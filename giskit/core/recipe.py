"""Recipe models for defining spatial data download tasks.

A Recipe is a declarative JSON/YAML specification of:
- Where: Location (address, point, bbox)
- What: Datasets from providers (PDOK, OSM, Copernicus, etc.)
- How: Output format and CRS
"""

from enum import Enum
from pathlib import Path
from typing import Any, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


class LocationType(str, Enum):
    """Supported location specification types."""

    ADDRESS = "address"
    POINT = "point"
    BBOX = "bbox"
    POLYGON = "polygon"


class Location(BaseModel):
    """Location specification for spatial queries.

    Examples:
        Address with radius:
            {"type": "address", "value": "Dam 1, Amsterdam", "radius": 500}

        Point (WGS84) with radius:
            {"type": "point", "value": [52.3676, 4.9041], "radius": 1000}

        Bounding box (WGS84):
            {"type": "bbox", "value": [4.88, 52.36, 4.92, 52.38]}

        Polygon (WGS84):
            {"type": "polygon", "value": [[4.88, 52.36], [4.92, 52.36], ...]}
    """

    type: LocationType = Field(..., description="Type of location specification")
    value: Union[str, list[float], list[list[float]]] = Field(
        ..., description="Location value (depends on type)"
    )
    radius: Optional[float] = Field(
        None, description="Radius in meters (for address/point)", ge=0, le=50000
    )
    crs: str = Field("EPSG:4326", description="CRS of input coordinates (default WGS84)")

    @field_validator("value")
    @classmethod
    def validate_value(cls, v: Any, info) -> Any:
        """Validate location value based on type."""
        location_type = info.data.get("type")

        if location_type == LocationType.ADDRESS:
            if not isinstance(v, str) or not v.strip():
                raise ValueError("Address must be non-empty string")

        elif location_type == LocationType.POINT:
            if not isinstance(v, list) or len(v) != 2:
                raise ValueError("Point must be [lon, lat]")
            if not all(isinstance(x, (int, float)) for x in v):
                raise ValueError("Point coordinates must be numbers")

        elif location_type == LocationType.BBOX:
            if not isinstance(v, list) or len(v) != 4:
                raise ValueError("Bbox must be [minx, miny, maxx, maxy]")
            if not all(isinstance(x, (int, float)) for x in v):
                raise ValueError("Bbox coordinates must be numbers")
            minx, miny, maxx, maxy = v
            if minx >= maxx or miny >= maxy:
                raise ValueError("Invalid bbox: min must be < max")

        elif location_type == LocationType.POLYGON:
            if not isinstance(v, list) or not v:
                raise ValueError("Polygon must be list of coordinates")
            if not all(isinstance(coord, list) and len(coord) == 2 for coord in v):
                raise ValueError("Polygon coordinates must be [lon, lat] pairs")
            if len(v) < 3:
                raise ValueError("Polygon must have at least 3 points")

        return v

    @model_validator(mode="after")
    def validate_radius(self) -> "Location":
        """Ensure radius is provided for address/point types."""
        if self.type in (LocationType.ADDRESS, LocationType.POINT):
            if self.radius is None:
                raise ValueError(f"Radius required for {self.type.value} location")
        elif self.radius is not None:
            raise ValueError(f"Radius not applicable for {self.type.value} location")
        return self


