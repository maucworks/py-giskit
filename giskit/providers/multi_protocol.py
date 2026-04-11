"""Multi-protocol provider supporting multiple data access protocols.

A single provider (e.g., PDOK) can offer services via different protocols:
- OGC API Features (vector data)
- WCS (raster/elevation data)
- WMTS (pre-rendered tiles)
- WFS (legacy vector data)

This provider automatically routes requests to the appropriate protocol handler
based on the service configuration.
"""

import logging
from pathlib import Path
from typing import Any, Union

import geopandas as gpd

from giskit.config.yaml_utils import load_yaml_safe
from giskit.core.raster import RasterResult
from giskit.core.recipe import Dataset, Location
from giskit.protocols.base import Protocol
from giskit.providers.base import Provider

logger = logging.getLogger(__name__)


class MultiProtocolProvider(Provider):
    """Provider supporting multiple protocols from unified config.

    Reads a unified provider config (e.g., pdok.yml) where each service
    specifies its protocol. Automatically creates and manages protocol
    handlers for each protocol type used.

    Example config:
        provider:
          name: pdok
          title: PDOK

        services:
          bgt:
            protocol: ogc-features
            url: https://api.pdok.nl/lv/bgt/ogc/v1_0/
            ...
          ahn:
            protocol: wcs
            url: https://service.pdok.nl/rws/ahn/wcs/v1_0
            ...
          luchtfoto:
            protocol: wmts
            url: https://service.pdok.nl/hwh/luchtfotorgb/wmts/v1_0
            ...
    """

    def __init__(self, name: str, config_file: Path | None = None, **kwargs: Any):
        """Initialize multi-protocol provider.

        Args:
            name: Provider identifier (e.g., "pdok")
            config_file: Path to unified provider config file
            **kwargs: Additional configuration
        """
        super().__init__(name, **kwargs)

        self.config_file = config_file
        self.services: dict[str, dict[str, Any]] = {}
        self.services_by_protocol: dict[str, dict[str, dict[str, Any]]] = {}

        # Load config
        if config_file and config_file.exists():
            self._load_config(config_file)

    def _load_config(self, config_file: Path) -> None:
        """Load unified provider config and organize services by protocol."""
        data = load_yaml_safe(config_file)

        if not data or "services" not in data:
            return

        provider_meta = data.get("provider", {})
        self.metadata = provider_meta

        # Organize services by protocol
        for service_id, service_config in data["services"].items():
            protocol = service_config.get("protocol", "ogc-features")

            # Store in main services dict
            self.services[service_id] = service_config

            # Group by protocol for efficient lookup
            if protocol not in self.services_by_protocol:
                self.services_by_protocol[protocol] = {}

            self.services_by_protocol[protocol][service_id] = service_config

    async def get_metadata(self) -> dict[str, Any]:
        """Get provider metadata.

        Returns:
            Provider metadata including supported protocols
        """
        # Map country codes to coverage names for backward compatibility
        country_code = self.metadata.get("country", "")
        coverage_map = {
            "NL": "Netherlands",
            "": "",
        }
        coverage = coverage_map.get(country_code, country_code)

        return {
            "name": self.metadata.get("title", self.name).split(" ")[
                0
            ],  # Extract "PDOK" from "PDOK - ..."
            "title": self.metadata.get("title", self.name),
            "description": self.metadata.get("description", ""),
            "homepage": self.metadata.get("homepage", ""),
            "country": country_code,
            "coverage": coverage,
            "license": self.metadata.get("license", ""),
            "protocols": list(self.services_by_protocol.keys()),
            "services": list(self.services.keys()),
            "service_count": len(self.services),
        }

    async def download_dataset(
        self,
        dataset: Dataset,
        location: Location,
        output_path: Path,
        output_crs: str = "EPSG:4326",
        **kwargs: Any,
    ) -> Union[gpd.GeoDataFrame, RasterResult]:
        """Download a dataset using the appropriate protocol.

        Args:
            dataset: Dataset specification from recipe
            location: Location specification
            output_path: Where to save downloaded data
            output_crs: Output coordinate reference system
            **kwargs: Additional options

        Returns:
            GeoDataFrame with downloaded vector data, or RasterResult for
            raster protocols (WMTS/WCS).

        Raises:
            ValueError: If service not found or protocol not supported
        """
        if not dataset.service:
            raise ValueError("Dataset must specify a service")

        if dataset.service not in self.services:
            raise ValueError(
                f"Service '{dataset.service}' not found in provider '{self.name}'. "
                f"Available: {', '.join(self.services.keys())}"
            )

        service_config = self.services[dataset.service]
        protocol_name = service_config.get("protocol", "ogc-features")

        # Delegate raster protocols to their specialized provider transparently.
        # WMTSProvider and WCSProvider have their own init logic (protocol instances,
        # layer key mapping) that would be duplicated if reimplemented here.
        if protocol_name in ("wmts", "wcs"):
            return await self._delegate_raster(
                protocol_name, dataset, location, output_path, output_crs, **kwargs
            )

        # Get or create protocol handler
        protocol = self.get_protocol(protocol_name)
        if protocol is None:
            protocol = self._create_protocol_handler(
                protocol_name, service_config, service_id=dataset.service
            )
            self.register_protocol(protocol_name, protocol)

        # Convert location to bbox using spatial helper
        from giskit.core.spatial import location_to_bbox

        bbox = await location_to_bbox(location, "EPSG:4326")

        # Get temporal filter from dataset (default to 'latest')
        temporal = dataset.temporal if dataset.temporal else "latest"

        # For WFS: translate user-facing layer names to WFS type names using the layers map.
        # e.g. "perceel" -> "cp:cadastralparcel" for brk-percelen-wfs
        layers_to_request = dataset.layers
        if protocol_name == "wfs":
            layer_map = service_config.get("layers", {})
            if layer_map:
                translated = []
                for name in dataset.layers or []:
                    if name in layer_map:
                        translated.append(layer_map[name])
                    else:
                        logger.warning(
                            "Layer '%s' not found in service '%s' layers map — skipping. "
                            "Available: %s",
                            name,
                            dataset.service,
                            list(layer_map.keys()),
                        )
                layers_to_request = translated if translated else None

        # Delegate to protocol handler based on protocol type
        async with protocol:
            if protocol_name in ("ogc-features", "wfs"):
                # Vector data protocols - use get_features
                gdf = await protocol.get_features(
                    bbox=bbox,  # type: ignore
                    layers=layers_to_request,
                    crs=output_crs,
                    temporal=temporal,
                    **kwargs,
                )
            elif protocol_name in ("gtfs", "csv"):
                # Data feed protocols - use fetch method
                point = (
                    tuple(location.value)
                    if location.type == "point" and isinstance(location.value, list)
                    else None
                )  # type: ignore
                gdf = await protocol.fetch(  # type: ignore
                    service_config=service_config,
                    bbox=tuple(bbox) if bbox else None,
                    point=point,
                    radius=location.radius if hasattr(location, "radius") else None,
                    crs=output_crs,
                    **kwargs,
                )
            else:
                # For other protocols (GTFS, CSV, etc.) raise clearly
                raise NotImplementedError(
                    f"Download for {protocol_name} protocol should use specialized provider classes "
                    f"(WCSProvider, WMTSProvider) rather than MultiProtocolProvider"
                )

        return gdf

    async def _delegate_raster(
        self,
        protocol_name: str,
        dataset: Dataset,
        location: Location,
        output_path: Path,
        output_crs: str,
        **kwargs: Any,
    ) -> Union[gpd.GeoDataFrame, RasterResult]:
        """Transparently delegate wmts/wcs downloads to the specialized provider.

        Builds a synthetic dataset whose service key matches the specialized
        provider's expected ``"service_name.layer_key"`` format, then hands off
        to WMTSProvider / WCSProvider so that all tiling, layer-key mapping,
        and RasterResult construction is handled in one place.

        Args:
            protocol_name: "wmts" or "wcs"
            dataset: Original dataset from the recipe
            location: Location specification
            output_path: Output path
            output_crs: Target CRS
            **kwargs: Extra options forwarded to the specialized provider

        Returns:
            RasterResult from the specialized provider
        """
        from giskit.providers.base import get_provider

        # The specialized provider is registered as "<name>-<protocol>", e.g. "pdok-wmts"
        specialized_name = f"{self.name}-{protocol_name}"

        service_config = self.services[dataset.service or ""]

        # WMTSProvider expects dataset.service == "service_name.layer_key"
        # The recipe supplies service="luchtfoto", layers=["actueel_8cm"]
        # → build "luchtfoto.actueel_8cm"
        if protocol_name == "wmts":
            layers = dataset.layers or []
            layer_keys = []
            available_layers = service_config.get("layers", {})
            for layer_key in layers:
                # If user gave a friendly key that maps to a WMTS layer name, use it directly
                if layer_key in available_layers or not available_layers:
                    layer_keys.append(layer_key)
                else:
                    logger.warning(
                        "WMTS layer key '%s' not found in service '%s'. Available: %s",
                        layer_key,
                        dataset.service,
                        list(available_layers.keys()),
                    )

            results = []
            for layer_key in layer_keys:
                synthetic_service = f"{dataset.service}.{layer_key}"
                synthetic_dataset = dataset.model_copy(
                    update={"service": synthetic_service, "layers": [layer_key]}
                )
                provider = get_provider(specialized_name)
                result = await provider.download_dataset(
                    dataset=synthetic_dataset,
                    location=location,
                    output_path=output_path,
                    output_crs=output_crs,
                    **kwargs,
                )
                results.append(result)

            # Return single result or last result (multi-layer WMTS not yet merged)
            if len(results) == 1:
                return results[0]
            if results:
                return results[-1]
            raise ValueError(f"No WMTS layers downloaded for service '{dataset.service}'")

        # WCSProvider expects dataset.service == "service_name.coverage_key"
        if protocol_name == "wcs":
            coverages = dataset.layers or list(service_config.get("coverages", {}).keys())
            if not coverages:
                raise ValueError(f"No coverage specified for WCS service '{dataset.service}'")

            coverage_key = coverages[0]
            synthetic_service = f"{dataset.service}.{coverage_key}"
            synthetic_dataset = dataset.model_copy(
                update={"service": synthetic_service, "layers": [coverage_key]}
            )
            provider = get_provider(specialized_name)
            return await provider.download_dataset(
                dataset=synthetic_dataset,
                location=location,
                output_path=output_path,
                output_crs=output_crs,
                **kwargs,
            )

        raise NotImplementedError(
            f"Raster delegation not implemented for protocol '{protocol_name}'"
        )

    def _create_protocol_handler(
        self, protocol_name: str, service_config: dict[str, Any], service_id: str | None = None
    ) -> Protocol:
        """Create appropriate protocol handler using the protocol registry.

        Args:
            protocol_name: Protocol identifier (ogc-features, wcs, wmts)
            service_config: Service configuration
            service_id: Service identifier for quirks lookup

        Returns:
            Protocol instance

        Raises:
            ValueError: If protocol not supported
        """
        from giskit.protocols.registry import create_protocol

        # Build config for protocol factory
        config = {
            "url": service_config.get("url", ""),
            "service_id": service_id,
            "provider_name": self.name,
        }

        # Add protocol-specific parameters
        if protocol_name == "ogc-features":
            # Handle quirks for OGC Features
            from giskit.protocols.quirks import get_service_quirks

            if service_id:
                quirks = get_service_quirks(self.name, protocol_name, service_id)
            else:
                # Fallback: try to extract from config
                fallback_id = service_config.get("title", "").split(" - ")[0].lower()
                if not fallback_id:
                    fallback_id = service_config.get("url", "").split("/")[-2]
                quirks = get_service_quirks(self.name, protocol_name, fallback_id)

            config["quirks"] = quirks

        elif protocol_name == "wmts":
            # WMTS needs layer and tile matrix set
            config["layer"] = service_config.get("layer", "")
            config["tile_matrix_set"] = service_config.get("tile_matrix_set", "EPSG:28992")
            config["tile_format"] = service_config.get("tile_format", "jpeg")

        elif protocol_name == "wcs":
            # WCS needs coverage ID and native CRS
            config["coverage_id"] = service_config.get("coverage_id", "")
            config["native_crs"] = service_config.get("native_crs", "EPSG:28992")
            config["native_resolution"] = service_config.get("native_resolution")

        # Use registry to create protocol instance
        return create_protocol(protocol_name, config)

    def get_supported_services(self) -> list[str]:
        """Get list of all supported services across all protocols.

        Returns:
            List of service identifiers
        """
        return list(self.services.keys())

    def get_supported_protocols(self) -> list[str]:
        """Get list of protocols used by this provider.

        Returns:
            List of protocol names
        """
        return list(self.services_by_protocol.keys())

    def get_services_by_protocol(self, protocol: str) -> list[str]:
        """Get services that use a specific protocol.

        Args:
            protocol: Protocol name (ogc-features, wcs, wmts)

        Returns:
            List of service identifiers
        """
        return list(self.services_by_protocol.get(protocol, {}).keys())

    def get_services_by_category(self, category: str) -> list[str]:
        """Get services in a specific category.

        Args:
            category: Category name (e.g., 'elevation', 'imagery')

        Returns:
            List of service identifiers
        """
        return [
            service_id
            for service_id, config in self.services.items()
            if config.get("category") == category
        ]

    def get_service_info(self, service_id: str) -> dict[str, Any]:
        """Get detailed information about a service.

        Args:
            service_id: Service identifier

        Returns:
            Service configuration dict

        Raises:
            ValueError: If service not found
        """
        if service_id not in self.services:
            raise ValueError(
                f"Service '{service_id}' not found. Available: {', '.join(self.services.keys())}"
            )

        return {"name": service_id, **self.services[service_id]}

    def list_categories(self) -> list[str]:
        """Get list of all service categories.

        Returns:
            Sorted list of unique category names
        """
        categories = {config.get("category", "other") for config in self.services.values()}
        return sorted(categories)
