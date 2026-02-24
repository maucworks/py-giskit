"""OGC API Features protocol implementation.

Supports OGC API - Features (formerly WFS 3.0).
Specification: https://ogcapi.ogc.org/features/
"""

import logging
from typing import Any, Optional
from urllib.parse import urljoin

import geopandas as gpd
import httpx

from giskit.core.constants import (
    DEFAULT_GRID_CELL_SIZE_M,
    MIN_GRID_WALKING_AREA_M2,
    OGC_FEATURES_DEFAULT_LIMIT,
)
from giskit.protocols.base import Protocol
from giskit.protocols.quirks import ProtocolQuirks

logger = logging.getLogger(__name__)


class OGCFeaturesError(Exception):
    """Raised when OGC Features API requests fail."""

    pass


class OGCFeaturesProtocol(Protocol):
    """OGC API Features protocol implementation with quirk support."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        max_features_per_request: int = OGC_FEATURES_DEFAULT_LIMIT,
        quirks: Optional[ProtocolQuirks] = None,
        **kwargs: Any,
    ):
        """Initialize OGC Features protocol.

        Args:
            base_url: Base URL for OGC Features endpoint
            timeout: Request timeout in seconds
            max_features_per_request: Maximum features per request
            quirks: Protocol quirks configuration (None = no quirks)
            **kwargs: Additional configuration
        """
        # Apply quirks to base URL before passing to parent
        self.quirks = quirks or ProtocolQuirks()
        base_url = self.quirks.apply_to_url(base_url)

        # Initialize parent with timeout
        super().__init__(base_url, timeout=timeout, **kwargs)

        # Override timeout with quirks if specified
        self.timeout = self.quirks.get_timeout(timeout)
        self.max_features_per_request = max_features_per_request

    async def get_capabilities(self) -> dict[str, Any]:
        """Get service capabilities from collections endpoint.

        Returns:
            Dictionary with service metadata
        """
        client = await self._get_client()

        try:
            # Build request params with quirks applied
            params = self.quirks.apply_to_params({})

            # Get collections list
            response = await client.get(urljoin(self.base_url, "collections"), params=params)
            response.raise_for_status()
            data = response.json()

            collections = data.get("collections", [])

            # Extract layer names and metadata
            layers = []
            for coll in collections:
                layers.append(
                    {
                        "id": coll.get("id"),
                        "title": coll.get("title"),
                        "description": coll.get("description"),
                        "extent": coll.get("extent"),
                    }
                )

            return {
                "title": data.get("title", "Unknown"),
                "layers": [layer["id"] for layer in layers],
                "layer_details": layers,
                "crs": ["EPSG:4326"],  # OGC Features always supports WGS84
                "formats": ["application/geo+json"],
            }

        except httpx.HTTPError as e:
            raise OGCFeaturesError(f"Failed to get capabilities: {e}") from e

    async def get_features(
        self,
        bbox: tuple[float, float, float, float],
        layers: Optional[list[str]] = None,
        crs: str = "EPSG:4326",
        limit: Optional[int] = None,
        temporal: str = "latest",
        **kwargs: Any,
    ) -> gpd.GeoDataFrame:
        """Download vector features within bounding box.

        Args:
            bbox: (minx, miny, maxx, maxy) in EPSG:4326 (OGC Features requirement)
            layers: Collection IDs to download (None = all)
            crs: Target CRS (output will be reprojected)
            limit: Maximum features per collection
            temporal: Temporal filter strategy:
                - 'latest': Keep newest version per feature (default)
                - 'active': Only currently valid/active features
                - 'all': All historical versions
                - ISO date (e.g. '2024-01-01'): Features valid at that date
            **kwargs: Additional query parameters

        Returns:
            GeoDataFrame with downloaded features
        """
        self.validate_bbox(bbox)
        client = await self._get_client()

        # Get available collections if not specified
        if layers is None:
            capabilities = await self.get_capabilities()
            layers = capabilities["layers"]

        if not layers:
            # Return empty GeoDataFrame
            return gpd.GeoDataFrame()

        # Transform bbox if quirk specifies different CRS
        request_bbox = bbox
        bbox_crs_str = "EPSG:4326"
        if self.quirks.bbox_crs:
            bbox_crs = self.quirks.bbox_crs
            if bbox_crs != "EPSG:4326":
                from pyproj import Transformer

                transformer = Transformer.from_crs("EPSG:4326", bbox_crs, always_xy=True)
                minx, miny = transformer.transform(bbox[0], bbox[1])
                maxx, maxy = transformer.transform(bbox[2], bbox[3])
                request_bbox = (minx, miny, maxx, maxy)
                bbox_crs_str = bbox_crs

        # Check if we need grid walking for large areas
        # Grid walking splits large bbox into smaller cells to:
        # 1. Avoid timeouts on slow APIs
        # 2. Work around strict API feature limits
        # 3. Provide better progress feedback
        use_grid_walking = False
        grid_cell_size = None

        if self.quirks.max_features_limit and bbox_crs_str in ("EPSG:28992", "EPSG:3857"):
            # For APIs with low feature limits, use grid walking for large areas
            # Calculate approximate area and expected feature density
            width = request_bbox[2] - request_bbox[0]
            height = request_bbox[3] - request_bbox[1]
            area = width * height  # in square meters for metric CRS

            # Use grid walking if area exceeds threshold
            # This helps especially for BAG3D which has max 100 features per request
            if area > MIN_GRID_WALKING_AREA_M2:
                use_grid_walking = True
                grid_cell_size = DEFAULT_GRID_CELL_SIZE_M

        # Download each collection
        all_gdfs = []
        for collection_id in layers:
            try:
                if use_grid_walking and grid_cell_size:
                    gdf = await self._download_collection_with_grid(
                        client,
                        collection_id,
                        request_bbox,
                        grid_cell_size,
                        bbox_crs_str,
                        limit,
                        temporal,
                        max_concurrent=self.quirks.max_concurrent_cells,
                        **kwargs,
                    )
                else:
                    gdf = await self._download_collection(
                        client, collection_id, request_bbox, limit, temporal, **kwargs
                    )
                if not gdf.empty:
                    # Add source collection column
                    gdf["_collection"] = collection_id
                    all_gdfs.append(gdf)
            except Exception as e:
                # Log error but continue with other collections
                logger.warning(f"Failed to download {collection_id}: {e}")

        if not all_gdfs:
            # Return empty GeoDataFrame
            return gpd.GeoDataFrame()

        # Combine all collections
        combined = gpd.GeoDataFrame(gpd.pd.concat(all_gdfs, ignore_index=True))

        # Reproject if needed
        if crs != "EPSG:4326" and not combined.empty:
            combined = combined.to_crs(crs)

        return combined

    async def _download_collection_with_grid(
        self,
        client: httpx.AsyncClient,
        collection_id: str,
        bbox: tuple[float, float, float, float],
        grid_cell_size: float,
        bbox_crs: str,
        limit: Optional[int],
        temporal: str = "latest",
        max_concurrent: int = 5,
        **kwargs: Any,
    ) -> gpd.GeoDataFrame:
        """Download a collection using grid walking to split large areas into smaller cells.

        This method:
        1. Subdivides the bbox into grid cells of specified size
        2. Downloads cells concurrently (max 5 at a time by default)
        3. Deduplicates features that appear in multiple cells
        4. Shows progress for each cell

        Args:
            client: HTTP client
            collection_id: Collection ID (may include LOD prefix like "lod22")
            bbox: Bounding box in bbox_crs coordinates
            grid_cell_size: Size of grid cells in CRS units (e.g., 250 meters)
            bbox_crs: CRS of the bbox (e.g., "EPSG:28992")
            limit: Feature limit (total, not per cell)
            temporal: Temporal filter strategy
            max_concurrent: Maximum concurrent downloads (default: 5)
            **kwargs: Additional parameters

        Returns:
            GeoDataFrame with deduplicated features from all cells
        """
        import asyncio

        from giskit.core.spatial import subdivide_bbox

        # Subdivide bbox into grid cells
        cells = subdivide_bbox(bbox, grid_cell_size, crs=bbox_crs)
        logger.info(f"Splitting area into {len(cells)} grid cells ({grid_cell_size}m each)...")
        logger.info(f"Downloading with max {max_concurrent} concurrent requests...")

        # Download cells in batches to limit concurrency
        all_gdfs = []
        seen_ids = set()  # For deduplication
        total_features = 0

        # Process cells in batches
        for batch_start in range(0, len(cells), max_concurrent):
            batch_end = min(batch_start + max_concurrent, len(cells))
            batch_cells = cells[batch_start:batch_end]
            batch_indices = list(range(batch_start + 1, batch_end + 1))

            logger.debug(
                f"Processing batch: cells {batch_indices[0]}-{batch_indices[-1]} of {len(cells)}..."
            )

            # Download all cells in this batch concurrently
            async def download_cell(cell_bbox: tuple, cell_idx: int):
                """Download a single cell with retry logic"""
                max_retries = 3
                base_delay = 2.0  # seconds

                for attempt in range(max_retries):
                    try:
                        gdf = await self._download_collection(
                            client,
                            collection_id,
                            cell_bbox,
                            limit=None,
                            temporal=temporal,
                            **kwargs,
                        )
                        return (cell_idx, gdf, None)
                    except Exception as e:
                        error_msg = str(e)
                        # Check if it's a retryable error (timeout, 504, 503, connection errors)
                        is_retryable = any(
                            keyword in error_msg.lower()
                            for keyword in ["timeout", "504", "503", "connection", "temporary"]
                        )

                        if attempt < max_retries - 1 and is_retryable:
                            # Exponential backoff: 2s, 4s, 8s
                            delay = base_delay * (2**attempt)
                            logger.debug(
                                f"Cell {cell_idx}: Retry {attempt + 1}/{max_retries} after {delay}s (error: {error_msg})"
                            )
                            await asyncio.sleep(delay)
                        else:
                            return (cell_idx, None, error_msg)

                # Should never reach here, but just in case
                return (cell_idx, None, "Max retries exceeded")

            # Launch concurrent downloads for this batch
            # Create tasks first (don't await yet!)
            tasks = [
                asyncio.create_task(download_cell(cell_bbox, cell_idx))
                for cell_bbox, cell_idx in zip(batch_cells, batch_indices, strict=False)
            ]

            # Now await all tasks concurrently
            results = await asyncio.gather(*tasks)

            # Process results from this batch
            for cell_idx, gdf, error in results:
                if error:
                    logger.warning(f"Cell {cell_idx}/{len(cells)}: Failed - {error}")
                    continue

                if gdf is None or gdf.empty:
                    logger.debug(f"Cell {cell_idx}/{len(cells)}: 0 features")
                    continue

                # Deduplicate features based on 'identificatie' or index
                if "identificatie" in gdf.columns:
                    # Filter out features we've already seen
                    new_mask = ~gdf["identificatie"].isin(seen_ids)
                    gdf = gdf[new_mask]
                    seen_ids.update(gdf["identificatie"])

                if not gdf.empty:
                    all_gdfs.append(gdf)
                    cell_count = len(gdf)
                    total_features += cell_count
                    logger.info(
                        f"Cell {cell_idx}/{len(cells)}: {cell_count:,} features ({total_features:,} total)",
                    )
                else:
                    logger.debug(f"Cell {cell_idx}/{len(cells)}: 0 new features (all duplicates)")

            # Check if we've reached the limit
            if limit and total_features >= limit:
                logger.info(f"Reached limit of {limit:,} features, stopping...")
                break

        if not all_gdfs:
            return gpd.GeoDataFrame()

        # Combine all cells
        combined = gpd.GeoDataFrame(gpd.pd.concat(all_gdfs, ignore_index=True))

        # Apply limit if needed
        if limit and len(combined) > limit:
            combined = combined.head(limit)

        logger.info(f"Grid walking complete: {len(combined):,} unique features downloaded")

        return combined

    async def _download_collection(
        self,
        client: httpx.AsyncClient,
        collection_id: str,
        bbox: tuple[float, float, float, float],
        limit: Optional[int],
        temporal: str = "latest",
        **kwargs: Any,
    ) -> gpd.GeoDataFrame:
        """Download a single collection with pagination support.

        Args:
            client: HTTP client
            collection_id: Collection ID (may include LOD prefix like "lod22")
            bbox: Bounding box
            limit: Feature limit (total, not per page)
            temporal: Temporal filter strategy ('latest', 'active', 'all', or ISO date)
            **kwargs: Additional parameters

        Returns:
            GeoDataFrame with features
        """
        # For BAG3D: map lod* layers to "pand" collection
        # The LOD info is kept in collection_id for later parsing
        actual_collection_id = collection_id
        if collection_id.startswith("lod"):
            actual_collection_id = "pand"  # BAG3D only has "pand" collection

        url = urljoin(self.base_url, f"collections/{actual_collection_id}/items")

        # Build query parameters with quirks applied
        # Use smaller page size for pagination
        # If API has max_features_limit quirk, respect it
        default_page_limit = 1000
        if self.quirks.max_features_limit:
            page_limit = self.quirks.max_features_limit
        else:
            page_limit = min(limit or self.max_features_per_request, default_page_limit)

        params = {
            "bbox": ",".join(map(str, bbox)),
            "limit": page_limit,
            **kwargs,
        }

        # Add bbox-crs parameter to explicitly specify CRS of bbox coordinates
        # OGC API Features spec recommends always including this for clarity
        # However, some APIs (like BAG3D) don't support this parameter
        if not self.quirks.omit_bbox_crs_param:
            if self.quirks.bbox_crs and self.quirks.bbox_crs != "EPSG:4326":
                # Bbox was transformed to RD or other CRS - specify the transformed CRS
                params[
                    "bbox-crs"
                ] = f"http://www.opengis.net/def/crs/EPSG/0/{self.quirks.bbox_crs.split(':')[1]}"
            else:
                # Using WGS84 - explicitly specify CRS84 (OGC standard for WGS84 lon/lat)
                params["bbox-crs"] = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"

        params = self.quirks.apply_to_params(params)

        all_gdfs = []
        total_features = 0
        next_url = None
        page_num = 1

        try:
            # Download first page
            response = await client.get(url, params=params)
            response.raise_for_status()
            geojson = response.json()

            # Check if we know total count for progress indicator
            total_matched = geojson.get("numberMatched")
            if total_matched:
                logger.info(
                    f"Downloading {total_matched:,} features (max {page_limit} per page)..."
                )

            # Determine format from first response
            is_cityjson = False
            lod = "0"

            if "features" in geojson and geojson["features"]:
                first_feature = geojson["features"][0]
                if "CityObjects" in first_feature:
                    is_cityjson = True
                    # Extract LOD for CityJSON
                    if collection_id.startswith("lod"):
                        lod_num = collection_id[3:]
                        if len(lod_num) == 2:
                            lod = f"{lod_num[0]}.{lod_num[1]}"

            # Process all pages
            while True:
                if "features" not in geojson or not geojson["features"]:
                    break

                # Parse this page
                if is_cityjson:
                    from giskit.protocols.cityjson import cityjson_to_geodataframe

                    gdf = cityjson_to_geodataframe(geojson, lod=lod)
                    if not gdf.empty:
                        gdf.set_crs("EPSG:28992", inplace=True)
                else:
                    gdf = gpd.GeoDataFrame.from_features(geojson["features"])
                    gdf.set_crs("EPSG:4326", inplace=True)

                if not gdf.empty:
                    all_gdfs.append(gdf)
                    total_features += len(gdf)

                    # Show progress
                    if total_matched:
                        progress_pct = (total_features / total_matched) * 100
                        logger.info(
                            f"Progress: {total_features:,}/{total_matched:,} ({progress_pct:.0f}%) - page {page_num}",
                        )
                    else:
                        logger.info(
                            f"Downloaded {total_features:,} features (page {page_num})",
                        )

                # Check if we've reached the limit
                if limit and total_features >= limit:
                    break

                # Check for next page link
                next_url = None
                if "links" in geojson:
                    for link in geojson["links"]:
                        if link.get("rel") == "next":
                            next_url = link.get("href")
                            break

                if not next_url:
                    break  # No more pages

                # Fetch next page
                page_num += 1
                response = await client.get(next_url)
                response.raise_for_status()
                geojson = response.json()

            # Combine all pages
            if not all_gdfs:
                return gpd.GeoDataFrame()

            combined = gpd.GeoDataFrame(gpd.pd.concat(all_gdfs, ignore_index=True))

            # Apply temporal filtering based on strategy
            combined = self._apply_temporal_filter(combined, temporal)

            # Apply limit if specified
            if limit and len(combined) > limit:
                combined = combined.iloc[:limit]

            return combined

        except httpx.HTTPError as e:
            raise OGCFeaturesError(f"Failed to download collection {collection_id}: {e}") from e

    def _apply_temporal_filter(
        self, gdf: gpd.GeoDataFrame, temporal: str = "latest"
    ) -> gpd.GeoDataFrame:
        """Apply temporal filtering to remove historical duplicates.

        Args:
            gdf: GeoDataFrame with potentially duplicate historical features
            temporal: Temporal filter strategy:
                - 'latest': Keep newest version per feature (default)
                - 'active': Only currently valid/active features
                - 'all': Keep all historical versions (no filtering)
                - ISO date (e.g. '2024-01-01'): Features valid at that date

        Returns:
            Filtered GeoDataFrame
        """
        if temporal == "all" or gdf.empty:
            return gdf

        # Determine ID field for deduplication
        id_field = None
        if "lokaal_id" in gdf.columns:
            id_field = "lokaal_id"  # BGT data
        elif "identificatie" in gdf.columns:
            id_field = "identificatie"  # BAG/BRK data
        else:
            # No known ID field - return as-is
            return gdf

        if temporal == "active":
            # Filter to only active/valid features (no termination date or future termination)
            if "termination_date" in gdf.columns:
                # Keep features where termination_date is null or in the future
                from datetime import datetime

                now = datetime.now().isoformat() + "Z"
                gdf = gdf[
                    (gdf["termination_date"].isna())
                    | (gdf["termination_date"] == "")
                    | (gdf["termination_date"] > now)
                ]
            # If no termination_date field, fall back to 'latest' behavior
            temporal = "latest"

        if temporal == "latest":
            # First, filter out terminated features (with eind_registratie)
            # These are historical versions that have been replaced, even if they have different IDs
            if "eind_registratie" in gdf.columns:
                # Remove features that have been terminated
                before_count = len(gdf)
                gdf = gdf[gdf["eind_registratie"].isna() | (gdf["eind_registratie"] == "")]
                after_count = len(gdf)
                if before_count != after_count:
                    logger.info(
                        f"Filtered out {before_count - after_count} terminated features (eind_registratie)"
                    )

            # Then, keep newest version per feature ID (for true duplicates with same ID)
            if "tijdstip_registratie" in gdf.columns:
                # Sort by timestamp descending, keep first (newest) per ID
                gdf = gdf.sort_values("tijdstip_registratie", ascending=False)
                gdf = gdf.drop_duplicates(subset=id_field, keep="first")
            elif "version" in gdf.columns:
                # Fallback to version field
                gdf = gdf.sort_values("version", ascending=False)
                gdf = gdf.drop_duplicates(subset=id_field, keep="first")
            else:
                # No timestamp - just keep first occurrence
                gdf = gdf.drop_duplicates(subset=id_field, keep="first")

        elif temporal.count("-") == 2:  # Looks like ISO date (YYYY-MM-DD)
            # Filter to features valid at specific date
            try:
                from datetime import datetime

                target_date = datetime.fromisoformat(temporal.replace("Z", ""))
                target_iso = target_date.isoformat() + "Z"

                # Keep features where:
                # - tijdstip_registratie <= target_date
                # - AND (termination_date is null OR termination_date > target_date)
                if "tijdstip_registratie" in gdf.columns:
                    gdf = gdf[gdf["tijdstip_registratie"] <= target_iso]

                if "termination_date" in gdf.columns:
                    gdf = gdf[
                        (gdf["termination_date"].isna())
                        | (gdf["termination_date"] == "")
                        | (gdf["termination_date"] > target_iso)
                    ]

                # Then keep only the latest version per ID before or at target date
                if "tijdstip_registratie" in gdf.columns:
                    gdf = gdf.sort_values("tijdstip_registratie", ascending=False)
                    gdf = gdf.drop_duplicates(subset=id_field, keep="first")

            except (ValueError, AttributeError):
                # Invalid date format - fall back to 'latest'
                logger.warning(f"Invalid temporal date '{temporal}', using 'latest' instead")
                return self._apply_temporal_filter(gdf, "latest")

        return gdf

    async def get_coverage(
        self,
        bbox: tuple[float, float, float, float],
        product: str,
        resolution: int,
        crs: str = "EPSG:4326",
        **kwargs: Any,
    ) -> Any:
        """OGC Features does not support raster coverage.

        Raises:
            NotImplementedError: OGC Features is vector-only
        """
        raise NotImplementedError(
            "OGC Features protocol does not support raster coverage. "
            "Use OGC Coverages or WMTS protocol instead."
        )


# Register protocol factory
def _create_ogc_features_protocol(config: dict[str, Any]) -> OGCFeaturesProtocol:
    """Factory function for creating OGC Features protocol instances.

    Args:
        config: Configuration dictionary with keys:
            - url: Base URL for the service
            - service_id: Service identifier for quirks lookup (optional)
            - provider_name: Provider name for quirks lookup (optional)
            - quirks: Pre-constructed quirks object (optional)

    Returns:
        OGCFeaturesProtocol instance
    """
    from giskit.protocols.quirks import get_service_quirks

    url = config.get("url", "")
    service_id = config.get("service_id")
    provider_name = config.get("provider_name", "pdok")

    # Get or use provided quirks
    if "quirks" in config:
        quirks = config["quirks"]
    elif service_id:
        quirks = get_service_quirks(provider_name, "ogc-features", service_id)
    else:
        # No quirks - try to infer from URL or config
        fallback_id = config.get("title", "").split(" - ")[0].lower()
        if not fallback_id and url:
            fallback_id = url.split("/")[-2]
        if fallback_id:
            quirks = get_service_quirks(provider_name, "ogc-features", fallback_id)
        else:
            quirks = None

    return OGCFeaturesProtocol(base_url=url, quirks=quirks)


# Register with global registry
from giskit.protocols.registry import register_protocol

register_protocol("ogc-features", _create_ogc_features_protocol)