class Dataset(BaseModel):
    """Dataset specification for a provider.

    Examples:
        PDOK BGT buildings:
            {"provider": "pdok", "service": "bgt", "layers": ["pand"]}

        PDOK BGT with temporal filter (only active features):
            {"provider": "pdok", "service": "bgt", "layers": ["wegdeel"],
             "temporal": "active"}

        PDOK BGT at specific date:
            {"provider": "pdok", "service": "bgt", "layers": ["wegdeel"],
             "temporal": "2024-01-01"}

        BAG3D with custom colors:
            {"provider": "bag3d", "service": "bag3d", "layers": ["lod22"],
             "colors": {
                 "roof": [0.8, 0.2, 0.1],
                 "wall": [0.9, 0.85, 0.75],
                 "default": [0.7, 0.7, 0.7]
             }}

        OSM Overpass query:
            {"provider": "osm", "query": "amenity=restaurant"}

        Copernicus DEM:
            {"provider": "copernicus", "product": "dem", "resolution": 30}
    """

    provider: str = Field(..., description="Provider name (pdok, osm, copernicus)")
    service: Optional[str] = Field(None, description="Service name (for OGC providers)")
    layers: Optional[list[str]] = Field(
        None, description="Layer names to download (for vector services)"
    )
    query: Optional[str] = Field(None, description="Query string (for Overpass, WFS filters)")
    product: Optional[str] = Field(None, description="Product name (for raster providers)")
    resolution: Optional[int] = Field(
        None, description="Resolution in meters (for raster)", ge=1, le=1000
    )
    temporal: Optional[str] = Field(
        "latest",
        description=(
            "Temporal filter: 'latest' (newest version per feature), "
            "'active' (only currently valid features), "
            "'all' (all historical versions), "
            "or ISO date like '2024-01-01'"
        ),
    )
    colors: Optional[dict[str, list[float]]] = Field(
        None,
        description=(
            "Color overrides for this dataset. "
            "Keys are surface types (roof/wall/default) or attribute values. "
            "Values are RGB lists [R, G, B] in 0-1 range. "
            "Example: {'roof': [0.8, 0.2, 0.1], 'wall': [0.9, 0.85, 0.75]}"
        ),
    )
    extra: dict[str, Any] = Field(default_factory=dict, description="Provider-specific parameters")

    @model_validator(mode="after")
    def validate_dataset(self) -> "Dataset":
        """Ensure required fields are present based on provider type."""
        # At least one of: service, query, product must be specified
        if not any([self.service, self.query, self.product]):
            raise ValueError("Must specify service, query, or product")
        return self


class OutputFormat(str, Enum):
    """Supported output formats."""

    GPKG = "gpkg"
    GEOJSON = "geojson"
    SHAPEFILE = "shp"
    FLATGEOBUF = "fgb"
    IFC = "ifc"
    GLB = "glb"


