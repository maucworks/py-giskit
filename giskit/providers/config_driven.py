"""Config-driven provider base class.

Provides common functionality for providers that load their service
definitions from YAML config files. This eliminates code duplication
across OGCFeaturesProvider, WMTSProvider, WCSProvider, and MultiProtocolProvider.

All config-driven providers share these features:
- Load services from config/services/{name}.yml or config/providers/{name}/*.yml
- Provide catalog methods (get_service_info, list_categories, etc.)
- Handle both legacy (string URL) and modern (dict) service formats
"""

from typing import Any

from giskit.config import load_services
from giskit.providers.base import Provider


class ConfigDrivenProvider(Provider):
    """Base class for providers that load services from YAML config files.

    Subclasses must implement:
    - download_dataset(): Protocol-specific download logic
    - get_supported_protocols(): List of supported protocol names

    This class provides:
    - Service loading from config files
    - Catalog methods (get_service_info, list_categories, etc.)
    - Common validation and error handling
    """

    def __init__(self, name: str, **kwargs: Any):
        """Initialize config-driven provider.

        Args:
            name: Provider identifier (e.g., "pdok", "pdok-wmts")
                  Must have corresponding config file
            **kwargs: Additional configuration
                fallback_services: Optional fallback if config not found

        Raises:
            FileNotFoundError: If config file not found and no fallback provided
            ValueError: If config is invalid or no services found
        """
        super().__init__(name, **kwargs)

        # Load services from config
        fallback = kwargs.get("fallback_services", None)
        self.services = load_services(name, fallback=fallback)

        if not self.services:
            raise ValueError(
                f"No services found for provider '{name}'. "
                f"Check config/services/{name}.yml exists and is valid."
            )

    def get_supported_services(self) -> list[str]:
        """Get list of supported services.

        Returns:
            List of service names
        """
        return list(self.services.keys())

    def get_services_by_category(self, category: str) -> list[str]:
        """Get list of services in a specific category.

        Args:
            category: Category name (e.g., 'base_registers', 'imagery', 'topography')

        Returns:
            List of service names in this category
        """
        services = []
        for service_name, service_config in self.services.items():
            if isinstance(service_config, dict):
                if service_config.get("category") == category:
                    services.append(service_name)
        return services

    def get_service_info(self, service_id: str) -> dict[str, Any]:
        """Get detailed information about a specific service.

        Args:
            service_id: Service identifier

        Returns:
            Dictionary with service metadata

        Raises:
            ValueError: If service not found
        """
        if service_id not in self.services:
            raise ValueError(
                f"Service '{service_id}' not found. Available: {', '.join(self.services.keys())}"
            )

        service_config = self.services[service_id]
        if isinstance(service_config, str):
            # Old format - just URL
            return {
                "name": service_id,
                "url": service_config,
                "title": service_id.upper(),
                "category": "unknown",
                "description": "",
                "keywords": [],
            }
        else:
            # New format - full metadata
            return {"name": service_id, **service_config}

    def list_categories(self) -> list[str]:
        """Get list of all service categories.

        Returns:
            List of category names (sorted)
        """
        categories = set()
        for service_config in self.services.values():
            if isinstance(service_config, dict):
                category = service_config.get("category", "other")
                categories.add(category)
        return sorted(categories)

    async def get_metadata(self) -> dict[str, Any]:
        """Get provider metadata.

        Returns:
            Dictionary with provider information
        """
        # Count services by category
        categories: dict[str, int] = {}
        for service_config in self.services.values():
            if isinstance(service_config, dict):
                category = service_config.get("category", "other")
                categories[category] = categories.get(category, 0) + 1

        # Get protocol list from subclass
        protocols = self.get_supported_protocols()
        protocol_str = ", ".join(protocols) if protocols else "unknown"

        return {
            "name": self.name,
            "description": f"{protocol_str.upper()} provider: {self.name}",
            "total_services": len(self.services),
            "categories": categories,
            "services": list(self.services.keys()),
            "protocols": protocols,
        }


__all__ = ["ConfigDrivenProvider"]
