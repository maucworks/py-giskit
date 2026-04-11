"""WCS Provider - Config-driven provider for coverage/elevation data.

This provider supports WCS (Web Coverage Service) for downloading
raster coverage data like:
- Elevation models (DTM, DSM)
- AHN (Actueel Hoogtebestand Nederland)
- Temperature/climate data
- Other gridded/raster coverage data

For other protocols, use:
- OGCFeaturesProvider for vector data (OGC API Features)
- WMTSProvider for pre-rendered tile imagery
- WMSProvider for dynamic map rendering (not yet implemented)

Examples:
    >>> # Use with PDOK AHN elevation data
    >>> provider = WCSProvider("pdok-wcs")
    >>> services = provider.get_supported_services()
    >>>
    >>> # Use with custom WCS service
    >>> # Just create config/services/my-wcs.yml
    >>> provider = WCSProvider("my-wcs")
    >>> services = provider.get_supported_services()
"""

import logging
from pathlib import Path
from typing import Any, Union

import geopandas as gpd
import numpy as np

from giskit.core.raster import RasterResult
from giskit.core.recipe import Dataset, Location, LocationType
from giskit.protocols.wcs import WCSProtocol
from giskit.providers.base import register_provider
from giskit.providers.config_driven import ConfigDrivenProvider

logger = logging.getLogger(__name__)

# Colour palette for elevation: low=blue, mid=green, high=red (viridis-ish)
_ELEVATION_COLORMAP = [
    (0.267, 0.004, 0.329),  # deep purple  (very low)
    (0.282, 0.412, 0.639),  # blue
    (0.157, 0.620, 0.557),  # teal
    (0.486, 0.780, 0.345),  # green
    (0.980, 0.902, 0.141),  # yellow
    (0.988, 0.612, 0.122),  # orange
    (0.988, 0.302, 0.165),  # red-orange  (very high)
]


def _elevation_to_pil_image(array: np.ndarray):  # type: ignore[return]
    """Convert a 2-D elevation numpy array to a RGB PIL Image.

    Nodata values (NaN or <= -9999) are rendered as transparent grey.

    Args:
        array: 2-D float array of elevation values (metres).

    Returns:
        PIL Image in RGB mode.
    """
    from PIL import Image

    # Mask nodata
    nodata_mask = np.isnan(array) | (array <= -9999)
    valid = array[~nodata_mask]

    if valid.size == 0:
        # All nodata — return grey image
        h, w = array.shape
        return Image.new("RGB", (w, h), (128, 128, 128))

    vmin, vmax = float(valid.min()), float(valid.max())
    if vmax == vmin:
        vmax = vmin + 1.0  # prevent division by zero

    h, w = array.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)

    n_stops = len(_ELEVATION_COLORMAP) - 1
    for y in range(h):
        for x in range(w):
            if nodata_mask[y, x]:
                rgb[y, x] = (128, 128, 128)
            else:
                t = (float(array[y, x]) - vmin) / (vmax - vmin)
                t = max(0.0, min(1.0, t))
                idx = t * n_stops
                lo = int(idx)
                hi = min(lo + 1, n_stops)
                frac = idx - lo
                c0 = _ELEVATION_COLORMAP[lo]
                c1 = _ELEVATION_COLORMAP[hi]
                r = int((c0[0] + (c1[0] - c0[0]) * frac) * 255)
                g = int((c0[1] + (c1[1] - c0[1]) * frac) * 255)
                b = int((c0[2] + (c1[2] - c0[2]) * frac) * 255)
                rgb[y, x] = (r, g, b)

    return Image.fromarray(rgb, "RGB")