class IFCExportConfig(BaseModel):
    """IFC export configuration.

    IFC Coordinate System (IFC4+ Compliant):
        - Site placement is always at (0, 0, 0) - IFC best practice
        - Vertex coordinates are always relative to site (small local numbers)
        - IfcMapConversion (IFC4+) provides proper georeferencing to RD (EPSG:28992)
        - RD reference point also stored in properties for backward compatibility
        - BIM tools (Blender/Bonsai) can use IfcMapConversion to position model correctly

    IFC Versions:
        - IFC4X3_ADD2: Latest version with civil infrastructure support (IfcRoad, etc.)
        - IFC4: Standard IFC4 with IfcCivilElement fallback
        - IFC2X3: Legacy version with IfcBuildingElementProxy fallback

    Multiple IFC Versions:
        - Use ifc_versions to export to multiple IFC versions simultaneously
        - Each version creates a separate file: name_IFCVERSION.ifc
        - Example: {"path": "output.ifc", "ifc_versions": ["IFC4X3_ADD2", "IFC4"]}
        - Creates: output_IFC4X3_ADD2.ifc, output_IFC4.ifc

    GLB Export (Optional):
        - If glb_path is specified, will also export to GLB after IFC creation
        - GLB is created from IFC using IfcConvert (requires ifcopenshell)
        - GLB is ideal for web viewers (Three.js, Cesium, etc.)

    OBJ ZIP Export (Optional):
        - If obj_zip_path is specified, will export to OBJ ZIP after IFC creation
        - Creates a ZIP with OBJ+MTL files per layer

    Color Overrides:
        - Use layer_colors to override default colors per layer
        - Format: {"layer_name": {"surface_type": [R, G, B]}}
        - Example: {"bag3d_lod22": {"roof": [0.8, 0.2, 0.1], "wall": [0.9, 0.85, 0.75]}}
        - Surface types for BAG3D: "roof", "wall", "default"
        - For other layers: "default" only

    Examples:
        Export to IFC only:
            {"path": "output.ifc"}

        Export with specific IFC version:
            {"path": "output.ifc", "ifc_version": "IFC4"}

        Export to multiple IFC versions:
            {"path": "output.ifc", "ifc_versions": ["IFC4X3_ADD2", "IFC4", "IFC2X3"]}
            # Creates: output_IFC4X3_ADD2.ifc, output_IFC4.ifc, output_IFC2X3.ifc

        Export to IFC + GLB + OBJ:
            {
                "path": "output.ifc",
                "glb_path": "output.glb",
                "obj_zip_path": "output_obj.zip"
            }

        Export with absolute NAP elevations:
            {"path": "output.ifc", "normalize_z": false}

        Export with custom BAG3D colors:
            {"path": "output.ifc", "layer_colors": {
                "bag3d_lod22": {
                    "roof": [0.8, 0.2, 0.1],
                    "wall": [0.9, 0.85, 0.75]
                }
            }}
    """

    path: Path = Field(..., description="Output IFC file path")
    ifc_version: str = Field(
        "IFC4X3_ADD2", description="IFC schema version (IFC4X3_ADD2, IFC4, IFC2X3)"
    )
    ifc_versions: Optional[list[str]] = Field(
        None,
        description=(
            "Export to multiple IFC versions. Creates separate files: name_IFCVERSION.ifc. "
            "Valid versions: IFC4X3_ADD2, IFC4, IFC2X3"
        ),
    )
    site_name: Optional[str] = Field(
        None, description="Name for the IFC site (default: use address)"
    )
    normalize_z: bool = Field(
        True, description="Normalize Z to ground level (True) or keep NAP elevations (False)"
    )
    layer_colors: Optional[dict[str, dict[str, list[float]]]] = Field(
        None,
        description=(
            "Color overrides per layer. "
            "Format: {'layer_name': {'surface_type': [R, G, B]}}. "
            "For BAG3D: surface_type can be 'roof', 'wall', or 'default'. "
            "RGB values in 0-1 range."
        ),
    )
    glb_path: Optional[Path] = Field(
        None, description="Optional GLB export path (creates GLB from IFC)"
    )
    glb_use_world_coords: bool = Field(
        True, description="Use world coordinates in GLB (preserves geo-location)"
    )
    glb_center_model: bool = Field(
        False, description="Center GLB model at origin (useful for web viewers)"
    )
    glb_compress: bool = Field(
        True, description="Gzip compress GLB output (creates .glb.gz, ~80% size reduction)"
    )
    obj_zip_path: Optional[Path] = Field(
        None, description="Optional OBJ ZIP export path (creates layered OBJ+MTL from IFC)"
    )

    @field_validator("path")
    @classmethod
    def validate_ifc_path(cls, v: Path) -> Path:
        """Ensure path has .ifc extension."""
        if v.suffix.lower() != ".ifc":
            v = v.with_suffix(".ifc")
        return Path(v)

    @field_validator("ifc_versions")
    @classmethod
    def validate_ifc_versions(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        """Validate IFC version list."""
        if v is None:
            return None
        valid_versions = {"IFC4X3_ADD2", "IFC4", "IFC2X3"}
        for version in v:
            if version not in valid_versions:
                raise ValueError(
                    f"Invalid IFC version '{version}'. "
                    f"Valid versions: {', '.join(sorted(valid_versions))}"
                )
        return v


class Output(BaseModel):
    """Output specification for downloaded data.

    Examples:
        GeoPackage with custom CRS:
            {"path": "./data.gpkg", "format": "gpkg", "crs": "EPSG:28992"}

        GeoJSON (always WGS84):
            {"path": "./data.geojson", "format": "geojson"}

        GeoPackage with IFC export:
            {
                "path": "./data.gpkg",
                "format": "gpkg",
                "crs": "EPSG:28992",
                "ifc_export": {
                    "path": "output.ifc",
                    "relative": true,
                    "normalize_z": true
                }
            }
    """

    path: Path = Field(..., description="Output file path")
    format: OutputFormat = Field(OutputFormat.GPKG, description="Output format (default: gpkg)")
    crs: str = Field("EPSG:4326", description="Output CRS (default: WGS84)")
    overwrite: bool = Field(False, description="Overwrite existing file")
    layer_prefix: Optional[str] = Field(
        None, description="Prefix for layer names (e.g., 'amsterdam_')"
    )
    ifc_export: Optional[IFCExportConfig] = Field(
        None, description="Optional IFC export configuration (auto-export after GPKG creation)"
    )

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: Path) -> Path:
        """Ensure path has correct extension."""
        return Path(v)

    @model_validator(mode="after")
    def validate_output(self) -> "Output":
        """Ensure path extension matches format."""
        expected_ext = f".{self.format.value}"
        if self.path.suffix.lower() != expected_ext:
            # Auto-fix extension
            self.path = self.path.with_suffix(expected_ext)
        return self


