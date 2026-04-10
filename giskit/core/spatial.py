"""Spatial utilities for coordinate transformations and geometric operations."""

from typing import TYPE_CHECKING, List, Tuple

import pyproj
from pyproj import Transformer
from shapely.geometry import Point, Polygon, box
from shapely.ops import transform

if TYPE_CHECKING:
    from giskit.core.recipe import Location


class SpatialError(Exception):
    """Raised when spatial operations fail."""

    pass


def buffer_point_to_bbox(
    lon: float, lat: float, radius_m: float, crs: str = "EPSG:4326"
) -> Tuple[float, float, float, float]:
    """Buffer a point by radius to create a bounding box.

    Uses equal-area projection for accurate metric buffering.

    Args:
        lon: Longitude in specified CRS
        lat: Latitude in specified CRS
        radius_m: Buffer radius in meters
        crs: Input/output CRS (default: EPSG:4326)

    Returns:
        Tuple of (minx, miny, maxx, maxy) in specified CRS

    Raises:
        SpatialError: If buffering fails
    """
    try:
        # Create point geometry
        point = Point(lon, lat)

        # If input is WGS84, project to equal-area for accurate metric buffer
        if crs == "EPSG:4326":
            # Use Azimuthal Equidistant projection centered on point
            # This gives accurate distances in all directions from the center
            proj_string = (
                f"+proj=aeqd +lat_0={lat} +lon_0={lon} +x_0=0 +y_0=0 +datum=WGS84 +units=m"
            )

            # Transform to projected CRS
            transformer_to_proj = Transformer.from_crs("EPSG:4326", proj_string, always_xy=True)
            point_proj = transform(transformer_to_proj.transform, point)

            # Buffer in meters
            buffered_proj = point_proj.buffer(radius_m)

            # Transform back to WGS84
            transformer_to_wgs84 = Transformer.from_crs(proj_string, "EPSG:4326", always_xy=True)
            buffered = transform(transformer_to_wgs84.transform, buffered_proj)
        else:
            # For other CRS, assume units are meters (or accept inaccuracy)
            # TODO: Implement proper CRS unit detection
            buffered = point.buffer(radius_m)

        # Get bounding box
        bounds = buffered.bounds
        return bounds

    except Exception as e:
        raise SpatialError(f"Failed to buffer point: {e}") from e


def polygon_to_bbox(
    coords: List[Tuple[float, float]], crs: str = "EPSG:4326"
) -> Tuple[float, float, float, float]:
    """Calculate bounding box from polygon coordinates.

    Args:
        coords: List of (lon, lat) or (x, y) coordinate tuples
        crs: Coordinate reference system (not used, kept for consistency)

    Returns:
        Tuple of (minx, miny, maxx, maxy)

    Raises:
        SpatialError: If polygon is invalid
    """
    try:
        if len(coords) < 3:
            raise SpatialError("Polygon must have at least 3 points")

        polygon = Polygon(coords)

        if not polygon.is_valid:
            raise SpatialError("Invalid polygon geometry")

        return polygon.bounds

    except Exception as e:
        raise SpatialError(f"Failed to calculate polygon bbox: {e}") from e


def transform_bbox(
    bbox: Tuple[float, float, float, float], from_crs: str, to_crs: str
) -> Tuple[float, float, float, float]:
    """Transform bounding box from one CRS to another.

    Args:
        bbox: (minx, miny, maxx, maxy) in from_crs
        from_crs: Source CRS (e.g., "EPSG:4326")
        to_crs: Target CRS (e.g., "EPSG:28992")

    Returns:
        Transformed (minx, miny, maxx, maxy) in to_crs

    Raises:
        SpatialError: If transformation fails
    """
    try:
        if from_crs == to_crs:
            return bbox

        # Create box geometry
        minx, miny, maxx, maxy = bbox
        geom = box(minx, miny, maxx, maxy)

        # Transform
        transformer = Transformer.from_crs(from_crs, to_crs, always_xy=True)
        transformed_geom = transform(transformer.transform, geom)

        return transformed_geom.bounds

    except Exception as e:
        raise SpatialError(f"Failed to transform bbox from {from_crs} to {to_crs}: {e}") from e


def transform_point(lon: float, lat: float, from_crs: str, to_crs: str) -> Tuple[float, float]:
    """Transform a point from one CRS to another.

    Args:
        lon: Longitude/X coordinate in from_crs
        lat: Latitude/Y coordinate in from_crs
        from_crs: Source CRS (e.g., "EPSG:4326")
        to_crs: Target CRS (e.g., "EPSG:28992")

    Returns:
        Tuple of (x, y) in to_crs

    Raises:
        SpatialError: If transformation fails
    """
    try:
        if from_crs == to_crs:
            return (lon, lat)

        transformer = Transformer.from_crs(from_crs, to_crs, always_xy=True)
        x, y = transformer.transform(lon, lat)

        return (x, y)

    except Exception as e:
        raise SpatialError(f"Failed to transform point from {from_crs} to {to_crs}: {e}") from e


def validate_crs(crs: str) -> bool:
    """Validate that a CRS string is recognized by pyproj.

    Args:
        crs: CRS string (e.g., "EPSG:4326")

    Returns:
        True if valid, False otherwise
    """
    try:
        pyproj.CRS(crs)
        return True
    except Exception:
        return False


def get_crs_info(crs: str) -> dict:
    """Get information about a CRS.

    Args:
        crs: CRS string (e.g., "EPSG:4326")

    Returns:
        Dictionary with CRS metadata

    Raises:
        SpatialError: If CRS is invalid
    """
    try:
        crs_obj = pyproj.CRS(crs)
        return {
            "name": crs_obj.name,
            "type": crs_obj.type_name,
            "area": crs_obj.area_of_use.name if crs_obj.area_of_use else None,
            "unit": crs_obj.axis_info[0].unit_name if crs_obj.axis_info else None,
        }
    except Exception as e:
        raise SpatialError(f"Invalid CRS '{crs}': {e}") from e


