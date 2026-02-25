# Adding a New Protocol

This guide explains how to add a new protocol implementation to pygiskit using the `ProtocolRegistry` pattern.

## Overview

After the Phase 2 refactoring, protocols are registered dynamically in a central registry, making it easy to add new ones without modifying existing code.

**When to add a new protocol**:
- You need to support a new API standard (e.g., WMS, CSW, SOS)
- An existing standard has a significantly different variant
- You're adding support for a proprietary API format

## Prerequisites

- Understand the API/protocol specification
- Identify async HTTP client needs (`httpx` for most cases)
- Determine return data format (GeoDataFrame, image, etc.)
- Review similar existing protocols for patterns

## Step-by-Step Guide

### 1. Create Protocol Implementation

Create `giskit/protocols/your_protocol.py`:

```python
"""Your Protocol - Implementation of YourAPI specification.

This module implements the YourAPI protocol for accessing [data type].

Protocol Specification:
- Standard: YourAPI v1.0
- Spec URL: https://example.com/spec
- Supported operations: GetData, GetMetadata, etc.

Examples:
    >>> async with YourProtocol(base_url="https://api.example.com") as protocol:
    ...     data = await protocol.get_data(params)
"""

import logging
from typing import Any, Optional, Callable

import httpx
import geopandas as gpd

from giskit.protocols.base import Protocol


logger = logging.getLogger(__name__)


class YourProtocol(Protocol):
    """YourAPI protocol implementation.

    Supports:
    - Operation 1
    - Operation 2
    - etc.

    Attributes:
        base_url: API endpoint base URL
        param1: Protocol-specific parameter
        param2: Another parameter
    """

    def __init__(
        self,
        base_url: str,
        param1: str,
        param2: Optional[str] = None,
        **kwargs: Any,
    ):
        """Initialize protocol.

        Args:
            base_url: API endpoint URL
            param1: Required parameter
            param2: Optional parameter
            **kwargs: Additional configuration
        """
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.param1 = param1
        self.param2 = param2 or "default_value"
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "YourProtocol":
        """Async context manager entry."""
        self._client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *args) -> None:
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()

    async def get_data(
        self,
        bbox: tuple[float, float, float, float],
        crs: str = "EPSG:4326",
        progress_callback: Optional[Callable[[str, float], None]] = None,
        **kwargs: Any,
    ) -> gpd.GeoDataFrame:
        """Retrieve data from the API.

        Args:
            bbox: Bounding box (minx, miny, maxx, maxy)
            crs: Coordinate reference system
            progress_callback: Optional progress reporting function
            **kwargs: Additional query parameters

        Returns:
            GeoDataFrame with retrieved data

        Raises:
            YourProtocolError: If request fails
        """
        if not self._client:
            raise RuntimeError("Protocol not initialized. Use 'async with' context.")

        if progress_callback:
            progress_callback("Fetching data...", 0.0)

        # Build request URL
        url = f"{self.base_url}/data"
        params = {
            "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
            "crs": crs,
            "param1": self.param1,
            # ... other params
        }

        try:
            # Make API request (use centralized HTTP error handling from base)
            response = await self._client.get(url, params=params)
            response.raise_for_status()

            # Parse response
            data = response.json()

            if progress_callback:
                progress_callback("Processing response...", 0.5)

            # Convert to GeoDataFrame
            gdf = self._parse_response(data, crs)

            if progress_callback:
                progress_callback("Complete", 1.0)

            return gdf

        except httpx.HTTPError as e:
            # Use centralized error handling from Protocol base class
            raise YourProtocolError(f"Failed to fetch data: {e}") from e

    def _parse_response(self, data: dict, crs: str) -> gpd.GeoDataFrame:
        """Parse API response into GeoDataFrame.

        Args:
            data: JSON response data
            crs: Target CRS

        Returns:
            Parsed GeoDataFrame
        """
        # Implementation depends on response format
        # Common patterns:
        # - GeoJSON: gpd.GeoDataFrame.from_features(data["features"])
        # - Custom: Build GeoDataFrame from dict/list
        pass

    async def get_capabilities(self) -> dict[str, Any]:
        """Get API capabilities/metadata.

        Returns:
            Capabilities dict

        Raises:
            YourProtocolError: If request fails
        """
        if not self._client:
            raise RuntimeError("Protocol not initialized")

        url = f"{self.base_url}/capabilities"

        try:
            response = await self._client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise YourProtocolError(f"Failed to get capabilities: {e}") from e


class YourProtocolError(Exception):
    """Raised when YourProtocol operations fail."""

    pass
```

### 2. Register Protocol

Add registration at the end of `giskit/protocols/your_protocol.py`:

```python
from giskit.protocols.registry import get_protocol_registry

# Register protocol factory
registry = get_protocol_registry()
registry.register_protocol(
    "your-protocol",
    lambda **kwargs: YourProtocol(**kwargs),
)
```

### 3. Import in Protocols Module

Update `giskit/protocols/__init__.py`:

```python
from giskit.protocols.your_protocol import YourProtocol, YourProtocolError

__all__ = [
    # ... existing
    "YourProtocol",
    "YourProtocolError",
]
```

### 4. Add Unit Tests

Create `tests/unit/test_your_protocol.py`:

```python
"""Unit tests for YourProtocol."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from giskit.protocols.your_protocol import YourProtocol, YourProtocolError


class TestYourProtocolInit:
    """Test protocol initialization."""

    @pytest.mark.unit
    def test_initialization(self):
        """Test protocol initializes correctly."""
        protocol = YourProtocol(
            base_url="https://api.example.com",
            param1="value1",
        )

        assert protocol.base_url == "https://api.example.com"
        assert protocol.param1 == "value1"

    @pytest.mark.unit
    def test_base_url_trailing_slash_removed(self):
        """Test that trailing slash is removed from base URL."""
        protocol = YourProtocol(
            base_url="https://api.example.com/",
            param1="value1",
        )

        assert protocol.base_url == "https://api.example.com"


class TestYourProtocolGetData:
    """Test data retrieval."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_data_success(self):
        """Test successful data retrieval."""
        protocol = YourProtocol(
            base_url="https://api.example.com",
            param1="value1",
        )

        # Mock HTTP client
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "type": "FeatureCollection",
            "features": [],
        }

        async with protocol:
            protocol._client.get = AsyncMock(return_value=mock_response)

            result = await protocol.get_data(
                bbox=(0.0, 0.0, 1.0, 1.0),
                crs="EPSG:4326",
            )

            assert len(result) == 0  # Empty result in mock

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_data_error_handling(self):
        """Test error handling on failed request."""
        protocol = YourProtocol(
            base_url="https://api.example.com",
            param1="value1",
        )

        async with protocol:
            # Mock HTTP error
            import httpx

            protocol._client.get = AsyncMock(
                side_effect=httpx.HTTPError("Connection failed")
            )

            with pytest.raises(YourProtocolError, match="Failed to fetch data"):
                await protocol.get_data(bbox=(0.0, 0.0, 1.0, 1.0))
```

### 5. Add Integration Tests

Add tests to `tests/integration/test_protocol_registry.py`:

```python
@pytest.mark.integration
def test_your_protocol_registered(self):
    """Test that your protocol is registered."""
    registry = get_protocol_registry()
    protocols = registry.get_available_protocols()

    assert "your-protocol" in protocols

@pytest.mark.integration
def test_create_your_protocol(self):
    """Test creating your protocol via registry."""
    registry = get_protocol_registry()

    protocol = registry.create_protocol(
        "your-protocol",
        base_url="https://api.example.com",
        param1="value1",
    )

    assert isinstance(protocol, YourProtocol)
    assert protocol.base_url == "https://api.example.com"
```

## Protocol Patterns

### Async Context Manager Pattern

All protocols should support async context manager for resource cleanup:

```python
async def __aenter__(self) -> "YourProtocol":
    """Initialize HTTP client."""
    self._client = httpx.AsyncClient(timeout=30.0)
    return self

async def __aexit__(self, *args) -> None:
    """Close HTTP client."""
    if self._client:
        await self._client.aclose()
```

### Error Handling Pattern

Use centralized error handling from `Protocol` base class:

```python
try:
    response = await self._client.get(url)
    response.raise_for_status()
except httpx.HTTPError as e:
    raise YourProtocolError(f"Operation failed: {e}") from e
```

### Progress Callback Pattern

Support optional progress callbacks for UI integration:

```python
if progress_callback:
    progress_callback("Starting...", 0.0)

# ... do work ...

if progress_callback:
    progress_callback("Processing...", 0.5)

# ... more work ...

if progress_callback:
    progress_callback("Complete", 1.0)
```

### Pagination Pattern

For APIs with pagination (see `OGCFeaturesProtocol` for example):

```python
all_features = []
next_url = initial_url

while next_url:
    response = await self._client.get(next_url)
    data = response.json()

    all_features.extend(data["features"])

    # Get next page URL (format varies by API)
    next_url = data.get("links", {}).get("next")

return gpd.GeoDataFrame.from_features(all_features)
```

## Testing Your Protocol

### Run Unit Tests

```bash
poetry run pytest tests/unit/test_your_protocol.py -v
```

### Run Integration Tests

```bash
poetry run pytest tests/integration/test_protocol_registry.py::test_your_protocol_registered -v
```

### Test with Provider

Create a provider that uses your protocol (see [Adding Providers](adding_providers.md)), then test end-to-end with a recipe.

## Common Protocol Types

### Vector Data Protocols

Return `GeoDataFrame` directly:

```python
async def get_features(self, bbox, crs) -> gpd.GeoDataFrame:
    # Fetch GeoJSON/features
    # Parse to GeoDataFrame
    return gdf
```

### Raster/Image Protocols

Return `PIL.Image` or save to file:

```python
async def get_image(self, bbox, crs) -> Image.Image:
    # Fetch image bytes
    # Return PIL Image
    return Image.open(io.BytesIO(image_bytes))
```

### Coverage Protocols

Save GeoTIFF and return metadata:

```python
async def save_coverage_as_geotiff(
    self,
    bbox,
    output_path,
    resolution,
) -> Path:
    # Download coverage data
    # Save as GeoTIFF
    # Return path
    return output_path
```

## References

- **Protocol Base Class**: `giskit/protocols/base.py`
- **ProtocolRegistry**: `giskit/protocols/registry.py`
- **Example Protocols**: `wmts.py`, `wcs.py`, `ogc_features.py`, `wfs.py`
- **HTTP Client**: httpx documentation
- **GeoDataFrames**: geopandas documentation