class Recipe(BaseModel):
    """Complete recipe for downloading spatial data.

    Example:
        {
            "name": "Amsterdam restaurants",
            "location": {
                "type": "address",
                "value": "Dam 1, Amsterdam",
                "radius": 500
            },
            "datasets": [
                {"provider": "pdok", "service": "bgt", "layers": ["pand"]},
                {"provider": "osm", "query": "amenity=restaurant"}
            ],
            "output": {
                "path": "./amsterdam.gpkg",
                "crs": "EPSG:28992"
            }
        }
    """

    name: Optional[str] = Field(None, description="Human-readable recipe name")
    description: Optional[str] = Field(None, description="Recipe description")
    location: Location = Field(..., description="Location specification")
    datasets: list[Dataset] = Field(..., description="Datasets to download", min_length=1)
    output: Output = Field(..., description="Output specification")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Custom metadata")

    @classmethod
    def from_file(cls, path: Path) -> "Recipe":
        """Load recipe from JSON/YAML file."""
        import json

        with open(path) as f:
            data = json.load(f)
        return cls(**data)

    def to_file(self, path: Path) -> None:
        """Save recipe to JSON file."""
        import json

        with open(path, "w") as f:
            json.dump(self.model_dump(mode="json"), f, indent=2)

    async def get_bbox_wgs84(self) -> tuple[float, float, float, float]:
        """Get bounding box in WGS84 for this recipe's location.

        Returns:
            (minx, miny, maxx, maxy) in EPSG:4326

        Raises:
            ValueError: If location type is unknown
        """
        # Import here to avoid circular dependencies
        from giskit.core.geocoding import geocode
        from giskit.core.spatial import (
            buffer_point_to_bbox,
            polygon_to_bbox,
            transform_bbox,
        )

        if self.location.type == LocationType.BBOX:
            bbox = tuple(self.location.value)  # type: ignore
            if self.location.crs == "EPSG:4326":
                return bbox
            else:
                # Transform bbox to WGS84
                return transform_bbox(bbox, self.location.crs, "EPSG:4326")

        elif self.location.type == LocationType.POINT:
            lon, lat = self.location.value  # type: ignore
            if self.location.crs != "EPSG:4326":
                # Transform point to WGS84 first
                from giskit.core.spatial import transform_point

                lon, lat = transform_point(lon, lat, self.location.crs, "EPSG:4326")

            # Buffer point to create bbox
            assert self.location.radius is not None
            return buffer_point_to_bbox(lon, lat, self.location.radius)

        elif self.location.type == LocationType.ADDRESS:
            # Geocode address to get coordinates
            lon, lat = await geocode(self.location.value)  # type: ignore

            # Buffer to create bbox
            assert self.location.radius is not None
            return buffer_point_to_bbox(lon, lat, self.location.radius)

        elif self.location.type == LocationType.POLYGON:
            coords = self.location.value  # type: ignore
            bbox = polygon_to_bbox(coords, self.location.crs)

            if self.location.crs != "EPSG:4326":
                # Transform bbox to WGS84
                return transform_bbox(bbox, self.location.crs, "EPSG:4326")
            return bbox

        raise ValueError(f"Unknown location type: {self.location.type}")
