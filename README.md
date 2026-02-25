# GISKit

**Recipe-driven spatial data downloader for Netherlands geo-data**

[![Python 3.10-3.12](https://img.shields.io/badge/python-3.10--3.12-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-123%20passing-brightgreen.svg)](tests/)

> **⚠️ Version Policy**: Odd minor versions (0.1.x, 0.3.x, 0.5.x, etc.) may introduce breaking changes as we refine the architecture. Even minor versions (0.2.x, 0.4.x, etc.) maintain backward compatibility. Pin to specific versions in production.

---

## What is GISKit?

GISKit is a Python tool for downloading Dutch spatial data using simple JSON "recipes". Define what data you need and where you need it - GISKit handles the downloads and combines everything into a single GeoPackage.

**Perfect for:**
- Creating project underlays for construction/infrastructure projects
- Downloading base maps for GIS analysis
- Collecting spatial context data for locations
- Automating repetitive spatial data downloads

### Key Features

- **Recipe-Driven**: Define your data needs in simple JSON
- **Multi-Provider**: Access 68+ datasets from 5 providers (PDOK, BAG3D, Klimaateffectatlas, DUO, NDOV)
- **Service Catalog**: Discover available data with search and filtering
- **Smart Downloads**: Automatic bbox calculation from addresses
- **Single Output**: Everything combined in one GeoPackage
- **CRS Handling**: Automatic coordinate transformation
- **Export Options**: GeoPackage, GeoJSON, CityJSON, optional IFC/GLB
- **Climate Data**: 26 climate adaptation services for heat, flood, drought analysis


## Quick Start

### Installation

**From PyPI (recommended):**
```bash
pip install pygiskit

# With IFC export support (Python 3.10-3.12 only)
pip install pygiskit[ifc]
```

**From source:**
```bash
git clone https://github.com/sanderboer/py-giskit.git
cd py-giskit
pip install -e .
```

### Your First Recipe

**Option 1: Generate from template**

```bash
# Generate complete template with all providers
giskit providers json -o my_recipe.json

# Edit the JSON to keep only the datasets you need
# Then run it:
giskit run my_recipe.json
```

**Option 2: Write from scratch**

Create `dam_square.json`:

```json
{
  "name": "Dam Square Buildings",
  "description": "Download buildings and roads around Dam Square in Amsterdam",
  "location": {
    "type": "address",
    "value": "Dam 1, Amsterdam",
    "radius": 500
  },
  "datasets": [
    {
      "provider": "pdok",
      "service": "bgt",
      "layers": ["pand", "wegdeel"]
    }
  ],
  "output": {
    "path": "./dam_square.gpkg",
    "format": "gpkg",
    "crs": "EPSG:28992",
    "overwrite": true
  }
}
```

Run it:

```bash
giskit run dam_square.json
```

Result: `dam_square.gpkg` with buildings and roads around Dam Square!


## Architecture

GISKit follows a layered, config-driven architecture designed for extensibility and maintainability:

### Core Design Principles

1. **Config-Driven Providers**: Services defined in YAML files (`config/services/*.yml`), not hardcoded
2. **Protocol Registry**: Dynamic protocol registration for WMTS, WCS, OGC Features, WFS
3. **Separation of Concerns**: Clean boundaries between CLI, business logic (RecipeRunner), and I/O (OutputManager)
4. **Async-First**: All data access is async for performance and testability

### Architecture Layers

```
CLI Layer (giskit/cli/)
   ↓
Core Business Logic (giskit/core/)
   ├─ RecipeRunner: Execute recipes, coordinate downloads
   ├─ OutputManager: Save data in multiple formats
   └─ Spatial Utils: Geocoding, CRS transforms
   ↓
Provider Layer (giskit/providers/)
   ├─ ConfigDrivenProvider (base class)
   ├─ WMTSProvider, WCSProvider
   └─ OGCFeaturesProvider, WFSProvider
   ↓
Protocol Layer (giskit/protocols/)
   ├─ ProtocolRegistry (factory pattern)
   ├─ WMTSProtocol, WCSProtocol
   └─ OGCFeaturesProtocol, WFSProtocol
```

### Key Refactorings (2026)

- **CLI Reduction**: 744 → 189 lines (74% reduction) - business logic extracted to core modules
- **ConfigDrivenProvider Pattern**: Add new services via YAML, no code changes needed
- **ProtocolRegistry**: Replace 60-line if/elif chain with dynamic registration
- **Test Coverage**: 68 test methods (32 unit + 36 integration) for refactored components

For detailed architecture documentation, see:
- [docs/architecture.md](docs/architecture.md) - Complete system design
- [docs/adding_providers.md](docs/adding_providers.md) - How to add new providers
- [docs/adding_protocols.md](docs/adding_protocols.md) - How to add new protocols


## Discovering Available Data

GISKit provides a **service catalog** to help you discover what data is available before writing recipes.

### CLI Commands

**Generate complete recipe template:**

GISKit has two modes for discovering available data:

#### 🚀 Fast Mode (Default)
Shows common layer examples - instant, works offline:
```bash
giskit providers json                    # All providers
giskit providers json -p pdok           # Only PDOK
giskit providers json -o template.json  # Save to file
```
**Output:** Common examples (e.g., BGT: `["pand", "wegdeel", "waterdeel"]`)

#### 🔍 Complete Mode (--fetch-layers)
Fetches ALL layers from service APIs - complete layer lists:
```bash
giskit providers json --fetch-layers                      # All providers, all layers
giskit providers json -p pdok --fetch-layers             # PDOK complete
giskit providers json --fetch-layers -o template.json    # Save complete template
giskit providers json --fetch-layers --no-cache          # Force refresh
```
**Output:** Complete lists (e.g., BGT: all 49 layers including `ondersteunendwaterdeel`)
**Performance:**
- First run: ~1-2 minutes (queries 85 service APIs)
- Cached runs: <1 second (uses `~/.cache/giskit/layers/`)
- Use `--no-cache` to force refresh

**Comparison:**
| Mode | BGT Layers | Speed | Internet |
|------|------------|-------|----------|
| Fast | 3 examples | Instant | No |
| Complete | 49 complete | 1-2 min (first) / <1s (cached) | Yes |

The generated JSON shows:
- All available providers, services, and complete layer lists
- Predefined layers for WMTS/WCS services (e.g., AHN: dsm, dtm)
- All collections for OGC Features/WFS (e.g., BGT: all 49 layers including ondersteunendwaterdeel)
- Default options (tile_format, tile_matrix_set, format)
- Cached results for fast subsequent runs (~1 second)

**Example output (Fast Mode):**
```json
{
  "service": "bgt",
  "layers": ["pand", "wegdeel", "waterdeel"],
  "_note": "Common layers - use --fetch-layers for complete list"
}
```

**Example output (Complete Mode with --fetch-layers):**
```json
{
  "service": "bgt",
  "layers": [
    "bak", "begroeidterreindeel", "begroeidterreindeel_kruinlijn",
    "bord", "buurt", "functioneelgebied", "gebouwinstallatie",
    "installatie", "kast", "kunstwerkdeel_lijn", "kunstwerkdeel_punt",
    "kunstwerkdeel_vlak", "mast", "onbegroeidterreindeel",
    "onbegroeidterreindeel_kruinlijn", "ondersteunendwaterdeel",
    "ondersteunendwegdeel", "ondersteunendwegdeel_kruinlijn",
    "ongeclassificeerdobject", "openbareruimte", "openbareruimtelabel",
    "overbruggingsdeel", "overigbouwwerk", "overigescheiding",
    "paal", "pand", "pand_nummeraanduiding", "put",
    "scheiding_lijn", "scheiding_vlak", "sensor_lijn", "sensor_punt",
    "spoor", "stadsdeel", "straatmeubilair", "tunneldeel",
    "vegetatieobject_lijn", "vegetatieobject_punt", "vegetatieobject_vlak",
    "waterdeel", "waterinrichtingselement_lijn", "waterinrichtingselement_punt",
    "waterschap", "wegdeel", "wegdeel_kruinlijn",
    "weginrichtingselement_lijn", "weginrichtingselement_punt",
    "weginrichtingselement_vlak", "wijk"
  ],
  "_note": "Complete list from API (49 layers)"
}
```

Edit the generated JSON to keep only the datasets you need, then run:
```bash
giskit run template.json
```

### Python API

```python
from giskit.catalog import (
    print_catalog,           # Browse all providers
    search_services,         # Search by keyword
    list_services_by_protocol,  # Filter by protocol type
    export_catalog_json      # Export catalog as JSON
)

# Quick overview
print_catalog()
# Output:
# 📦 PDOK
#    PDOK - Publieke Dienstverlening Op de Kaart
#    Services: 52
#    Protocols: ogc-features, wmts, wcs

# Search for specific data
results = search_services("elevation")
# → {'pdok': [{'id': 'ahn', 'title': 'Actueel Hoogtebestand Nederland', ...}]}

# Find all raster/elevation services
wcs_services = list_services_by_protocol("wcs")
# → {'pdok': ['ahn']}

# Export catalog for external tools
export_catalog_json("catalog.json", detailed=True)
```

### Finding the Right Service

**By keyword:**
```python
# Find 3D building data
search_services("3d")
# → bag3d/bag3d, pdok/3d-basisvoorziening, pdok/bag3d

# Find elevation data
search_services("elevation")
# → pdok/ahn

# Find cadastral parcels
search_services("kadaster")
# → pdok/brk
```

**By category:**
```python
from giskit.catalog import list_services_by_category

# See all categories
by_category = list_services_by_category()
# → {'pdok': {'base_registers': ['bgt', 'bag', 'brk'],
#             'elevation': ['ahn'],
#             'infrastructure': ['nwb-wegen', ...], ...}}

# Get only elevation data
elevation = list_services_by_category("elevation")
```

**By protocol type:**
```python
# Vector data (OGC Features)
vector_services = list_services_by_protocol("ogc-features")

# Raster/elevation data (WCS)
raster_services = list_services_by_protocol("wcs")

# Pre-rendered tiles (WMTS)
tile_services = list_services_by_protocol("wmts")
```

### Catalog Demo

Run the interactive catalog demo:

```bash
python examples/catalog_demo.py
```

This shows:
- Complete catalog overview
- Search examples
- Services by protocol and category
- How to compose recipes from search results


## Recipe Examples

All examples are in the `recipes/` directory. Try them out:

```bash
# Download buildings and infrastructure around Curieweg, Spijkenisse
giskit run recipes/curieweg_multi_service.json

# Amsterdam Dam Square with buildings
giskit run recipes/amsterdam_dam_square.json

# Climate risk assessment for Amsterdam
giskit run recipes/amsterdam_klimaat_check.json

# Public transport stops in Amsterdam
giskit run recipes/ov_haltes_amsterdam.json

# Schools in Amsterdam
giskit run recipes/amsterdam_scholen.json

# Simple bbox example
giskit run recipes/bbox_simple.json
```

### Urban Planning Dataset

Comprehensive data for a project location:

```json
{
  "name": "Curieweg Project Underlay",
  "description": "Multi-service data collection for urban planning analysis",
  "location": {
    "type": "address",
    "value": "Curieweg 7a, Spijkenisse",
    "radius": 1000
  },
  "datasets": [
    {"provider": "pdok", "service": "bgt", "layers": ["pand", "wegdeel", "waterdeel"]},
    {"provider": "pdok", "service": "bag", "layers": ["pand", "verblijfsobject"]},
    {"provider": "pdok", "service": "cbs-wijken-buurten-2024", "layers": ["buurten"]},
    {"provider": "pdok", "service": "bestuurlijkegebieden", "layers": ["gemeenten"]}
  ],
  "output": {
    "path": "./curieweg.gpkg",
    "format": "gpkg",
    "crs": "EPSG:28992",
    "overwrite": true
  }
}
```

### Output Configuration

The `output` section supports multiple options:

```json
{
  "output": {
    "path": "./output.gpkg",           // Output file path
    "format": "gpkg",                   // Format: gpkg, geojson, shp
    "crs": "EPSG:28992",                // Target coordinate system
    "overwrite": true,                  // Overwrite existing file
    "layer_prefix": "data_"             // Optional prefix for layer names
  }
}
```

**Available formats:**
- `gpkg` - GeoPackage (default, recommended for multiple layers)
- `geojson` - GeoJSON (single layer only)
- `shp` - Shapefile (legacy support)
- `json` - CityJSON (for 3D data from BAG3D)

### Location Types

**Address with buffer:**
```json
{
  "location": {
    "type": "address",
    "value": "Curieweg 7a, Spijkenisse",
    "radius": 1000
  }
}
```

**Point coordinates:**
```json
{
  "location": {
    "type": "point",
    "value": [4.89, 52.37],
    "crs": "EPSG:4326",
    "radius": 500
  }
}
```

**Bounding box:**
```json
{
  "location": {
    "type": "bbox",
    "value": [120700, 487000, 120950, 487250],
    "crs": "EPSG:28992"
  }
}
```


## Available Data Sources

**Quick Discovery:** Use the [catalog system](#discovering-available-data) to search for specific data types:
```python
from giskit.catalog import search_services, print_catalog
print_catalog()  # Browse all 68+ services across 5 providers
search_services("elevation")  # Find specific data
```

### Current Providers

GISKit provides access to **68+ datasets** from 5 different providers:

**PDOK** (52 services) - Dutch government spatial data
**BAG3D** (1 service) - 3D building models in CityJSON format
**Klimaateffectatlas** (26 services) - Climate adaptation data (heat, flooding, drought)
**DUO** (1 service) - School locations and data (CSV format)
**NDOV** (1 service) - Public transport stops (GTFS format)

### PDOK (Platform Digitale Overheid - Netherlands)

GISKit provides access to **52 Dutch government datasets** via PDOK:

**Base Registries (Basisregistraties):**
- **BGT** - Large Scale Topography (54 layers: buildings, roads, water, terrain, etc.)
- **BAG** - Buildings and Addresses (buildings, addresses, residence objects)
- **BAG3D** - 3D Building Models (LoD 1.2, 1.3, 2.2 in CityJSON format)
- **BRK** - Cadastral Parcels

**Infrastructure:**
- **NWB Roads** - National Road Database (road segments, junctions)
- **NWB Waterways** - Waterway network

**Topography & Elevation:**
- **AHN** - Actueel Hoogtebestand Nederland (elevation data via WCS)
- **Luchtfoto** - Aerial imagery (WMTS tiles)

**Statistics & Administration:**
- **CBS Neighborhoods 2024** - Statistical areas (neighborhoods, districts, municipalities)
- **Administrative Boundaries** - Municipalities, provinces, water boards

**Environment:**
- **Protected Areas** - Nature reserves, Natura 2000
- **Soil Data** - Soil types, contamination

### Klimaateffectatlas (Climate Effect Atlas - Netherlands)

**26 climate adaptation datasets** for heat stress, flooding, and drought risk assessment:

**Heat Stress (6 services):**
- Social vulnerability to heat
- Heat island effect
- Perceived temperature
- Distance to cooling areas
- Shade maps
- Elderly vulnerability

**Flooding Risk (9 services):**
- Heavy precipitation (current + 2050)
- Extreme precipitation (current + 2050)
- Safe zones and dry floors
- Groundwater flooding risk

**Drought Risk (4 services):**
- 10-year precipitation deficit (current + 2050)
- Nature sensitivity to drought
- Water salinization risk

**Urban Characteristics (4 services):**
- Green percentage per neighborhood
- Paved surface percentage
- Water percentage
- Municipality boundaries

See [docs/KLIMAATEFFECTATLAS_INTEGRATION.md](docs/KLIMAATEFFECTATLAS_INTEGRATION.md) for complete service list.

### DUO (Education Data - Netherlands)

**School Locations** - All schools in Netherlands with type, students, address (CSV + geocoding)

### NDOV (Public Transport - Netherlands)

**OV Stops** - ~60,000 public transport stops across Netherlands (GTFS format)

**Current providers:** `pdok`, `bag3d`, `klimaateffectatlas`, `duo`, `ndov`

See [docs/PDOK_SERVICES.md](docs/PDOK_SERVICES.md) for complete catalog with all layers.

### Planned Providers

- **OpenStreetMap** - Global POI, buildings, roads via Overpass API


## CLI Commands

**Run recipes:**
```bash
# Execute a recipe
giskit run recipe.json

# Validate recipe syntax
giskit recipe validate recipe.json
```

**Explore providers:**
```bash
# List available providers and services
giskit providers list

# Generate complete recipe template with all providers/services
giskit providers json

# Generate template for specific provider
giskit providers json -p pdok

# Save template to file for editing
giskit providers json -o template.json

# Show PDOK service details
giskit providers info pdok
```

**Monitor API quirks:**
```bash
# Show known API quirks for providers
giskit quirks list

# Show details for specific provider
giskit quirks show pdok ogc-features

# Monitor which quirks are being applied
giskit quirks monitor
```

## Export Formats

**Built-in formats:**
- GeoPackage (`.gpkg`) - default, recommended
- GeoJSON (`.geojson`)
- Shapefile (`.shp`)
- CityJSON (`.json`) - for 3D data

**Optional IFC/GLB export:**

Requires `pip install giskit[ifc]` (Python 3.10-3.12 only)

```bash
# Export GeoPackage to IFC
giskit export ifc data.gpkg output.ifc

# Convert IFC to GLB (for web viewers)
giskit export glb data.ifc output.glb
```

See [notes/EXPORT_GUIDE.md](notes/EXPORT_GUIDE.md) for details.


## How It Works

1. **Define** - Write a JSON recipe with location and datasets
2. **Geocode** - GISKit converts addresses to coordinates
3. **Download** - Fetches data from PDOK OGC API Features
4. **Transform** - Converts to target CRS if needed
5. **Combine** - Merges all layers into single GeoPackage

```
┌──────────────┐
│ JSON Recipe  │
└──────┬───────┘
       │
       ▼
┌──────────────┐      ┌─────────────┐
│  Geocoding   │─────▶│ PDOK Lookup │
└──────┬───────┘      └─────────────┘
       │
       ▼
┌──────────────┐
│   Download   │──────┬────────────────┐
└──────┬───────┘      │                │
       │         ┌────▼────┐      ┌────▼────┐
       │         │  BGT    │      │   BAG   │
       │         │ (54 lyr)│      │ (3 lyr) │
       │         └────┬────┘      └────┬────┘
       ▼              │                │
┌──────────────┐      │                │
│  Transform   │◀─────┴────────────────┘
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ GeoPackage   │
│ (.gpkg)      │
└──────────────┘
```

## Project Structure

```
giskit/
├── cli/              # Command-line interface
├── core/             # Recipe parsing, geocoding, spatial ops
├── protocols/        # OGC Features, WMTS, WCS, WFS, GTFS, CSV protocols
├── providers/        # Multi-protocol provider system
├── exporters/        # IFC/GLB export (optional)
├── config/           # YAML configurations for 68+ services
│   ├── providers/    # Provider configs (pdok, bag3d, klimaateffectatlas, duo, ndov)
│   ├── services/     # Service-specific settings
│   └── quirks/       # API compatibility fixes
└── catalog.py        # Service discovery and search

recipes/              # Example recipes ready to use
tests/                # 123 unit and integration tests
docs/                 # Provider documentation and guides
```


## Development

### Running Tests

```bash
# All tests (123 passing)
pytest

# With coverage report
pytest --cov=giskit --cov-report=html

# Specific test suites
pytest tests/unit/
pytest tests/integration/
```

### Code Quality

```bash
# Lint code
ruff check .

# Format code
ruff format .
```

## Documentation

- **[docs/PDOK_SERVICES.md](docs/PDOK_SERVICES.md)** - Complete PDOK service catalog (52 services)
- **[docs/KLIMAATEFFECTATLAS_INTEGRATION.md](docs/KLIMAATEFFECTATLAS_INTEGRATION.md)** - Climate data guide (26 services)
- **[docs/EXTERNAL_SERVICES.md](docs/EXTERNAL_SERVICES.md)** - Overview of all external data sources
- **[notes/EXPORT_GUIDE.md](notes/EXPORT_GUIDE.md)** - IFC/GLB export instructions
- **[notes/QUIRKS_SYSTEM.md](notes/QUIRKS_SYSTEM.md)** - API compatibility handling
- **[notes/BAG3D_ARCHITECTURE.md](notes/BAG3D_ARCHITECTURE.md)** - 3D data handling
- **[CHANGELOG.md](CHANGELOG.md)** - Version history

### For Contributors

- **[docs/publishing/](docs/publishing/)** - PyPI publication guides
- **[notes/](notes/)** - Technical implementation notes

## Use Cases

**Urban Planning:**
- Project site context data (buildings, infrastructure, parcels)
- Statistical area boundaries for reports
- Base maps for presentations
- Climate adaptation planning (heat stress, flooding risk)

**Construction:**
- Site underlay generation
- Existing infrastructure mapping
- Environmental constraints (protected areas, water)

**Climate Adaptation:**
- Heat stress vulnerability assessment
- Flooding risk analysis (current + 2050 scenarios)
- Drought impact evaluation
- Green infrastructure planning

**GIS Analysis:**
- Batch download base data for multiple locations
- Standardized data collection workflows
- Automated updates of project data

**Research:**
- Reproducible spatial data downloads
- Consistent data collection methodology
- Share data requirements via recipes


## Contributing

Contributions welcome! This project is in active development.

1. Check [PLAN.md](PLAN.md) for current priorities
2. Create an issue for discussion
3. Submit a pull request

## Credits

**Built with:**
- [GeoPandas](https://geopandas.org/) - Spatial data handling
- [Shapely](https://shapely.readthedocs.io/) - Geometry operations
- [httpx](https://www.python-httpx.org/) - Async HTTP client
- [Typer](https://typer.tiangolo.com/) - CLI framework
- [Pydantic](https://docs.pydantic.dev/) - Data validation

**Data sources:**
- [PDOK](https://www.pdok.nl/) - Dutch government spatial data platform
- [Nominatim](https://nominatim.org/) - OpenStreetMap geocoding

## License

MIT License - See [LICENSE](LICENSE)

---

**Made by A190**

*Simple recipes for Dutch spatial data*
