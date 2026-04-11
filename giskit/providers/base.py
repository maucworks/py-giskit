"""Base Provider class for data providers.

A Provider represents an organization/service that offers spatial data:
- PDOK (Netherlands)
- OpenStreetMap
- Copernicus (EU)
- USGS (USA)
- etc.

Each provider can support multiple protocols (e.g., PDOK supports OGC Features, WFS, WMTS).
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

import geopandas as gpd

from giskit.core.recipe import Dataset, Location
from giskit.protocols.base import Protocol

if TYPE_CHECKING:
    from giskit.core.raster import RasterResult


class Provider(ABC):
    """Abstract base class for all data providers."""

    def __init__(self, name: str, **kwargs: Any):
        """Initialize provider.

        Args:
            name: Provider identifier (e.g., 'pdok', 'osm')
            **kwargs: Provider-specific configuration
        """
        self.name = name
        self.config = kwargs
        self._protocols: dict[str, Protocol] = {}

    @abstractmethod
    async def get_metadata(self) -> dict[str, Any]:
        """Get provider metadata.

        Returns:
            Dictionary with provider info:
            {
                "name": str,
                "description": str,
                "homepage": str,
                "services": list[str],
                "coverage": str,  # e.g., "Netherlands", "Global"
                "attribution": str
            }
        """
        pass

    @abstractmethod
    async def download_dataset(
        self,
        dataset: Dataset,
        location: Location,
        output_path: Path,
        output_crs: str = "EPSG:4326",
        **kwargs: Any,
    ) -> "Union[gpd.GeoDataFrame, RasterResult]":
        """Download a dataset for a specific location.

        Args:
            dataset: Dataset specification from recipe
            location: Location specification from recipe
            output_path: Where to save downloaded data
            output_crs: Output coordinate reference system
            **kwargs: Additional download options

        Returns:
            GeoDataFrame with downloaded vector data, or RasterResult for
            raster providers (WMTS imagery, WCS elevation).

        Raises:
            ValueError: If dataset configuration is invalid
            NotImplementedError: If provider doesn't support this dataset type
        """
        pass

    @abstractmethod
    def get_supported_services(self) -> list[str]:
        """Get list of supported services.

        Returns:
            List of service names (e.g., ['bgt', 'bag', 'bag3d'] for PDOK)
        """
        pass

    @abstractmethod
    def get_supported_protocols(self) -> list[str]:
        """Get list of supported protocols.

        Returns:
            List of protocol names (e.g., ['ogc-features', 'wfs', 'wmts'])
        """
        pass

    @abstractmethod
    def get_service_info(self, service_id: str) -> dict[str, Any]:
        """Get detailed information about a specific service.

        Args:
            service_id: Service identifier

        Returns:
            Dictionary with service metadata:
            {
                "name": str,
                "title": str,
                "description": str,
                "url": str,
                "protocol": str,
                "category": str,
                "keywords": list[str],
                ...
            }

        Raises:
            ValueError: If service not found
        """
        pass

    @abstractmethod
    def list_categories(self) -> list[str]:
        """Get list of all service categories.

        Returns:
            Sorted list of unique category names
            (e.g., ['base_registers', 'elevation', 'imagery'])
        """
        pass

    @abstractmethod
    def get_services_by_category(self, category: str) -> list[str]:
        """Get services in a specific category.

        Args:
            category: Category name (e.g., 'elevation', 'imagery')

        Returns:
            List of service identifiers in that category
        """
        pass

    def get_services_by_protocol(self, protocol: str) -> list[str]:
        """Get services that use a specific protocol.

        This is optional - only multi-protocol providers need to implement this.
        Single-protocol providers can use the default implementation which
        returns all services if they match the protocol.

        Args:
            protocol: Protocol name (e.g., 'ogc-features', 'wcs', 'wmts')

        Returns:
            List of service identifiers that use this protocol
        """
        # Default: return all services if provider supports this protocol
        supported = self.get_supported_protocols()
        if protocol in supported:
            return self.get_supported_services()
        return []

    def register_protocol(self, name: str, protocol: Protocol) -> None:
        """Register a protocol instance for this provider.

        Args:
            name: Protocol identifier
            protocol: Protocol instance
        """
        self._protocols[name] = protocol

    def get_protocol(self, name: str) -> Optional[Protocol]:
        """Get a registered protocol instance.

        Args:
            name: Protocol identifier

        Returns:
            Protocol instance or None if not registered
        """
        return self._protocols.get(name)

    async def __aenter__(self) -> "Provider":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        # Clean up all protocols
        for protocol in self._protocols.values():
            await protocol.__aexit__(exc_type, exc_val, exc_tb)


class ProviderRegistry:
    """Registry for all available providers."""

    def __init__(self) -> None:
        """Initialize empty provider registry."""
        self._providers: dict[str, type[Provider]] = {}

    def register(self, name: str, provider_class: type[Provider]) -> None:
        """Register a provider class.

        Args:
            name: Provider identifier (e.g., 'pdok')
            provider_class: Provider class (not instance)
        """
        self._providers[name] = provider_class

    def get(self, name: str) -> Optional[type[Provider]]:
        """Get a provider class by name.

        Args:
            name: Provider identifier

        Returns:
            Provider class or None if not found
        """
        return self._providers.get(name)

    def list_providers(self) -> list[str]:
        """Get list of all available provider names.

        Includes both explicitly registered and auto-discovered providers.

        Returns:
            List of provider identifiers
        """
        from giskit.config.discovery import list_providers as discover_list

        # Combine explicit registrations with auto-discovered
        explicit = list(self._providers.keys())
        discovered = discover_list()

        # Return unique sorted list
        return sorted(set(explicit + discovered))

    def create(self, name: str, **kwargs: Any) -> Provider:
        """Create a provider instance.

        Uses auto-discovery if provider not explicitly registered.
        Falls back to config-driven instantiation based on protocol.

        Args:
            name: Provider identifier
            **kwargs: Provider-specific configuration

        Returns:
            Provider instance

        Raises:
            ValueError: If provider not found
        """
        # First check explicit registrations (backward compatibility)
        provider_class = self.get(name)
        if provider_class is not None:
            return provider_class(name=name, **kwargs)

        # Try auto-discovery from config
        from giskit.config.discovery import get_provider_config

        config = get_provider_config(name)
        if config is None:
            raise ValueError(
                f"Provider '{name}' not found. Available: {', '.join(self.list_providers())}"
            )

        # Check config format
        config_format = config.get("format", "split")

        if config_format == "unified":
            # Unified multi-protocol provider
            from giskit.providers.multi_protocol import MultiProtocolProvider

            return MultiProtocolProvider(
                name=config["base_name"], config_file=config.get("config_file"), **kwargs
            )

        # Legacy split format - instantiate based on single protocol
        protocol = config.get("protocol")
        if not protocol:
            raise ValueError(f"No protocol specified for provider '{name}'")

        if protocol == "ogc-features":
            from giskit.providers.ogc_features import OGCFeaturesProvider

            return OGCFeaturesProvider(name=config["base_name"], **kwargs)
        elif protocol == "wcs":
            from giskit.providers.wcs import WCSProvider

            return WCSProvider(name=f"{config['base_name']}-wcs", **kwargs)
        elif protocol == "wmts":
            from giskit.providers.wmts import WMTSProvider

            return WMTSProvider(name=f"{config['base_name']}-wmts", **kwargs)
        else:
            raise ValueError(f"Unknown protocol '{protocol}' for provider '{name}'")


# Global provider registry
_registry = ProviderRegistry()


def register_provider(name: str, provider_class: type[Provider]) -> None:
    """Register a provider in the global registry.

    Args:
        name: Provider identifier
        provider_class: Provider class
    """
    _registry.register(name, provider_class)


def get_provider(name: str, **kwargs: Any) -> Provider:
    """Get a provider instance from the global registry.

    Args:
        name: Provider identifier
        **kwargs: Provider configuration

    Returns:
        Provider instance
    """
    return _registry.create(name, **kwargs)


def list_providers() -> list[str]:
    """List all registered providers.

    Returns:
        List of provider identifiers
    """
    return _registry.list_providers()


# Register built-in providers
# Import here to avoid circular imports
from giskit.providers.ogc_features import OGCFeaturesProvider

register_provider("ogc-features", OGCFeaturesProvider)
