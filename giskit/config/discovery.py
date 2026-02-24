"""Provider auto-discovery from config directory.

Discovers providers from two formats:
1. Unified format: config/providers/{name}.yml (contains all services with protocol field)
2. Legacy format: config/providers/{name}/ogc-features.yml, wcs.yml, etc.
"""

from pathlib import Path
from typing import Any

from giskit.config.yaml_utils import load_yaml_safe


def discover_providers(config_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    """Discover all providers from config directory.

    Supports two formats:

    1. Unified multi-protocol (NEW):
       config/providers/pdok.yml
       → Registers as single "pdok" provider supporting multiple protocols

    2. Split per-protocol (LEGACY):
       config/providers/pdok/ogc-features.yml → "pdok"
       config/providers/pdok/wcs.yml → "pdok-wcs"
       config/providers/pdok/wmts.yml → "pdok-wmts"

    Args:
        config_dir: Base config directory (defaults to giskit/config)

    Returns:
        Dict mapping provider names to their config metadata:
        {
            "pdok": {
                "format": "unified",  # or "split"
                "config_file": Path("providers/pdok.yml"),
                "protocols": ["ogc-features", "wcs", "wmts"],
                "metadata": {...}
            }
        }
    """
    if config_dir is None:
        config_dir = Path(__file__).parent

    providers_dir = config_dir / "providers"
    if not providers_dir.exists():
        return {}

    discovered = {}

    # First: Check for unified format (*.yml files directly in providers/)
    for config_file in providers_dir.glob("*.yml"):
        if config_file.name.startswith("."):
            continue

        provider_name = config_file.stem  # e.g., "pdok" from "pdok.yml"

        config_data = load_yaml_safe(config_file)

        if not config_data or "provider" not in config_data or "services" not in config_data:
            continue  # Not a valid provider config

        # Detect protocols used in services
        protocols = set()
        for service_config in config_data["services"].values():
            if "protocol" in service_config:
                protocols.add(service_config["protocol"])

        discovered[provider_name] = {
            "format": "unified",
            "config_file": config_file,
            "protocols": sorted(protocols),
            "metadata": config_data.get("provider", {}),
            "base_name": provider_name,
        }

    # Second: Check for legacy split format (directories with protocol files)
    for provider_path in providers_dir.iterdir():
        if not provider_path.is_dir() or provider_path.name.startswith("."):
            continue

        provider_name = provider_path.name

        # Skip if already discovered as unified
        if provider_name in discovered:
            continue

        # Load provider metadata if exists
        metadata_file = provider_path / "provider.yml"
        metadata = {}
        if metadata_file.exists():
            metadata = load_yaml_safe(metadata_file) or {}

        # Check for protocol config files
        protocol_files = {
            "ogc-features": "ogc-features.yml",
            "wcs": "wcs.yml",
            "wmts": "wmts.yml",
            "wfs": "wfs.yml",
        }

        for protocol, filename in protocol_files.items():
            config_file = provider_path / filename
            if config_file.exists():
                # Determine provider registration name
                if protocol == "ogc-features":
                    # Main protocol uses provider name directly
                    reg_name = provider_name
                else:
                    # Other protocols use {provider}-{protocol} format
                    reg_name = f"{provider_name}-{protocol}"

                discovered[reg_name] = {
                    "format": "split",
                    "protocol": protocol,
                    "config_dir": provider_path,
                    "config_file": config_file,
                    "metadata": metadata,
                    "base_name": provider_name,
                }

    return discovered


def get_provider_config(
    provider_name: str, config_dir: Path | None = None
) -> dict[str, Any] | None:
    """Get config for a specific provider.

    Args:
        provider_name: Provider name (e.g., "pdok", "pdok-wcs")
        config_dir: Base config directory

    Returns:
        Provider config dict or None if not found
    """
    providers = discover_providers(config_dir)
    return providers.get(provider_name)


def list_providers(config_dir: Path | None = None) -> list[str]:
    """List all discovered provider names.

    Args:
        config_dir: Base config directory

    Returns:
        List of provider names
    """
    return list(discover_providers(config_dir).keys())
