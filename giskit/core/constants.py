"""Constants used throughout the giskit codebase.

This module centralizes magic numbers and configuration values that are used
across multiple modules, improving maintainability and code clarity.
"""

# BGT (Basisregistratie Grootschalige Topografie) Constants
# ============================================================

# If requesting more than this many BGT layers, assume user wants "all" layers
BGT_ALL_LAYERS_THRESHOLD = 40

# OGC Features API Constants
# ===========================

# Default limit for features per page when paginating through API results
OGC_FEATURES_DEFAULT_LIMIT = 100

# Default maximum number of features to request in a single API call
# Used when API doesn't specify its own limit
OGC_FEATURES_DEFAULT_MAX_FEATURES = 1000

# Spatial Query Grid Walking Constants
# ======================================

# Grid cell size in meters when splitting large area queries
# Used to prevent timeouts on large bounding boxes
DEFAULT_GRID_CELL_SIZE_M = 250.0

# Minimum area (in square meters) before grid walking is triggered
# 0.25 km² = 500m × 500m
# Areas larger than this will be split into grid cells
MIN_GRID_WALKING_AREA_M2 = 250_000

# WMTS (Web Map Tile Service) Constants
# =======================================

# Default resolution in meters per pixel for WMTS imagery
WMTS_DEFAULT_RESOLUTION_M = 0.25  # 25cm per pixel

# WCS (Web Coverage Service) Constants
# =====================================

# Default resolution in meters for WCS coverage downloads
WCS_DEFAULT_RESOLUTION_M = 0.5  # 50cm

# Geocoding Constants
# ===================

# Default search radius in meters for address geocoding
DEFAULT_GEOCODING_RADIUS_M = 500

# Maximum allowed radius for location queries (50km)
# Prevents accidentally querying entire countries
MAX_LOCATION_RADIUS_M = 50_000

# IFC Export Constants
# ====================

# Default IFC schema version for exports
DEFAULT_IFC_VERSION = "IFC4X3_ADD2"

# Whether to normalize Z coordinates to ground level by default
# True: Ground level = 0, False: Use absolute NAP elevations
DEFAULT_IFC_NORMALIZE_Z = True

# HTTP Client Constants
# ======================

# Default timeout for HTTP requests in seconds
HTTP_DEFAULT_TIMEOUT_S = 120

# Maximum number of retries for failed HTTP requests
HTTP_MAX_RETRIES = 3

# Time to wait between retry attempts in seconds
HTTP_RETRY_DELAY_S = 1.0

# File Export Constants
# =====================

# Default JPEG quality for exported aerial imagery
JPEG_EXPORT_QUALITY = 90

# Whether to optimize JPEG files (slower but smaller)
JPEG_OPTIMIZE = True

# PNG optimization level (0-9, higher = slower but smaller)
PNG_OPTIMIZE_LEVEL = 6
