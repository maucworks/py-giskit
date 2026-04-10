"""WMTS Provider - Config-driven provider for raster tile services.

This provider supports WMTS (Web Map Tile Service) for downloading
pre-rendered raster tiles like:
- Aerial imagery (orthophotos/luchtfoto's)
- Satellite imagery
- Background maps
- Other pre-rendered tile layers

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
from typing import Any

import geopandas as gpd

from giskit.core.constants import (
    JPEG_EXPORT_QUALITY,
    JPEG_OPTIMIZE,
    WMTS_DEFAULT_RESOLUTION_M,
)
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
    ) -> gpd.GeoDataFrame:
        """Download a dataset (imagery) for a specific location.

        Args:
            dataset: Dataset specification from recipe
            location: Location specification from recipe
            output_path: Where to save downloaded data (image file)
            output_crs: Output coordinate reference system (default: EPSG:28992)
            **kwargs: Additional download options:
                - zoom: Explicit zoom level (optional)
                - resolution: Target resolution in meters/pixel (optional)
                - layer: Specific layer name like "actueel_25cm" (optional)
                - progress_callback: Callback function for progress updates

        Returns:
            Empty GeoDataFrame (WMTS returns images, not vector data)

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

        # Transform to output CRS if needed
        if output_crs != "EPSG:4326":
            from giskit.core.spatial import transform_bbox

            bbox = transform_bbox(bbox_wgs84, "EPSG:4326", output_crs)
        else:
            bbox = bbox_wgs84

        # Extract WMTS-specific parameters
        zoom = kwargs.get("zoom")
        resolution = kwargs.get("resolution", dataset.resolution if dataset.resolution else None)
        progress_callback = kwargs.get("progress_callback")

        # Download imagery using WMTS protocol
        async with protocol:
            image = await protocol.get_coverage(
                bbox=bbox,  # type: ignore
                product=layer_key,
                resolution=resolution or WMTS_DEFAULT_RESOLUTION_M,
                crs=output_crs,
                zoom=zoom,
                progress_callback=progress_callback,
            )

        # Save if output path provided
        if output_path:
            # WMTS returns raster images, not vector data
            # Change extension from .gpkg to appropriate image format
            if output_path.suffix.lower() in [".gpkg", ".geojson", ".shp"]:
                # Replace vector format with image format, keeping the base name and directory
                image_format = self.services[service_name].get("tile_format", "jpeg")
                extension = ".jpg" if image_format == "jpeg" else f".{image_format}"
                # Keep directory and base name, just change extension
                output_path = output_path.parent / (output_path.stem + "_aerial" + extension)

            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Determine format from extension or use service config
            if output_path.suffix.lower() in [".jpg", ".jpeg"]:
                image.save(
                    str(output_path),
                    format="JPEG",
                    quality=JPEG_EXPORT_QUALITY,
                    optimize=JPEG_OPTIMIZE,
                )
            elif output_path.suffix.lower() == ".png":
                image.save(str(output_path), format="PNG", optimize=True)
            elif output_path.suffix.lower() == ".tif":
                image.save(str(output_path), format="TIFF")
            else:
                # Default to JPEG
                image.save(
                    str(output_path),
                    format="JPEG",
                    quality=JPEG_EXPORT_QUALITY,
                    optimize=JPEG_OPTIMIZE,
                )

        # WMTS returns images, not vector data
        # Return empty GeoDataFrame for now
        return gpd.GeoDataFrame()

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
