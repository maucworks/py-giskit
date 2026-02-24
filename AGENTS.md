# AGENTS.md - AI Coding Agent Guidelines for pygiskit

This document provides guidelines for AI coding agents working in the pygiskit codebase.

## Project Overview

**pygiskit** is a recipe-driven spatial data downloader for Dutch geo-data. It downloads data from PDOK, BAG3D, Klimaateffectatlas, and other Dutch government spatial data sources using JSON "recipes".

- **Language:** Python 3.10-3.12
- **Package Manager:** Poetry
- **Main Module:** `giskit/`
- **CLI Entry Point:** `giskit` command (defined in pyproject.toml)

## Build & Development Commands

```bash
# Install dependencies
poetry install

# Install with optional IFC export support
poetry install --extras ifc

# Activate virtual environment
poetry shell

# Install pre-commit hooks (REQUIRED before committing)
pre-commit install

# Run CLI tool
poetry run giskit --help
```

## Testing Commands

```bash
# Run all tests
poetry run pytest -v

# Run unit tests only (fast, no external API calls)
poetry run pytest tests/unit/ -v

# Run integration tests (slow, require real API calls)
poetry run pytest tests/integration/ -v

# Run a single test file
poetry run pytest tests/unit/test_recipe.py -v

# Run a single test class
poetry run pytest tests/unit/test_recipe.py::TestLocation -v

# Run a single test function
poetry run pytest tests/unit/test_recipe.py::TestLocation::test_address_location_valid -v

# Run tests matching a pattern
poetry run pytest -k "test_bbox" -v

# Run with coverage report
poetry run pytest --cov=giskit --cov-report=html
```

### Test Markers

- `@pytest.mark.unit` - Fast unit tests (no external dependencies)
- `@pytest.mark.integration` - Integration tests (require real API calls)
- `@pytest.mark.slow` - Slow tests (>1s runtime)

## Linting & Formatting Commands

```bash
# Run linter
poetry run ruff check .

# Run linter with auto-fix
poetry run ruff check . --fix

# Format code
poetry run ruff format .

# Type checking
poetry run mypy giskit/

# Run all pre-commit hooks
pre-commit run --all-files
```

## Code Style Guidelines

### Formatting (Ruff)

- **Line length:** 100 characters
- **Target version:** Python 3.10
- Use Ruff for all formatting (replaces Black, isort)

### Import Order

Imports are sorted by isort rules via Ruff:

```python
# Standard library
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional, Union

# Third-party
import geopandas as gpd
import httpx
from pydantic import BaseModel, Field

# Local
from giskit.core.recipe import Dataset, Location
from giskit.protocols.base import Protocol
```

### Type Annotations

- Use type hints for function signatures
- Use `Optional[T]` for nullable types
- Use generic types: `list[str]`, `dict[str, Any]`, `tuple[float, ...]`
- Use `Union` sparingly; prefer specific types

```python
async def get_features(
    self,
    bbox: tuple[float, float, float, float],
    layers: Optional[list[str]] = None,
    crs: str = "EPSG:4326",
) -> gpd.GeoDataFrame:
```

### Naming Conventions

- **Classes:** `PascalCase` (e.g., `OGCFeaturesProtocol`, `LocationType`)
- **Functions/methods:** `snake_case` (e.g., `get_features`, `download_dataset`)
- **Constants:** `UPPER_SNAKE_CASE`
- **Private members:** Prefix with `_` (e.g., `self._protocols`)
- **Enums:** `PascalCase` class, `UPPER_SNAKE_CASE` values

```python
class LocationType(str, Enum):
    ADDRESS = "address"
    POINT = "point"
    BBOX = "bbox"
```

### Error Handling

- Create specific exception classes per module
- Inherit from `Exception` for custom exceptions
- Use `raise ... from e` to chain exceptions (except where B904 is ignored in config)

```python
class OGCFeaturesError(Exception):
    """Raised when OGC Features API requests fail."""
    pass

try:
    response = await client.get(url)
    response.raise_for_status()
except httpx.HTTPError as e:
    raise OGCFeaturesError(f"Failed to get capabilities: {e}") from e
```

### Docstrings

Use Google-style docstrings:

```python
def download_dataset(
    self,
    dataset: Dataset,
    location: Location,
    output_path: Path,
) -> gpd.GeoDataFrame:
    """Download a dataset for a specific location.

    Args:
        dataset: Dataset specification from recipe
        location: Location specification from recipe
        output_path: Where to save downloaded data

    Returns:
        GeoDataFrame with downloaded data

    Raises:
        ValueError: If dataset configuration is invalid
    """
```

### Pydantic Models

- Use `Field()` for validation and documentation
- Implement validators with `@field_validator` and `@model_validator`
- Return `self` from `@model_validator(mode="after")`

```python
class Location(BaseModel):
    type: LocationType = Field(..., description="Type of location")
    radius: Optional[float] = Field(None, ge=0, le=50000)

    @model_validator(mode="after")
    def validate_radius(self) -> "Location":
        # validation logic
        return self
```

### Async Code

- Use `async/await` for I/O operations
- Use `httpx` for HTTP requests (not `requests`)
- Test async code with `pytest-asyncio` (auto mode enabled)

## Project Structure

```
giskit/
├── cli/            # CLI commands (click-based)
├── config/         # YAML configurations for providers/services
├── core/           # Core business logic (recipe.py, spatial.py)
├── exporters/      # Export formats (IFC, GLB, OBJ)
├── indexer/        # Monitoring & quirks
├── protocols/      # Protocol implementations (ogc_features, wmts, wfs)
└── providers/      # Data providers (base.py, pdok.py)

tests/
├── unit/           # Fast unit tests (mocked, no external deps)
└── integration/    # Slow integration tests (real API calls)
```

## Commit Message Convention

Follow conventional commits:

```
feat: add support for CityJSON export
fix: handle polygon holes in IFC export
docs: update CONTRIBUTING guide
test: add unit tests for temporal filtering
refactor: simplify quirks registry
```

## Pre-commit Hooks

Pre-commit runs automatically on `git commit`:

1. **ruff-format** - Code formatting
2. **ruff** - Linting with auto-fix
3. **pytest-unit** - Unit tests (fast)
4. Standard file checks (trailing whitespace, YAML syntax, etc.)

If hooks fail with auto-fixes, stage the changes and commit again.
