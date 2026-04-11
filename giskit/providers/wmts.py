"""WMTS Provider - Config-driven provider for raster tile services.

This provider supports WMTS (Web Map Tile Service) for downloading
pre-rendered raster tiles like:
- Aerial imagery (orthophotos/luchtfoto's)
- Satellite imagery
- Background maps
- Other pre-rendered tile pyramids

For other protocols, use:
- OGCFeaturesProvider for vector data (OGC API Features)
- WCSProvider for coverage/elevation data
- WMSProvider for dynamic map rendering (not yet implemented)

Examples:
    >>> # Use with PDOK luchtfoto
    >>> provider = WMTSProvider("pdok-wmts")
    >>> services = provider.get_supported_services()
    >>>
    >>> # Use with custom WMTS service
    >>> # Just create config/services/my-wmts.yml
    >>> provider = WMTSProvider("my-wmts")
    >>> services = provider.get_supported_services()
"""

from pathlib import Path
from typing import Any, Union

import geopandas as gpd

from giskit.core.constants import WMTS_DEFAULT_RESOLUTION_M
from giskit.core.raster import RasterResult
from giskit.core.recipe import Dataset, Location
from giskit.protocols.wmts import WMTSProtocol
from giskit.providers.base import register_provider
from giskit.providers.config_driven import ConfigDrivenProvider


class WMTSProvider(ConfigDrivenProvider):
    """WMTS provider for raster tile services.

    Loads services from YAML config files, making it work with any provider
    that offers WMTS endpoints (pre-rendered tiles).

    Supports:
    - WMTS (Web Map Tile Service)
    - Aerial imagery
    - Satellite imagery
    - Background maps
    - Pre-rendered tile pyramids

    Does NOT support:
    - Vector data (use OGCFeaturesProvider instead)
    - Coverage/elevation data (use WCSProvider instead)
    - Dynamic WMS rendering (use WMSProvider if needed)
    """

    def __init__(self, name: str, **kwargs: Any):
        """Initialize WMTS provider.

        Args:
            name: Provider identifier (e.g., "pdok-wmts", "my-wmts")
                  Must have corresponding config/services/{name}.yml
            **kwargs: Additional configuration

        Raises:
            FileNotFoundError: If config file not found and no fallback provided
            ValueError: If config is invalid
        """
        # Call parent to load services from config
        super().__init__(name, **kwargs)

        # Register WMTS protocols for each service
        self.protocols: dict[str, WMTSProtocol] = {}
        for service_name, service_config in self.services.items():
            if isinstance(service_config, dict):
                # Extract WMTS configuration
                url = service_config.get("url", "")
                layers = service_config.get("layers", {})

                # Register protocol for each layer
                for layer_key, layer_name in layers.items():
                    protocol_key = f"{service_name}.{layer_key}"
                    self.protocols[protocol_key] = WMTSProtocol(
                        base_url=url,
                        layer=layer_name,
                        tile_matrix_set=service_config.get("tile_matrix_set", "EPSG:28992"),
                        tile_format=service_config.get("tile_format", "jpeg"),
                    )

    async def download_dataset(
        self,
        dataset: Dataset,
        location: Location,
        output_path: Path,
        output_crs: str = "EPSG:28992",
        **kwargs: Any,
    ) -> Union[RasterResult, gpd.GeoDataFrame]:
        """Download a dataset (imagery) for a specific location.

        Args:
            dataset: Dataset specification from recipe
            location: Location specification from recipe
            output_path: Where to save downloaded data (used only for directory)
            output_crs: Output coordinate reference system (default: EPSG:28992)
            **kwargs: Additional download options:
                - zoom: Explicit zoom level (optional)
                - resolution: Target resolution in metres/pixel (optional)
                - progress_callback: Callback function for progress updates

        Returns:
            RasterResult containing the stitched PIL Image and georeferencing
            info.  Saving to disk is delegated to OutputManager.

        Raises:
            ValueError: If service or layer not found
        """
        # Validate service format
        if not dataset.service:
            raise ValueError("Dataset.service is required for WMTS provider")

        service_parts = dataset.service.split(".", 1)
        if len(service_parts) != 2:
            raise ValueError(
                f"WMTS service must be specified as 'service.layer' (e.g., 'luchtfoto.actueel_25cm'), "
                f"got: {dataset.service}"
            )

        service_name, layer_key = service_parts
        protocol_key = f"{service_name}.{layer_key}"

        if protocol_key not in self.protocols:
            available = list(self.protocols.keys())
            raise ValueError(
                f"Service layer '{protocol_key}' not found. Available: {', '.join(available)}"
            )

        protocol = self.protocols[protocol_key]

        # Convert location to bbox in output CRS
        from giskit.core.spatial import location_to_bbox

        # Get bbox in WGS84 first
        bbox_wgs84 = await location_to_bbox(location, "EPSG:4326")

        # Transform to output CRS (RD New by default) for tile fetching
        if output_crs != "EPSG:4326":
            from giskit.core.spatial import transform_bbox

            bbox_rd = transform_bbox(bbox_wgs84, "EPSG:4326", output_crs)
        else:
            bbox_rd = bbox_wgs84

        # Extract WMTS-specific parameters
        zoom = kwargs.get("zoom")
        resolution = kwargs.get("resolution", dataset.resolution if dataset.resolution else None)
        progress_callback = kwargs.get("progress_callback")

        # Download imagery using WMTS protocol
        async with protocol:
            image = await protocol.get_coverage(
                bbox=bbox_rd,  # type: ignore
                product=layer_key,
                resolution=float(resolution or WMTS_DEFAULT_RESOLUTION_M),
                crs=output_crs,
                zoom=zoom,
                progress_callback=progress_callback,
            )

        # Build a canonical layer name: "luchtfoto_actueel_25cm"
        layer_name = protocol_key.replace(".", "_").replace("-", "_")

        return RasterResult(
            layer_name=layer_name,
            image=image,
            bbox_rd=tuple(bbox_rd),  # type: ignore[arg-type]
            bbox_wgs84=tuple(bbox_wgs84),  # type: ignore[arg-type]
            source_crs=output_crs,
        )

    def get_supported_protocols(self) -> list[str]:
        """Get list of supported protocols.

        Returns:
            List of protocol names
        """
        return ["wmts"]


# Register WMTS provider globally
register_provider("wmts", WMTSProvider)

# Register PDOK WMTS provider explicitly
register_provider("pdok-wmts", WMTSProvider)