class WCSProvider(ConfigDrivenProvider):
    """WCS provider for coverage/elevation data.

    Loads services from YAML config files, making it work with any provider
    that offers WCS endpoints (raster coverage data).

    ``download_dataset()`` now returns a :class:`~giskit.core.raster.RasterResult`
    instead of a metadata GeoDataFrame.  Saving the GeoTIFF and JPEG is
    delegated to :class:`~giskit.core.output.OutputManager`.

    Supports:
    - WCS (Web Coverage Service)
    - Elevation data (DTM, DSM)
    - AHN lidar data
    - Climate/weather grids
    - Other gridded raster data

    Does NOT support:
    - Vector data (use OGCFeaturesProvider instead)
    - Pre-rendered tiles (use WMTSProvider instead)
    """

    def __init__(self, name: str, **kwargs: Any):
        """Initialize WCS provider.

        Args:
            name: Provider identifier (e.g., "pdok-wcs", "my-wcs")
                  Must have corresponding config/services/{name}.yml
            **kwargs: Additional configuration

        Raises:
            FileNotFoundError: If config file not found and no fallback provided
            ValueError: If config is invalid
        """
        # Call parent to load services from config
        super().__init__(name, **kwargs)

        # Register WCS protocols for each service/coverage
        self.protocols: dict[str, WCSProtocol] = {}

        for service_name, service_config in self.services.items():
            if isinstance(service_config, dict):
                url = service_config.get("url", "")
                coverages = service_config.get("coverages", {})
                native_crs = service_config.get("native_crs", "EPSG:28992")
                native_resolution = service_config.get("native_resolution")

                # Register protocol for each coverage
                for coverage_key, coverage_id in coverages.items():
                    # Create protocol key: service.coverage (e.g., "ahn.dsm", "ahn.dtm")
                    protocol_key = f"{service_name}.{coverage_key}"

                    self.protocols[protocol_key] = WCSProtocol(
                        base_url=url,
                        coverage_id=coverage_id,
                        native_crs=native_crs,
                        native_resolution=native_resolution,
                    )

        logger.info("WCSProvider initialized")
        logger.info(f"  Loaded {len(self.services)} services from config")
        logger.debug(f"  Registered {len(self.protocols)} coverage protocols")
        logger.debug(f"  Available coverages: {list(self.protocols.keys())}")

    async def download_dataset(
        self,
        dataset: Dataset,
        location: Location,
        output_path: Path,
        output_crs: str = "EPSG:4326",
        **kwargs: Any,
    ) -> Union[RasterResult, gpd.GeoDataFrame]:
        """Download a dataset for a specific location.

        Args:
            dataset: Dataset specification from recipe
            location: Location specification from recipe
            output_path: Where to save downloaded data (directory used for
                         intermediate files; final saving done by OutputManager)
            output_crs: Output coordinate reference system
            **kwargs: Additional download options (e.g., resolution, format)

        Returns:
            RasterResult with the elevation PIL Image and bbox georeferencing.

        Raises:
            ValueError: If service not found
            NotImplementedError: Protocol not yet implemented for this location type
        """
        # Parse dataset name: "service.coverage" (e.g., "ahn.dtm", "ahn.dsm")
        service_name = dataset.service or ""
        if "." not in service_name:
            raise ValueError(
                f"WCS dataset must be in format 'service.coverage' (e.g., 'ahn.dtm'). "
                f"Got: '{service_name}'"
            )

        protocol_key = service_name

        if protocol_key not in self.protocols:
            raise ValueError(
                f"Coverage '{protocol_key}' not found. "
                f"Available coverages: {', '.join(self.protocols.keys())}"
            )

        # Get protocol
        protocol = self.protocols[protocol_key]

        # For now, only bbox locations are supported for WCS
        if location.type != LocationType.BBOX:
            raise NotImplementedError(
                f"Location type '{location.type.value}' not yet supported for WCS. "
                "Use bbox for now."
            )

        if not isinstance(location.value, list) or len(location.value) != 4:
            raise ValueError("Location value must be [minx, miny, maxx, maxy] for bbox")

        # Extract bbox values
        bbox_values = location.value
        if not all(isinstance(v, (int, float)) for v in bbox_values):
            raise ValueError("All bbox values must be numbers")

        bbox_rd: tuple[float, float, float, float] = (
            float(bbox_values[0]),  # type: ignore[arg-type]
            float(bbox_values[1]),  # type: ignore[arg-type]
            float(bbox_values[2]),  # type: ignore[arg-type]
            float(bbox_values[3]),  # type: ignore[arg-type]
        )

        # Transform bbox to WGS84 for the RasterResult metadata
        from giskit.core.spatial import transform_bbox

        try:
            bbox_wgs84 = transform_bbox(bbox_rd, "EPSG:28992", "EPSG:4326")
        except Exception:
            bbox_wgs84 = bbox_rd  # fallback: keep as-is

        # Get resolution from dataset or use default
        resolution = dataset.resolution or protocol.native_resolution or 0.5

        logger.info(f"Downloading {protocol_key}...")
        logger.debug(f"  Resolution: {resolution}m")
        logger.debug(f"  Bbox: {bbox_rd}")

        def _progress(msg: str, pct: float) -> None:
            logger.debug(f"  [{pct * 100:.0f}%] {msg}")

        # Download the raw elevation array via the protocol
        async with protocol:
            array = await protocol.get_coverage(
                bbox=bbox_rd,
                product=protocol_key,
                resolution=resolution,
                crs="EPSG:28992",
                progress_callback=_progress,
            )

        logger.info(f"Downloaded {protocol_key}: shape={array.shape}")

        # Convert elevation array to a false-colour PIL Image for visualisation
        image = _elevation_to_pil_image(array)

        # Build canonical layer name: "ahn_dtm"
        layer_name = protocol_key.replace(".", "_").replace("-", "_")

        return RasterResult(
            layer_name=layer_name,
            image=image,
            bbox_rd=bbox_rd,
            bbox_wgs84=tuple(bbox_wgs84),  # type: ignore[arg-type]
            source_crs="EPSG:28992",
        )

    def get_supported_protocols(self) -> list[str]:
        """Get list of supported protocols.

        Returns:
            List of protocol names
        """
        return ["wcs"]


# Register WCS provider globally
register_provider("wcs", WCSProvider)
