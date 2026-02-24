"""OGC API Features Provider - Config-driven provider for OGC API Features.

This is a generic provider that loads services and quirks from YAML config files.
It supports OGC API Features (vector data) endpoints only.

For other protocols, use:
- WMSProvider for raster tiles (WMS/WMTS)
- WFSProvider for legacy Web Feature Service
- WCSProvider for coverage/raster data

Examples:
    >>> # Use with PDOK
    >>> provider = OGCFeaturesProvider("pdok")
    >>> services = provider.get_supported_services()
    >>>
    >>> # Use with custom provider
    >>> # Just create config/services/myapi.yml
    >>> provider = OGCFeaturesProvider("myapi")
    >>> services = provider.get_supported_services()

This replaces hardcoded provider classes like PDOKProvider.
"""

from pathlib import Path
from typing import Any

import geopandas as gpd

from giskit.core.recipe import Dataset, Location
from giskit.protocols.ogc_features import OGCFeaturesProtocol
from giskit.providers.base import register_provider
from giskit.providers.config_driven import ConfigDrivenProvider


class OGCFeaturesProvider(ConfigDrivenProvider):
    """OGC API Features provider.

    Loads services from YAML config files, making it work with any provider
    that offers OGC API Features endpoints (vector data).

    Supports:
    - GeoJSON format
    - CityJSON format (3D buildings)
    - Feature collections with attributes

    Does NOT support:
    - Raster data (use WMSProvider instead)
    - Legacy WFS (use WFSProvider instead)
    - Coverage data (use WCSProvider instead)
    """

    def __init__(self, name: str, **kwargs: Any):
        """Initialize OGC API Features provider.

        Args:
            name: Provider identifier (e.g., "pdok", "myapi")
                  Must have corresponding config/services/{name}.yml
            **kwargs: Additional configuration

        Raises:
            FileNotFoundError: If config file not found and no fallback provided
            ValueError: If config is invalid
        """
        # Call parent to load services from config
        super().__init__(name, **kwargs)

        # Register OGC Features protocols for each service
        for service_name, service_config in self.services.items():
            # Handle both old string format and new dict format
            if isinstance(service_config, str):
                service_url = service_config
            else:
                service_url = service_config["url"]

            # Get service-specific quirks (handles fallback to provider/format quirks)
            from giskit.protocols.quirks import get_service_quirks

            quirks = get_service_quirks(name, "ogc-features", service_name)

            # Create and register protocol for this service
            protocol = OGCFeaturesProtocol(base_url=service_url, quirks=quirks)
            self.register_protocol(f"ogc-features-{service_name}", protocol)

    async def download_dataset(
        self,
        dataset: Dataset,
        location: Location,
        output_path: Path,
        output_crs: str = "EPSG:4326",
        **kwargs: Any,
    ) -> gpd.GeoDataFrame:
        """Download a dataset for a specific location.

        Args:
            dataset: Dataset specification from recipe
            location: Location specification from recipe
            output_path: Where to save downloaded data
            output_crs: Output coordinate reference system
            **kwargs: Additional download options

        Returns:
            GeoDataFrame with downloaded data

        Raises:
            ValueError: If service not found
        """
        # Get service from dataset
        service = dataset.service
        if service not in self.services:
            raise ValueError(
                f"Service '{service}' not found for provider '{self.name}'. "
                f"Available: {', '.join(self.services.keys())}"
            )

        # Get protocol for this service
        protocol_name = f"ogc-features-{service}"
        protocol = self.get_protocol(protocol_name)

        if protocol is None:
            raise ValueError(f"Protocol not registered: {protocol_name}")

        # Convert location to bbox using spatial helper
        from giskit.core.spatial import location_to_bbox

        bbox = await location_to_bbox(location, "EPSG:4326")

        # Get temporal filter from dataset (default to 'latest')
        temporal = (
            dataset.temporal if hasattr(dataset, "temporal") and dataset.temporal else "latest"
        )

        # Download features using OGC API
        async with protocol:
            gdf = await protocol.get_features(
                bbox=bbox,  # type: ignore
                layers=dataset.layers,
                crs=output_crs,
                temporal=temporal,
                **kwargs,
            )

        return gdf

    def get_supported_protocols(self) -> list[str]:
        """Get list of supported protocols.

        Returns:
            List of protocol names
        """
        return ["ogc-features"]


# Register OGC API Features provider globally
register_provider("ogc-features", OGCFeaturesProvider)
