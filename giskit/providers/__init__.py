"""Provider registry and imports.

Importing this module ensures all providers are registered.
"""

# Import all provider modules to ensure they're registered
from giskit.providers import gtfs, ogc_features, wcs, wmts  # noqa: F401

__all__ = []
