"""YAML utilities for safe loading and saving configuration files.

Provides consistent YAML handling across the config module with
proper error handling and validation.
"""

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def load_yaml_safe(file_path: Path) -> dict[str, Any] | None:
    """Load YAML file safely with error handling.

    Args:
        file_path: Path to YAML file

    Returns:
        Parsed YAML data as dict, or None if file doesn't exist or is invalid

    Examples:
        >>> data = load_yaml_safe(Path("config.yml"))
        >>> if data:
        ...     print(data["provider"]["name"])
    """
    if not file_path.exists():
        logger.debug(f"YAML file not found: {file_path}")
        return None

    try:
        with open(file_path) as f:
            data = yaml.safe_load(f)
        return data
    except yaml.YAMLError as e:
        logger.error(f"Invalid YAML in {file_path}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error reading {file_path}: {e}")
        return None


def save_yaml_safe(
    data: dict[str, Any],
    file_path: Path,
    *,
    create_dirs: bool = True,
    sort_keys: bool = False,
) -> bool:
    """Save data to YAML file safely.

    Args:
        data: Data to serialize to YAML
        file_path: Output file path
        create_dirs: Create parent directories if they don't exist
        sort_keys: Sort dictionary keys alphabetically

    Returns:
        True if successful, False otherwise

    Examples:
        >>> config = {"provider": {"name": "pdok"}}
        >>> save_yaml_safe(config, Path("output.yml"))
        True
    """
    try:
        if create_dirs:
            file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, "w") as f:
            yaml.dump(
                data,
                f,
                default_flow_style=False,
                sort_keys=sort_keys,
                allow_unicode=True,
            )
        return True
    except Exception as e:
        logger.error(f"Error writing YAML to {file_path}: {e}")
        return False


__all__ = ["load_yaml_safe", "save_yaml_safe"]