def subdivide_bbox(
    bbox: Tuple[float, float, float, float], cell_size: float, crs: str = "EPSG:28992"
) -> List[Tuple[float, float, float, float]]:
    """Subdivide large bounding box into smaller grid cells.

    This is useful for downloading large datasets in chunks to:
    - Avoid timeouts on slow APIs
    - Work around API feature limits
    - Enable parallel downloads
    - Show progress for large areas

    Args:
        bbox: (minx, miny, maxx, maxy) in specified CRS
        cell_size: Size of each grid cell in CRS units (e.g., 250 meters for EPSG:28992)
        crs: Coordinate reference system (default: EPSG:28992 for Dutch data)

    Returns:
        List of (minx, miny, maxx, maxy) tuples for each grid cell

    Example:
        >>> # Split 1km x 1km area into 250m x 250m cells
        >>> bbox = (80000, 429000, 81000, 430000)
        >>> cells = subdivide_bbox(bbox, cell_size=250)
        >>> len(cells)
        16  # 4x4 grid
    """
    minx, miny, maxx, maxy = bbox

    # Calculate number of cells in each direction
    width = maxx - minx
    height = maxy - miny

    cols = int((width + cell_size - 1) // cell_size)  # Ceiling division
    rows = int((height + cell_size - 1) // cell_size)

    cells = []
    for row in range(rows):
        for col in range(cols):
            cell_minx = minx + col * cell_size
            cell_miny = miny + row * cell_size
            cell_maxx = min(cell_minx + cell_size, maxx)
            cell_maxy = min(cell_miny + cell_size, maxy)

            cells.append((cell_minx, cell_miny, cell_maxx, cell_maxy))

    return cells


async def location_to_bbox(
    location: "Location",  # type: ignore  # Forward reference
    target_crs: str = "EPSG:4326",
) -> Tuple[float, float, float, float]:
    """Convert any Location type to bounding box in specified CRS.

    This is a unified helper that handles all location types:
    - address → geocode → buffer → bbox
    - point → buffer → bbox
    - bbox → transform if needed
    - polygon → bbox → transform if needed

    Args:
        location: Location specification (from giskit.core.recipe)
        target_crs: Target CRS for the bbox (default: WGS84)

    Returns:
        Tuple of (minx, miny, maxx, maxy) in target_crs

    Raises:
        SpatialError: If location conversion fails

    Examples:
        >>> from giskit.core.recipe import Location, LocationType
        >>>
        >>> # Address with radius
        >>> loc = Location(type=LocationType.ADDRESS, value="Dam 1, Amsterdam", radius=500)
        >>> bbox = await location_to_bbox(loc, "EPSG:28992")
        >>>
        >>> # Point with radius
        >>> loc = Location(type=LocationType.POINT, value=[52.3676, 4.9041], radius=1000)
        >>> bbox = await location_to_bbox(loc)
        >>>
        >>> # Bbox (just transform if needed)
        >>> loc = Location(type=LocationType.BBOX, value=[4.88, 52.36, 4.92, 52.38])
        >>> bbox = await location_to_bbox(loc, "EPSG:28992")
    """
    try:
        # Import here to avoid circular dependencies
        from giskit.core.geocoding import geocode
        from giskit.core.recipe import LocationType

        if location.type == LocationType.BBOX:
            # Bbox - just transform if needed
            bbox = tuple(location.value)  # type: ignore
            if location.crs == target_crs:
                return bbox  # type: ignore
            else:
                return transform_bbox(bbox, location.crs, target_crs)  # type: ignore

        elif location.type == LocationType.POINT:
            # Point with radius - buffer to create bbox
            lon, lat = location.value  # type: ignore

            if location.crs != "EPSG:4326":
                # Transform point to WGS84 first for geocoding
                lon, lat = transform_point(lon, lat, location.crs, "EPSG:4326")

            # Buffer point to create bbox (in WGS84)
            if location.radius is None:
                raise SpatialError("Radius is required for point location")
            bbox_wgs84 = buffer_point_to_bbox(lon, lat, location.radius)

            # Transform to target CRS if needed
            if target_crs != "EPSG:4326":
                return transform_bbox(bbox_wgs84, "EPSG:4326", target_crs)
            return bbox_wgs84

        elif location.type == LocationType.ADDRESS:
            # Address - geocode first, then buffer
            address = location.value  # type: ignore
            lon, lat = await geocode(address)

            # Buffer to create bbox (in WGS84)
            if location.radius is None:
                raise SpatialError("Radius is required for address location")
            bbox_wgs84 = buffer_point_to_bbox(lon, lat, location.radius)

            # Transform to target CRS if needed
            if target_crs != "EPSG:4326":
                return transform_bbox(bbox_wgs84, "EPSG:4326", target_crs)
            return bbox_wgs84

        elif location.type == LocationType.POLYGON:
            # Polygon - calculate bbox from coordinates
            coords = location.value  # type: ignore
            bbox = polygon_to_bbox(coords, location.crs)  # type: ignore

            # Transform to target CRS if needed
            if location.crs != target_crs:
                return transform_bbox(bbox, location.crs, target_crs)
            return bbox

        else:
            raise SpatialError(f"Unknown location type: {location.type}")

    except Exception as e:
        if isinstance(e, SpatialError):
            raise
        raise SpatialError(f"Failed to convert location to bbox: {e}") from e
