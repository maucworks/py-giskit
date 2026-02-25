# Adding a New Provider

This guide explains how to add a new data provider to pygiskit using the `ConfigDrivenProvider` pattern.

## Overview

After the Phase 2 refactoring, adding new providers is significantly easier:

**Before**: Hardcode services in Python, ~100-150 lines per provider
**After**: Create YAML config + minimal Python (~20-50 lines)

## Prerequisites

- Identify the protocol(s) your provider will use (WMTS, WCS, OGC Features, WFS)
- Gather service metadata (URLs, layer names, descriptions, keywords)
- Understand the provider's API structure and authentication (if any)

## Step-by-Step Guide

### 1. Create YAML Configuration

Create `giskit/config/services/your-provider.yml`:

```yaml
provider:
  name: your-provider
  title: Your Provider Name
  country: NL  # or other country code
  homepage: https://your-provider.example.com
  license: CC0-1.0  # or appropriate license
  defaults:
    protocol: wmts  # or wcs, ogc_features, wfs

services:
  service-name:
    url: https://api.example.com/service/endpoint
    title: Human-Readable Service Title
    category: imagery  # or elevation, vector, basemap, etc.
    description: |
      Multi-line description of what this service provides.
      Include data sources, update frequency, coverage, etc.
    keywords:
      - relevant
      - keywords
      - for
      - search
    # Protocol-specific configuration below
    # See examples for each protocol type
```

### 2. Protocol-Specific Configuration

#### For WMTS Providers (Raster Tiles)

```yaml
services:
  aerial-imagery:
    url: https://tiles.example.com/wmts/v1
    title: Aerial Imagery Service
    category: imagery
    description: High-resolution aerial photography
    keywords: [aerial, imagery, orthophoto]
    tile_format: jpeg  # or png
    tile_matrix_set: EPSG:28992  # or EPSG:3857, etc.
    resolutions: [3440.64, 1720.32, 860.16, ...]  # meters/pixel per zoom level
    layers:
      high_res: ActualLayerName_8cm
      standard: ActualLayerName_25cm
```

**Key Fields**:
- `layers`: Map of friendly names → actual WMS layer names
- `tile_format`: Image format (jpeg, png, webp)
- `tile_matrix_set`: Coordinate system for tiles

#### For WCS Providers (Coverage/Elevation)

```yaml
services:
  elevation:
    url: https://coverage.example.com/wcs/v2
    title: Elevation Data Service
    category: elevation
    description: Digital elevation model
    keywords: [elevation, dem, dtm, dsm]
    coverages:
      dtm: dtm_50cm  # Digital Terrain Model
      dsm: dsm_50cm  # Digital Surface Model
    format: image/tiff
    native_resolution: 0.5  # meters
    native_crs: EPSG:28992
    bbox: [10000, 306250, 280000, 618750]  # Service extent [minx, miny, maxx, maxy]
    vertical_datum: NAP  # or other vertical datum
    unit: meters
```

**Key Fields**:
- `coverages`: Map of friendly names → actual coverage IDs
- `native_resolution`: Native data resolution in meters
- `native_crs`: Native coordinate reference system
- `bbox`: Bounding box of service extent

#### For OGC Features Providers (Vector Data)

```yaml
services:
  buildings:
    url: https://api.example.com/collections
    title: Building Footprints
    category: vector
    description: Vector building footprints
    keywords: [buildings, footprints, cadastre]
    collections:
      - buildings_2d
      - buildings_3d
    crs: EPSG:28992
    formats: [json, geojson]
```

**Key Fields**:
- `collections`: List of collection IDs available
- `crs`: Supported coordinate reference systems
- `formats`: Response formats supported

### 3. Create Provider Class

Create `giskit/providers/your_provider.py`:

