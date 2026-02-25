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

## Architecture Overview (Post-Refactoring 2026)

pygiskit follows a layered, config-driven architecture:

### Core Principles

1. **Config-Driven**: Services defined in YAML (`config/services/*.yml`), not hardcoded
2. **Protocol Registry**: Dynamic protocol registration (WMTS, WCS, OGC Features, WFS)
3. **Separation of Concerns**: Clear boundaries: CLI → Core (RecipeRunner/OutputManager) → Providers → Protocols
4. **Testability**: Core modules are async-testable with clear interfaces

### Architecture Layers

```
┌─────────────────────────────────────────────┐
│     CLI Layer (giskit/cli/)                │
│     • download.py - User interface (189L)   │
└────────────────┬────────────────────────────┘
                 ▼
┌─────────────────────────────────────────────┐
│     Core Business Logic (giskit/core/)      │
│     • runner.py - RecipeRunner (376L)       │
│     • output.py - OutputManager (544L)      │
│     • spatial.py - Geocoding, transforms    │
│     • recipe.py - Pydantic models           │
│     • constants.py - Centralized constants  │
└────────────────┬────────────────────────────┘
                 ▼
┌─────────────────────────────────────────────┐
│     Provider Layer (giskit/providers/)      │
│     • config_driven.py - Base (154L)        │
│     • wmts.py - WMTSProvider                │
│     • wcs.py - WCSProvider                  │
│     • ogc_features.py - OGCFeaturesProvider │
└────────────────┬────────────────────────────┘
                 ▼
┌─────────────────────────────────────────────┐
│     Protocol Layer (giskit/protocols/)      │
│     • registry.py - ProtocolRegistry (135L) │
│     • wmts.py - WMTSProtocol                │
│     • wcs.py - WCSProtocol                  │
│     • ogc_features.py - OGCFeaturesProtocol │
└─────────────────────────────────────────────┘
```

### Key Refactorings (2026)

**Phase 1 - Quick Wins:**
- Constants extraction → Eliminated ~50 magic numbers
- Exception chaining → 100% B904 compliance
- Logging → Replaced 25+ print statements
- YAML utilities → Eliminated 4 duplicate implementations

**Phase 2 - Core Refactoring:**
- ConfigDrivenProvider → Eliminated ~298 lines across 3 providers
- ProtocolRegistry → Eliminated 60-line if/elif chain
- Centralized HTTP errors → Eliminated ~40-50 lines of duplication

**Phase 3 - CLI Refactoring:**
- CLI reduction: 744 → 189 lines (**74% reduction!**)
- RecipeRunner created: 376 lines (business logic)
- OutputManager created: 544 lines (file I/O)
- Clear separation: UI ↔ Logic ↔ I/O

**Phase 4 - Testing:**
- 32 unit tests for core modules (775 lines)
- 36 integration tests for providers (886 lines)
- **Total: 68 test methods** covering refactored components

### Module Responsibilities

**CLI Layer** (`giskit/cli/`):
- Argument parsing and user interaction only
- Delegates all business logic to RecipeRunner
- Delegates all file I/O to OutputManager
- **download.py**: 189 lines of pure UI code

**Core Layer** (`giskit/core/`):
- **runner.py** (RecipeRunner):
  - Execute recipes and coordinate downloads
  - Normalize layer names (_collection/_layer columns)
  - Build metadata for IFC/GLB exports
  - Calculate origin points for georeferencing
- **output.py** (OutputManager):
  - Save GeoDataFrames to GPKG/GeoJSON/SHP/FGB
  - Auto-export to IFC/GLB/OBJ if configured
  - Clean internal columns (_provider, _service)
  - Progress callback integration
- **spatial.py**: Geocoding, CRS transforms, bbox operations
- **recipe.py**: Pydantic models (Location, Dataset, OutputConfig, Recipe)
- **constants.py**: Centralized constants (no magic numbers)

**Provider Layer** (`giskit/providers/`):
- **config_driven.py** (ConfigDrivenProvider base class):
  - Load services from YAML files
  - Cache configurations
  - Common service metadata access
- **Provider implementations** (WMTSProvider, WCSProvider, etc.):
  - Inherit from ConfigDrivenProvider
  - Create protocol instances for each service/layer/coverage
  - Implement `download_dataset()` using protocols

**Protocol Layer** (`giskit/protocols/`):
- **registry.py** (ProtocolRegistry):
  - Register protocol factories
  - Create protocol instances
  - Singleton pattern via `get_protocol_registry()`
- **Protocol implementations** (WMTSProtocol, WCSProtocol, etc.):
  - Inherit from Protocol base class
  - Implement API communication (HTTP requests)
  - Return GeoDataFrames or images

### Adding New Components

**New Provider** (see [docs/adding_providers.md](docs/adding_providers.md)):
1. Create YAML in `config/services/provider-name.yml`
2. Create provider class inheriting from `ConfigDrivenProvider`
3. Register with `register_provider()`

**New Protocol** (see [docs/adding_protocols.md](docs/adding_protocols.md)):
1. Create protocol class inheriting from `Protocol`
2. Register with `ProtocolRegistry.register_protocol()`

**New Export Format**:
1. Add method to `OutputManager` in `core/output.py`
2. Update `save_layers()` to call new method

## Project Structure

```
giskit/
├── cli/            # CLI commands (189 lines - UI only)
├── config/         # YAML configurations for providers/services
│   ├── services/   # Service YAML files (pdok-wmts.yml, pdok-wcs.yml, etc.)
│   └── yaml_utils.py  # YAML loading utilities
├── core/           # Core business logic (refactored Phase 3)
│   ├── runner.py      # RecipeRunner (376 lines)
│   ├── output.py      # OutputManager (544 lines)
│   ├── spatial.py     # Geocoding, transforms
│   ├── recipe.py      # Pydantic models
│   └── constants.py   # Centralized constants (Phase 1)
├── exporters/      # Export formats (IFC, GLB, OBJ)
├── indexer/        # Monitoring & quirks
├── protocols/      # Protocol implementations (refactored Phase 2)
│   ├── registry.py       # ProtocolRegistry (135 lines)
│   ├── base.py           # Protocol base class with HTTP error handling
│   ├── wmts.py           # WMTSProtocol
│   ├── wcs.py            # WCSProtocol
│   ├── ogc_features.py   # OGCFeaturesProtocol
│   └── wfs.py            # WFSProtocol
└── providers/      # Data providers (refactored Phase 2)
    ├── config_driven.py  # ConfigDrivenProvider base (154 lines)
    ├── wmts.py           # WMTSProvider
    ├── wcs.py            # WCSProvider
    ├── ogc_features.py   # OGCFeaturesProvider
    └── base.py           # Provider registry

tests/
├── unit/           # Unit tests (32 tests, 775 lines)
│   ├── test_runner.py              # RecipeRunner tests
│   ├── test_output.py              # OutputManager tests
│   ├── test_config_driven_provider.py
│   └── test_protocol_registry.py
└── integration/    # Integration tests (36 tests, 886 lines)
    ├── test_wmts_provider.py
    ├── test_wcs_provider.py
    └── test_pdok_providers.py
```

## Documentation Resources

- **[docs/architecture.md](docs/architecture.md)** - Complete architecture guide
- **[docs/adding_providers.md](docs/adding_providers.md)** - Provider development guide
- **[docs/adding_protocols.md](docs/adding_protocols.md)** - Protocol development guide  
- **[REFACTORING_PLAN.md](REFACTORING_PLAN.md)** - Complete refactoring roadmap

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
