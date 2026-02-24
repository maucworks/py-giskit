"""Configuration loader for services and quirks.

This module provides utilities to load service and quirk definitions
from YAML config files, with fallback to hardcoded defaults.

Features:
- Load services from YAML files
- Load quirks from YAML files
- Validation and error handling
- Caching for performance
- Support for user config directories

Usage:
    from giskit.config import load_services, load_quirks

    # Load PDOK services
    services = load_services("pdok")

    # Load from custom file
    services = load_services("custom", config_path="/path/to/custom.yml")

    # Load quirks
    quirks = load_quirks()
"""

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError

from giskit.config.yaml_utils import load_yaml_safe, save_yaml_safe

# Config file locations
DEFAULT_CONFIG_DIR = Path(__file__).parent.parent / "config"
USER_CONFIG_DIR = Path.home() / ".giskit" / "config"


class ServiceDefinition(BaseModel):
    """Definition of a single service."""

    model_config = {"extra": "allow"}  # Allow extra fields for protocol-specific config

    url: str = Field(..., description="Service base URL")
    title: str = Field(..., description="Human-readable title")
    category: str = Field(..., description="Service category")
    description: str = Field(default="", description="Detailed description")
    keywords: list[str] = Field(default_factory=list, description="Search keywords")

    # Optional metadata
    quirks: list[str] = Field(default_factory=list, description="Quirk IDs to apply")
    timeout: Optional[float] = Field(None, description="Custom timeout in seconds")
    format: Optional[str] = Field(None, description="Data format (e.g., cityjson)")
    special: Optional[str] = Field(None, description="Special flags")

    # Protocol-specific fields (WMTS, WCS, WMS)
    layers: Optional[dict[str, str]] = Field(None, description="Layer definitions (WMTS)")
    tile_matrix_set: Optional[str] = Field(None, description="Tile matrix set (WMTS)")
    tile_format: Optional[str] = Field(None, description="Tile format (WMTS)")
    resolutions: Optional[list[float]] = Field(None, description="Available resolutions")

    # Monitoring metadata
    collections: Optional[int] = Field(None, description="Number of collections")
    last_checked: Optional[str] = Field(None, description="Last health check date")
    status: Optional[str] = Field(None, description="Health status")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format (compatible with legacy code)."""
        return self.model_dump(exclude_none=True)


class ProviderConfig(BaseModel):
    """Provider-level configuration."""

    name: str = Field(..., description="Provider identifier")
    title: str = Field(..., description="Provider display name")
    country: Optional[str] = Field(None, description="Country code (ISO 3166)")
    homepage: Optional[str] = Field(None, description="Provider homepage URL")
    license: Optional[str] = Field(None, description="Data license")

    # Defaults applied to all services
    defaults: dict[str, Any] = Field(default_factory=dict, description="Default settings")


class ServicesConfig(BaseModel):
    """Complete services configuration file."""

    provider: ProviderConfig = Field(..., description="Provider metadata")
    services: dict[str, ServiceDefinition] = Field(..., description="Service definitions")

    def get_services_dict(self) -> dict[str, dict[str, Any]]:
        """Get services as dict (compatible with legacy PDOK_SERVICES)."""
        result = {}

        for service_id, service_def in self.services.items():
            # Start with service definition
            service_dict = service_def.to_dict()

            # Apply provider defaults
            for key, value in self.provider.defaults.items():
                if key not in service_dict:
                    service_dict[key] = value

            result[service_id] = service_dict

        return result


class QuirkDefinition(BaseModel):
    """Definition of a single quirk."""

    name: str = Field(..., description="Quirk name")
    description: str = Field(default="", description="Why this quirk is needed")

    # URL quirks
    requires_trailing_slash: bool = Field(False)

    # Parameter quirks
    require_format_param: bool = Field(False)
    format_param_name: str = Field("f")
    format_param_value: str = Field("json")

    # Pagination quirks
    max_features_limit: Optional[int] = Field(None)
    pagination_broken: bool = Field(False)
    max_concurrent_cells: int = Field(5, description="Max concurrent grid cell downloads")

    # Timeout quirks
    custom_timeout: Optional[float] = Field(None)

    # CRS quirks
    force_crs_in_query: bool = Field(False)
    bbox_crs: Optional[str] = Field(
        None, description="CRS for bbox parameter (e.g., 'EPSG:28992' for BAG3D)"
    )
    omit_bbox_crs_param: bool = Field(
        False, description="Do not include bbox-crs parameter in requests"
    )

    # Response quirks
    empty_collections_return_404: bool = Field(False)

    # CityJSON format quirks
    format_is_cityjson: bool = Field(False)
    cityjson_version: Optional[str] = Field(None)
    has_per_page_transform: bool = Field(False)
    transform_applies_to_vertices: bool = Field(False)
    vertices_are_integers: bool = Field(False)
    has_lod_hierarchy: bool = Field(False)
    geometry_in_city_objects: bool = Field(False)

    # Metadata
    issue_url: Optional[str] = Field(None)
    workaround_date: Optional[str] = Field(None)
    references: list[str] = Field(default_factory=list)

    def to_protocol_quirks(self):
        """Convert to ProtocolQuirks instance."""
        from giskit.protocols.quirks import ProtocolQuirks

        return ProtocolQuirks(
            requires_trailing_slash=self.requires_trailing_slash,
            require_format_param=self.require_format_param,
            format_param_name=self.format_param_name,
            format_param_value=self.format_param_value,
            max_features_limit=self.max_features_limit,
            pagination_broken=self.pagination_broken,
            max_concurrent_cells=self.max_concurrent_cells,
            custom_timeout=self.custom_timeout,
            force_crs_in_query=self.force_crs_in_query,
            bbox_crs=self.bbox_crs,
            omit_bbox_crs_param=self.omit_bbox_crs_param,
            empty_collections_return_404=self.empty_collections_return_404,
            format_is_cityjson=self.format_is_cityjson,
            cityjson_version=self.cityjson_version,
            has_per_page_transform=self.has_per_page_transform,
            transform_applies_to_vertices=self.transform_applies_to_vertices,
            vertices_are_integers=self.vertices_are_integers,
            has_lod_hierarchy=self.has_lod_hierarchy,
            geometry_in_city_objects=self.geometry_in_city_objects,
            description=self.description,
            issue_url=self.issue_url,
            workaround_date=self.workaround_date,
        )


class QuirksConfig(BaseModel):
    """Complete quirks configuration file."""

    protocols: dict[str, QuirkDefinition] = Field(default_factory=dict)
    formats: dict[str, QuirkDefinition] = Field(default_factory=dict)
    providers: dict[str, QuirkDefinition] = Field(default_factory=dict)
    services: dict[str, dict[str, QuirkDefinition]] = Field(default_factory=dict)


def load_services(
    provider: str,
    config_path: Optional[Path] = None,
    config_dir: Optional[Path] = None,
    fallback: Optional[dict] = None,
) -> dict[str, dict[str, Any]]:
    """Load service definitions from config file.

    Args:
        provider: Provider name (e.g., "pdok")
        config_path: Explicit path to config file (overrides config_dir)
        config_dir: Directory containing config files (default: giskit/config)
        fallback: Fallback dict if config file not found

    Returns:
        Dictionary of services (compatible with PDOK_SERVICES format)

    Raises:
        FileNotFoundError: If config file not found and no fallback provided
        ValidationError: If config file is invalid

    Examples:
        >>> # Load from default location
        >>> services = load_services("pdok")

        >>> # Load from custom file
        >>> services = load_services("custom", config_path=Path("my-services.yml"))

        >>> # With fallback
        >>> services = load_services("pdok", fallback=LEGACY_SERVICES)
    """
    # Determine config file path
    if config_path:
        file_path = config_path
    else:
        if config_dir is None:
            config_dir = DEFAULT_CONFIG_DIR

        # Try new providers structure first: config/providers/{name}/ogc-features.yml
        new_path = config_dir / "providers" / provider / "ogc-features.yml"
        if new_path.exists():
            file_path = new_path
        else:
            # Fall back to legacy structure: config/services/{name}.yml
            file_path = config_dir / "services" / f"{provider}.yml"

    # Try to load from file
    if file_path.exists():
        data = load_yaml_safe(file_path)

        if data is None:
            # YAML loading failed
            if fallback is not None:
                print(f"⚠️  Failed to load YAML from {file_path}, using fallback...")
                return fallback
            raise ValueError(f"Failed to load YAML from {file_path}")

        try:
            # Validate and parse
            config = ServicesConfig(**data)
            return config.get_services_dict()

        except ValidationError as e:
            print(f"⚠️  Config validation error in {file_path}:")
            print(f"   {e}")
            if fallback is not None:
                print("   Using fallback...")
                return fallback
            raise

    # File not found
    else:
        if fallback is not None:
            return fallback
        raise FileNotFoundError(
            f"Config file not found: {file_path}\n" f"Create it or provide fallback parameter"
        )


def load_quirks(
    config_dir: Optional[Path] = None,
    fallback: Optional[dict] = None,
) -> dict[str, dict[str, Any]]:
    """Load quirk definitions from config files.

    Args:
        config_dir: Directory containing quirk config files
        fallback: Fallback dict if config files not found

    Returns:
        Dictionary of quirks (compatible with KNOWN_QUIRKS format)

    Examples:
        >>> quirks = load_quirks()
        >>> pdok_quirks = quirks["pdok"]["ogc-features"]
    """
    if config_dir is None:
        config_dir = DEFAULT_CONFIG_DIR / "quirks"

    all_quirks = {}

    # Load each quirks file
    for quirk_type in ["protocols", "formats", "providers", "services"]:
        file_path = config_dir / f"{quirk_type}.yml"

        if file_path.exists():
            data = load_yaml_safe(file_path)

            if data is None:
                print(f"⚠️  Failed to load YAML from {file_path}")
                if fallback:
                    return fallback
                continue

            try:
                # Handle services differently (nested structure)
                if quirk_type == "services":
                    # data is like: {"services": {"bag3d": {"ogc-features": {...}}}}
                    services_dict = data.get("services", {})
                    for service_id, protocols_dict in services_dict.items():
                        if service_id not in all_quirks:
                            all_quirks[service_id] = {}
                        for protocol_id, quirk_data in protocols_dict.items():
                            # Convert quirk_data to ProtocolQuirks
                            quirk_def = QuirkDefinition(**quirk_data)
                            all_quirks[service_id][protocol_id] = quirk_def.to_protocol_quirks()
                else:
                    # data is like: {"formats": {"cityjson-format": {...}}}
                    # We want to validate it and extract the quirks
                    config = QuirksConfig(**data)

                    # Convert to ProtocolQuirks instances
                    quirks_dict = getattr(config, quirk_type)
                    for quirk_id, quirk_def in quirks_dict.items():
                        # Extract provider/format name and protocol from quirk_id
                        # quirk_id is like "cityjson-format" or "pdok-ogc-features"
                        # We need to split intelligently:
                        # - For formats: "cityjson-format" -> provider="cityjson", protocol="format"
                        # - For providers: "pdok-ogc-features" -> provider="pdok", protocol="ogc-features"
                        parts = quirk_id.split("-", 1)  # Split on FIRST dash only
                        if len(parts) == 2:
                            provider_id, protocol_id = parts
                        else:
                            provider_id = quirk_id
                            protocol_id = "default"

                        # Organize by provider/format
                        if provider_id not in all_quirks:
                            all_quirks[provider_id] = {}
                        all_quirks[provider_id][protocol_id] = quirk_def.to_protocol_quirks()

            except Exception as e:
                print(f"⚠️  Error parsing quirks from {file_path}: {e}")
                if fallback:
                    return fallback

    # Return fallback if no quirks loaded
    if not all_quirks and fallback:
        return fallback

    return all_quirks


def save_services(
    services: dict[str, dict[str, Any]],
    provider_name: str,
    provider_title: str,
    output_path: Optional[Path] = None,
    **provider_metadata,
) -> Path:
    """Export services dict to YAML config file.

    Args:
        services: Services dictionary (PDOK_SERVICES format)
        provider_name: Provider identifier (e.g., "pdok")
        provider_title: Provider display name
        output_path: Output file path (default: config/services/{provider_name}.yml)
        **provider_metadata: Additional provider metadata (country, homepage, etc.)

    Returns:
        Path to written file

    Example:
        >>> save_services(
        ...     PDOK_SERVICES,
        ...     "pdok",
        ...     "PDOK - Publieke Dienstverlening Op de Kaart",
        ...     country="NL",
        ...     homepage="https://www.pdok.nl"
        ... )
    """
    if output_path is None:
        output_path = DEFAULT_CONFIG_DIR / "services" / f"{provider_name}.yml"

    # Convert services to ServiceDefinition instances
    service_defs = {}
    for service_id, service_data in services.items():
        service_defs[service_id] = ServiceDefinition(**service_data)

    # Create config structure
    config = ServicesConfig(
        provider=ProviderConfig(name=provider_name, title=provider_title, **provider_metadata),
        services=service_defs,
    )

    # Convert to dict and write YAML
    output_data = config.model_dump(exclude_none=True, exclude_defaults=False)

    if not save_yaml_safe(output_data, output_path, sort_keys=False):
        raise IOError(f"Failed to write YAML to {output_path}")

    return output_path


def save_quirks(
    quirks_dict: dict[str, dict[str, Any]],
    quirk_type: str,
    output_path: Optional[Path] = None,
) -> Path:
    """Export quirks dict to YAML config file.

    Args:
        quirks_dict: Quirks dictionary from KNOWN_QUIRKS
            Format: {"provider_id": {"protocol_id": ProtocolQuirks(...)}}
        quirk_type: Type of quirks ("formats", "providers", "protocols", "services")
        output_path: Output file path (default: config/quirks/{quirk_type}.yml)

    Returns:
        Path to written file

    Example:
        >>> from giskit.protocols.quirks import KNOWN_QUIRKS
        >>> # Export format quirks
        >>> save_quirks(
        ...     {"cityjson": KNOWN_QUIRKS["cityjson"]},
        ...     "formats"
        ... )
    """
    if output_path is None:
        output_path = DEFAULT_CONFIG_DIR / "quirks" / f"{quirk_type}.yml"

    # Flatten nested structure and convert to QuirkDefinition
    # Input:  {"cityjson": {"format": ProtocolQuirks(...)}}
    # Output: {"cityjson-format": QuirkDefinition(...)}
    quirk_defs = {}

    for category_id, protocols in quirks_dict.items():
        for protocol_id, quirk_obj in protocols.items():
            # Create unique ID for this quirk
            quirk_id = f"{category_id}-{protocol_id}"

            # Convert to dict if it has model_dump method (Pydantic model)
            if hasattr(quirk_obj, "model_dump"):
                quirk_data = quirk_obj.model_dump(exclude_none=True, exclude_defaults=True)
            elif isinstance(quirk_obj, dict):
                quirk_data = quirk_obj.copy()
            else:
                raise TypeError(f"Unknown quirk type: {type(quirk_obj)}")

            # Add name field
            quirk_data["name"] = quirk_id

            quirk_defs[quirk_id] = QuirkDefinition(**quirk_data)

    # Create config structure with the flattened quirks
    config = QuirksConfig(**{quirk_type: quirk_defs})

    # Convert to dict and write YAML
    output_data = config.model_dump(exclude_none=True, exclude_defaults=True)

    if not save_yaml_safe(output_data, output_path, sort_keys=False):
        raise IOError(f"Failed to write YAML to {output_path}")

    return output_path


__all__ = [
    "load_services",
    "load_quirks",
    "save_services",
    "save_quirks",
    "ServiceDefinition",
    "ServicesConfig",
    "QuirkDefinition",
    "QuirksConfig",
]