```python
"""Your Provider - Description of what it provides.

This provider supports [protocol name] for downloading [data type]:
- Service 1
- Service 2
- etc.

Examples:
    >>> provider = YourProvider("your-provider")
    >>> services = provider.get_supported_services()
"""

from pathlib import Path
from typing import Any

import geopandas as gpd

from giskit.core.recipe import Dataset, Location
from giskit.protocols.wmts import WMTSProtocol  # or WCS, OGCFeatures, etc.
from giskit.providers.base import register_provider
from giskit.providers.config_driven import ConfigDrivenProvider


class YourProvider(ConfigDrivenProvider):
    """Your provider for [data type].

    Loads services from YAML config files, making it work with any provider
    that offers [protocol] endpoints.

    Supports:
    - Protocol X
    - Data type Y
    - Use case Z

    Does NOT support:
    - Other data types (use OtherProvider instead)
    """

    def __init__(self, name: str, **kwargs: Any):
        """Initialize provider.

        Args:
            name: Provider identifier (e.g., "your-provider")
                  Must have corresponding config/services/{name}.yml
            **kwargs: Additional configuration

        Raises:
            FileNotFoundError: If config file not found
            ValueError: If config is invalid
        """
        # Call parent to load services from config
        super().__init__(name, **kwargs)

        # Register protocols for each service
        self.protocols: dict[str, ProtocolClass] = {}

        for service_name, service_config in self.services.items():
            if isinstance(service_config, dict):
                # Extract configuration
                url = service_config.get("url", "")

                # Create protocol instance(s)
                # Specific logic depends on your protocol type
                # See existing providers for examples

    async def download_dataset(
        self,
        dataset: Dataset,
        location: Location,
        output_path: Path,
        output_crs: str = "EPSG:28992",
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
        # 1. Parse dataset.service to get service name
        # 2. Get protocol instance from self.protocols
        # 3. Convert location to bbox/geometry
        # 4. Use protocol to download data
        # 5. Save to output_path if needed
        # 6. Return GeoDataFrame

        pass  # Implement based on your protocol

    def get_supported_protocols(self) -> list[str]:
        """Get list of supported protocols.

        Returns:
            List of protocol names
        """
        return ["your-protocol"]  # e.g., ["wmts"], ["wcs"], etc.


# Register provider globally
register_provider("your-provider", YourProvider)
```

### 4. Implementation Examples

#### WMTS Provider Pattern

See `giskit/providers/wmts.py` for complete example.

Key points:
- Create one protocol instance per layer
- Store in `self.protocols` dict with key `"service.layer"`
- In `download_dataset()`:
  - Parse `dataset.service` as `"service.layer"`
  - Get protocol from `self.protocols[key]`
  - Download image using `protocol.get_coverage()`
  - Save image to file

#### WCS Provider Pattern

See `giskit/providers/wcs.py` for complete example.

Key points:
- Create one protocol instance per coverage
- Store in `self.protocols` dict with key `"service.coverage"`
- In `download_dataset()`:
  - Parse `dataset.service` as `"service.coverage"`
  - Get protocol from `self.protocols[key]`
  - Download GeoTIFF using `protocol.save_coverage_as_geotiff()`
  - Return metadata GeoDataFrame

#### OGC Features Provider Pattern

See `giskit/providers/ogc_features.py` for complete example.

Key points:
- Create one protocol instance per service URL
- Collections are dynamically discovered
- In `download_dataset()`:
  - Get protocol for service
  - Query features by bbox and collection
  - Return GeoDataFrame directly

### 5. Add Unit Tests

Create `tests/unit/test_your_provider.py`:

```python
"""Unit tests for YourProvider."""

import pytest
from unittest.mock import AsyncMock, patch

from giskit.providers.your_provider import YourProvider
from giskit.providers.config_driven import ConfigDrivenProvider


class TestYourProviderConfiguration:
    """Test provider configuration."""

    @pytest.mark.unit
    def test_inherits_from_config_driven(self):
        """Test that provider inherits from ConfigDrivenProvider."""
        provider = YourProvider("your-provider")
        assert isinstance(provider, ConfigDrivenProvider)

    @pytest.mark.unit
    def test_loads_services_from_yaml(self):
        """Test that provider loads services from YAML config."""
        provider = YourProvider("your-provider")

        assert len(provider.services) > 0
        assert "service-name" in provider.services

    @pytest.mark.unit
    def test_protocols_registered(self):
        """Test that protocols are registered."""
        provider = YourProvider("your-provider")

        # Check protocols dict is populated
        assert len(provider.protocols) > 0


class TestYourProviderDownload:
    """Test download functionality."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_download_dataset_mock(self, tmp_path):
        """Test downloading dataset with mocked protocol."""
        # Add test implementation
        pass
```

### 6. Add Integration Tests

Create `tests/integration/test_your_provider.py`:

```python
"""Integration tests for YourProvider."""

import pytest

from giskit.providers.your_provider import YourProvider
from giskit.providers.base import get_provider


class TestYourProviderIntegration:
    """Test provider integration."""

    @pytest.mark.integration
    def test_provider_registered(self):
        """Test that provider is registered globally."""
        provider = get_provider("your-provider")
        assert isinstance(provider, YourProvider)

    @pytest.mark.integration
    def test_yaml_config_loaded(self):
        """Test that YAML config is loaded correctly."""
        provider = YourProvider("your-provider")

        # Test service metadata from YAML
        service = provider.services["service-name"]
        assert service["title"] is not None
        assert "url" in service
```

### 7. Register Provider

The provider is automatically registered when the module is imported thanks to:

```python
register_provider("your-provider", YourProvider)
```

at the end of your provider file.

To make it available, import it in `giskit/providers/__init__.py`:

```python
from giskit.providers.your_provider import YourProvider

__all__ = [
    # ... existing providers
    "YourProvider",
]
```

### 8. Update Documentation

Add your provider to `README.md`:

```markdown
## Supported Providers

- **PDOK** (Publieke Dienstverlening Op de Kaart)
  - OGC Features, WMTS, WCS
  - BAG, BGT, AHN, aerial imagery

- **Your Provider**
  - Protocol type
  - Data types provided
```

Update `docs/architecture.md` provider table:

```markdown
| Provider | Protocol(s) | Data Type | Config File |
|----------|-------------|-----------|-------------|
| ... | ... | ... | ... |
| `YourProvider` | WMTS | Raster tiles | `your-provider.yml` |
```

## Testing Your Provider

### Run Unit Tests

```bash
poetry run pytest tests/unit/test_your_provider.py -v
```

### Run Integration Tests

```bash
poetry run pytest tests/integration/test_your_provider.py -v
```

### Test with Recipe

Create a test recipe `test-recipes/your-provider.json`:

```json
{
  "location": {
    "type": "bbox",
    "value": [120000, 487000, 120100, 487100]
  },
  "datasets": [
    {
      "provider": "your-provider",
      "service": "service-name.layer",
      "layers": null
    }
  ],
  "output": {
    "path": "output/test-your-provider",
    "format": "gpkg"
  }
}
```

Test it:

```bash
poetry run giskit download test-recipes/your-provider.json
```

## Common Patterns

### Multiple Layer/Coverage Registration

For providers with many layers/coverages:

```python
for service_name, service_config in self.services.items():
    if isinstance(service_config, dict):
        url = service_config.get("url", "")
        layers = service_config.get("layers", {})

        for layer_key, layer_name in layers.items():
            protocol_key = f"{service_name}.{layer_key}"
            self.protocols[protocol_key] = ProtocolClass(
                base_url=url,
                layer=layer_name,
                # ... other config
            )
```

### Service Format Validation

```python
if not dataset.service:
    raise ValueError("Dataset.service is required")

if "." not in dataset.service:
    raise ValueError(
        f"Service must be 'service.layer' format, got: {dataset.service}"
    )

service_name, layer_name = dataset.service.split(".", 1)

if dataset.service not in self.protocols:
    available = list(self.protocols.keys())
    raise ValueError(
        f"Service '{dataset.service}' not found. "
        f"Available: {', '.join(available)}"
    )
```

### Progress Callbacks

```python
progress_callback = kwargs.get("progress_callback")

if progress_callback:
    progress_callback("Downloading data...", 0.0)

# ... do work ...

if progress_callback:
    progress_callback("Processing...", 0.5)

# ... more work ...

if progress_callback:
    progress_callback("Complete", 1.0)
```

## Troubleshooting

### Config File Not Found

```
FileNotFoundError: Config file not found: config/services/your-provider.yml
```

**Solution**: Ensure YAML file exists in `giskit/config/services/` directory.

### Protocol Not Registered

```
ValueError: Unknown protocol: your-protocol
```

**Solution**: Make sure protocol is registered with `ProtocolRegistry.register_protocol()`.

### Import Errors

```
ImportError: cannot import name 'YourProvider' from 'giskit.providers'
```

**Solution**: Add your provider to `giskit/providers/__init__.py`.

## Next Steps

- See [Adding Protocols](adding_protocols.md) if you need a new protocol type
- See [Architecture](architecture.md) for overall system design
- See `giskit/providers/wmts.py`, `wcs.py`, `ogc_features.py` for complete examples

## References

- **ConfigDrivenProvider**: `giskit/providers/config_driven.py`
- **Example YAML configs**: `giskit/config/services/`
- **Existing providers**: `giskit/providers/*.py`
- **Test examples**: `tests/unit/`, `tests/integration/`
