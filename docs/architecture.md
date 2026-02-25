# Architecture Overview

This document describes the architecture of pygiskit after the Phase 1-3 refactoring (2026).

## Design Principles

1. **Config-Driven**: Services and providers are configured via YAML files, not hardcoded
2. **Protocol-Oriented**: Use protocol instances (WMTS, WCS, OGC Features, WFS) for data access
3. **Registry Pattern**: Centralized protocol and provider registration
4. **Separation of Concerns**: Clear boundaries between CLI, core logic, and I/O
5. **Testability**: Core modules are async-testable with clear interfaces

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         CLI Layer                                │
│                     (giskit/cli/*.py)                           │
│  • User interface                                                │
│  • Argument parsing                                              │
│  • Delegates to RecipeRunner                                     │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Core Business Logic                         │
│                     (giskit/core/*.py)                          │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ RecipeRunner │  │ OutputManager│  │ Spatial Utils│         │
│  │              │  │              │  │              │         │
│  │ • Execute    │  │ • Save layers│  │ • Geocoding  │         │
│  │ • Metadata   │  │ • Auto-export│  │ • Transforms │         │
│  │ • Progress   │  │ • Formats    │  │ • Buffers    │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Provider Layer                              │
│                   (giskit/providers/*.py)                       │
│                                                                  │
│  ┌──────────────────────────────────────────────────────┐      │
│  │         ConfigDrivenProvider (base class)             │      │
│  │  • Load YAML configs from config/services/*.yml       │      │
│  │  • Cache configurations                               │      │
│  │  • Manage service metadata                            │      │
│  └───────┬──────────────────────────────────────────────┘      │
│          │                                                       │
│          ├── WMTSProvider (aerial imagery, maps)               │
│          ├── WCSProvider (elevation, AHN)                       │
│          ├── OGCFeaturesProvider (BAG, BGT, etc.)              │
│          └── WFSProvider (legacy vector services)              │
│                                                                  │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Protocol Layer                              │
│                   (giskit/protocols/*.py)                       │
│                                                                  │
│  ┌──────────────────────────────────────────────────────┐      │
│  │         ProtocolRegistry (singleton pattern)          │      │
│  │  • Register protocol factories                        │      │
│  │  • Create protocol instances                          │      │
│  └───────┬──────────────────────────────────────────────┘      │
│          │                                                       │
│          ├── WMTSProtocol (tile-based imagery)                 │
│          ├── WCSProtocol (coverage/elevation data)             │
│          ├── OGCFeaturesProtocol (modern vector API)           │
│          └── WFSProtocol (legacy WFS 2.0)                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Module Structure

### Core Modules (`giskit/core/`)

Created during Phase 3 refactoring to separate business logic from CLI.

#### `runner.py` - RecipeRunner
- **Purpose**: Execute recipes and coordinate data downloads
- **Responsibilities**:
  - Parse recipe files (JSON/YAML)
  - Get appropriate provider for each dataset
  - Download datasets with progress tracking
  - Normalize layer names and build metadata
  - Calculate origin points for 3D exports
- **Key Methods**:
  - `execute()` - Main execution flow
  - `_normalize_layer_names()` - Handle _collection/_layer columns
  - `_build_metadata_dict()` - Create metadata for IFC/GLB exports
  - `_calculate_origin_point()` - Calculate origin for georeferencing

#### `output.py` - OutputManager
- **Purpose**: Save downloaded data in various formats
- **Responsibilities**:
  - Save GeoDataFrames to GPKG, GeoJSON, Shapefile, FlatGeobuf
  - Auto-export to IFC/GLB/OBJ if configured
  - Clean internal columns (_provider, _service, etc.)
  - Progress callbacks for UI
  - Path resolution (relative/absolute)
- **Key Methods**:
  - `save_layers()` - Save all layers to disk
  - `_clean_internal_columns()` - Remove internal metadata
  - Auto-export methods for 3D formats

#### `spatial.py` - Spatial Utilities
- **Purpose**: Coordinate transformations and geocoding
- **Functions**:
  - `location_to_bbox()` - Convert Location to bbox
  - `geocode()` - Address to coordinates (PDOK Locatieserver)
  - `transform_bbox()`, `transform_point()` - CRS transformations
  - `buffer_point_to_bbox()` - Create bbox from point + radius

#### `recipe.py` - Recipe Models
- **Purpose**: Pydantic models for recipe validation
- **Models**:
  - `Location` - Where to download (address, point, bbox, polygon)
  - `Dataset` - What to download (provider, service, layers)
  - `OutputConfig` - How to export (format, CRS, IFC settings)
  - `Recipe` - Complete recipe specification

#### `constants.py` - Constants
- **Purpose**: Centralized constants (Phase 1 refactoring)
- Eliminated magic numbers throughout codebase
- Default values for resolutions, timeouts, limits, etc.

### Provider Layer (`giskit/providers/`)

Refactored in Phase 2 to use config-driven pattern.

#### `config_driven.py` - ConfigDrivenProvider (base class)
- **Purpose**: Base class for YAML-configured providers
- **Pattern**: Template method + lazy loading
- **Features**:
  - Load services from `config/services/{name}.yml`
  - Cache loaded configurations
  - `get_service_config()` helper method
  - Common metadata access patterns

#### Provider Implementations

All providers inherit from `ConfigDrivenProvider`:

| Provider | Protocol(s) | Data Type | Config File |
|----------|-------------|-----------|-------------|
| `WMTSProvider` | WMTS | Raster tiles (imagery, maps) | `pdok-wmts.yml` |
| `WCSProvider` | WCS | Coverage (elevation, AHN) | `pdok-wcs.yml` |
| `OGCFeaturesProvider` | OGC Features | Vector (BAG, BGT, etc.) | `pdok.yml` |
| `WFSProvider` | WFS 2.0 | Vector (legacy) | N/A |

### Protocol Layer (`giskit/protocols/`)

Protocol implementations handle low-level API communication.

#### `registry.py` - ProtocolRegistry
- **Purpose**: Centralized protocol registration and creation
- **Pattern**: Registry + Factory
- **Features**:
  - `register_protocol()` - Register protocol factories
  - `create_protocol()` - Create protocol instances
  - `get_available_protocols()` - List registered protocols
  - Singleton instance via `get_protocol_registry()`

#### Protocol Implementations

| Protocol | Standard | Use Case | Key Methods |
|----------|----------|----------|-------------|
| `WMTSProtocol` | OGC WMTS 1.0 | Pre-rendered tiles | `get_coverage()` |
| `WCSProtocol` | OGC WCS 2.0 | Elevation/coverage | `save_coverage_as_geotiff()` |
| `OGCFeaturesProtocol` | OGC API Features | Modern vector API | `get_features()` |
| `WFSProtocol` | OGC WFS 2.0 | Legacy vector API | `get_features()` |

All protocols inherit from `Protocol` base class which provides:
- HTTP error handling (Phase 2 refactoring)
- Logging setup
- Common retry logic
- Progress callback support

### Configuration (`giskit/config/`)

YAML-based service configuration system.

#### `services/*.yml` - Service Configurations

Example structure (`pdok-wmts.yml`):
```yaml
provider:
  name: pdok-wmts
  title: PDOK WMTS Services
  country: NL
  homepage: https://www.pdok.nl
  license: CC0-1.0
  defaults:
    protocol: wmts

services:
  luchtfoto:
    url: https://service.pdok.nl/hwh/luchtfotorgb/wmts/v1_0
    title: Luchtfoto Beeldmateriaal Nederland
    category: imagery
    description: Aerial imagery of the Netherlands (RGB orthophotos)
    keywords: [luchtfoto, aerial, imagery]
    tile_format: jpeg
    tile_matrix_set: EPSG:28992
    layers:
      actueel_25cm: Actueel_ortho25
      actueel_8cm: Actueel_orthoHR
```

Benefits:
- No code changes for new services
- Easy to update URLs, metadata, keywords
- Clear separation of data vs. logic
- Version-controlled service catalog

#### `yaml_utils.py` - YAML Helpers
- **Purpose**: Shared YAML loading utilities (Phase 1 refactoring)
- `load_yaml_config()` - Safe YAML loading with error handling
- `get_config_path()` - Resolve config file paths
- Eliminates duplicate YAML loading code

### CLI Layer (`giskit/cli/`)

Refactored in Phase 3 to delegate to core modules.

**Before Refactoring**: 744 lines of mixed concerns
**After Refactoring**: 189 lines of pure UI logic (**74% reduction!**)

#### `download.py` - Download Command
- Parse arguments
- Load recipe
- Create `RecipeRunner` and `OutputManager`
- Delegate to `runner.execute()`
- Delegate to `output.save_layers()`
- Display results

**Key Change**: CLI now focuses only on argument parsing and user interaction. All business logic moved to `RecipeRunner`.

## Data Flow

### Recipe Execution Flow

```
1. User runs CLI command
   └─> cli/download.py parses arguments

2. CLI creates RecipeRunner
   └─> core/runner.py loads recipe

3. RecipeRunner executes recipe
   ├─> For each dataset:
   │   ├─> Get provider from registry
   │   │   └─> providers/base.py: get_provider()
   │   ├─> Provider loads config
   │   │   └─> providers/config_driven.py: ConfigDrivenProvider
   │   ├─> Provider creates protocol instance
   │   │   └─> protocols/registry.py: ProtocolRegistry
   │   └─> Protocol downloads data
   │       └─> protocols/{wmts,wcs,ogc_features}.py
   │
   └─> Returns GeoDataFrame with data

4. CLI creates OutputManager
   └─> core/output.py saves data

5. OutputManager saves layers
   ├─> Save to GPKG/GeoJSON/SHP/FGB
   └─> Auto-export to IFC/GLB/OBJ if configured
```

### Configuration Loading Flow

```
1. Provider initialized
   └─> providers/wmts.py: WMTSProvider("pdok-wmts")

2. ConfigDrivenProvider.__init__()
   ├─> Load config/services/pdok-wmts.yml
   ├─> Cache configuration
   └─> Store services dict

3. Provider creates protocols
   ├─> For each service in config:
   │   └─> For each layer:
   │       ├─> Create protocol instance
   │       └─> Store in self.protocols dict
   │
   └─> protocols/wmts.py: WMTSProtocol(base_url=..., layer=...)
```

## Design Patterns Used

### 1. Config-Driven Provider Pattern
**Location**: `providers/config_driven.py`

**Problem**: Adding new services required code changes in provider classes.

**Solution**: Load service configurations from YAML files.

**Benefits**:
- No code changes for new services
- Easy to update service metadata
- Clear separation of configuration and logic

### 2. Registry Pattern
**Location**: `protocols/registry.py`

**Problem**: Large if/elif chains to select protocol implementations.

**Solution**: Protocol factory registry with dynamic registration.

**Benefits**:
- Extensible without modifying existing code
- Clear protocol lifecycle management
- Easy to add new protocols

### 3. Template Method Pattern
**Location**: `providers/config_driven.py`, `protocols/base.py`

**Problem**: Duplicate initialization and error handling across providers/protocols.

**Solution**: Base classes with template methods for common operations.

**Benefits**:
- DRY: Common logic in one place
- Consistent error handling
- Easier to test

### 4. Separation of Concerns
**Location**: `core/runner.py`, `core/output.py`, `cli/download.py`

**Problem**: CLI had 744 lines mixing UI, business logic, and I/O.

**Solution**: Extract RecipeRunner (business logic) and OutputManager (I/O).

**Benefits**:
- Testable business logic (no CLI dependencies)
- Reusable core modules (can be used outside CLI)
- Cleaner, more maintainable code

## Key Refactoring Metrics

### Phase 1: Quick Wins (Week 1)
- Extracted constants → Eliminated ~50 magic numbers
- Fixed exception chaining → 100% compliance with B904
- Replaced print with logging → 25+ print statements → proper logging
- Extracted YAML helper → Eliminated 4 duplicate implementations

### Phase 2: Core Refactoring (Week 2-3)
- ConfigDrivenProvider → Eliminated ~298 lines across 3 providers
- ProtocolRegistry → Eliminated 60-line if/elif chain
- Centralized HTTP errors → Eliminated ~40-50 lines of duplicate try/except

### Phase 3: CLI Refactoring (Week 3-4)
- **CLI reduction**: 744 → 189 lines (**74% reduction!**)
- **New core modules**: 920 lines (RecipeRunner 376 + OutputManager 544)
- **Net change**: +365 lines, but vastly improved architecture
- **Separation achieved**: Clear CLI/Core/I/O boundaries

### Phase 4: Testing & Validation (Week 5-6)
- **Unit tests**: 32 test methods (775 lines) for core modules
- **Integration tests**: 36 test methods (886 lines) for providers
- **Total coverage**: 68 test methods covering refactored components

## Testing Strategy

### Unit Tests (`tests/unit/`)
Test core business logic in isolation with mocking:
- `test_runner.py` - RecipeRunner functionality
- `test_output.py` - OutputManager save operations
- `test_config_driven_provider.py` - Config loading and caching
- `test_protocol_registry.py` - Protocol registration and creation

### Integration Tests (`tests/integration/`)
Test component integration with real configs (mocked API calls):
- `test_wmts_provider.py` - WMTS provider end-to-end
- `test_wcs_provider.py` - WCS provider end-to-end
- `test_pdok_providers.py` - ConfigDrivenProvider + ProtocolRegistry integration

### Test Markers
- `@pytest.mark.unit` - Fast unit tests (no external dependencies)
- `@pytest.mark.integration` - Integration tests (real configs, mocked APIs)
- `@pytest.mark.slow` - Slow tests (>1s runtime)

## Future Extensibility

### Adding a New Provider
1. Create YAML config in `config/services/new-provider.yml`
2. Create provider class inheriting from `ConfigDrivenProvider`
3. Register provider with `register_provider("new-provider", NewProvider)`
4. Add tests in `tests/unit/` and `tests/integration/`

See [Adding Providers](adding_providers.md) for detailed guide.

### Adding a New Protocol
1. Create protocol class inheriting from `Protocol`
2. Implement required async methods (e.g., `get_features()`, `get_coverage()`)
3. Register protocol with `ProtocolRegistry.register_protocol()`
4. Add tests in `tests/unit/` and `tests/integration/`

See [Adding Protocols](adding_protocols.md) for detailed guide.

### Adding a New Export Format
1. Add export method to `OutputManager` in `core/output.py`
2. Update `save_layers()` to call new export method
3. Add tests in `tests/unit/test_output.py`
4. Update documentation

## References

- **REFACTORING_PLAN.md** - Complete refactoring roadmap and milestones
- **AGENTS.md** - AI coding agent guidelines and conventions
- **CONTRIBUTING.md** - Contribution guidelines
- **README.md** - Project overview and getting started
