"""CSV protocol for tabular data sources.

This protocol handles CSV files with optional geocoding support.
"""

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import geopandas as gpd
import httpx
import pandas as pd
from shapely.geometry import Point

logger = logging.getLogger(__name__)


class CSVProtocol:
    """Protocol for CSV data sources with geocoding."""

    protocol_name = "csv"

    def __init__(self, **kwargs):
        """Initialize CSV protocol.

        Args:
            **kwargs: Additional arguments
        """
        self.cache_dir = Path.home() / ".cache" / "giskit" / "csv"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def fetch(
        self,
        service_config: dict[str, Any],
        bbox: Optional[tuple] = None,
        point: Optional[tuple] = None,
        radius: Optional[float] = None,
        crs: str = "EPSG:28992",
        **kwargs,
    ) -> gpd.GeoDataFrame:
        """Fetch CSV data and optionally geocode it.

        Args:
            service_config: Service configuration containing:
                - url: CSV file URL
                - encoding: CSV encoding (default: utf-8)
                - delimiter: CSV delimiter (default: ,)
                - geocoding: Geocoding configuration (optional)
                    - address_template: Template for address string
                    - lat_column: Column containing latitude
                    - lon_column: Column containing longitude
                    - crs: Source CRS (default: EPSG:4326)
                - cache_hours: Cache duration in hours (default: 24)
            bbox: Bounding box (minx, miny, maxx, maxy) in target CRS
            point: Point (x, y) in target CRS
            radius: Radius in meters for point+radius queries
            crs: Target CRS (default: EPSG:28992)
            **kwargs: Additional query parameters

        Returns:
            GeoDataFrame with geocoded features
        """
        url = service_config["url"]
        encoding = service_config.get("encoding", "utf-8")
        delimiter = service_config.get("delimiter", ",")
        geocoding = service_config.get("geocoding", {})
        cache_hours = service_config.get("cache_hours", 24)

        # Download and parse CSV with caching
        df = await self._download_csv(url, encoding, delimiter, cache_hours)

        # Geocode if address template is provided
        if geocoding and "address_template" in geocoding:
            gdf = await self._geocode_dataframe(df, geocoding, crs)
        elif geocoding and "lat_column" in geocoding and "lon_column" in geocoding:
            # CSV already has coordinates
            lat_col = geocoding["lat_column"]
            lon_col = geocoding["lon_column"]
            source_crs = geocoding.get("crs", "EPSG:4326")

            # Create geometry from coordinates
            geometry_list = []
            for idx in df.index:
                try:
                    lon_val = float(df.at[idx, lon_col])
                    lat_val = float(df.at[idx, lat_col])
                    geometry_list.append(Point(lon_val, lat_val))
                except (ValueError, TypeError):
                    geometry_list.append(None)

            gdf = gpd.GeoDataFrame(df, geometry=geometry_list, crs=source_crs)
            gdf = gdf[gdf.geometry.notna()]

            # Transform to target CRS
            if source_crs != crs:
                gdf = gdf.to_crs(crs)
        else:
            # No geometry info, return empty GeoDataFrame
            gdf = gpd.GeoDataFrame(df, geometry=[], crs=crs)

        # Filter by bbox
        if bbox and len(gdf) > 0:
            minx, miny, maxx, maxy = bbox
            gdf = gdf.cx[minx:maxx, miny:maxy]

        # Filter by point+radius
        if point and radius and len(gdf) > 0:
            center = Point(point)
            gdf = gdf[gdf.distance(center) <= radius]

        return gdf

    async def _download_csv(
        self, url: str, encoding: str, delimiter: str, cache_hours: int
    ) -> pd.DataFrame:
        """Download CSV file with caching.

        Args:
            url: CSV file URL
            encoding: CSV encoding
            delimiter: CSV delimiter
            cache_hours: Cache duration in hours

        Returns:
            DataFrame with CSV data
        """
        # Generate cache key from URL
        cache_key = hashlib.md5(url.encode()).hexdigest()
        cache_file = self.cache_dir / f"{cache_key}.csv"
        cache_meta = self.cache_dir / f"{cache_key}.meta"

        # Check cache
        if cache_file.exists() and cache_meta.exists():
            meta = pd.read_json(cache_meta, typ="series")
            cached_at = pd.to_datetime(meta["cached_at"])
            expires_at = cached_at + pd.Timedelta(hours=cache_hours)

            if datetime.now(timezone.utc) < expires_at.tz_localize(timezone.utc):
                logger.info(f"Using cached CSV from {cache_file}")
                return pd.read_csv(cache_file, encoding=encoding, delimiter=delimiter)

        # Download CSV
        logger.info(f"Downloading CSV from {url}")
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.get(url)
            response.raise_for_status()

            # Save to cache
            cache_file.write_bytes(response.content)
            pd.Series({"cached_at": datetime.now(timezone.utc).isoformat(), "url": url}).to_json(
                cache_meta
            )

        # Parse CSV
        return pd.read_csv(cache_file, encoding=encoding, delimiter=delimiter)

    async def _geocode_dataframe(
        self, df: pd.DataFrame, geocoding_config: dict, target_crs: str
    ) -> gpd.GeoDataFrame:
        """Geocode addresses in dataframe using PDOK Locatieserver.

        Args:
            df: DataFrame with address data
            geocoding_config: Geocoding configuration
            target_crs: Target CRS

        Returns:
            GeoDataFrame with geocoded points
        """
        address_template = geocoding_config["address_template"]

        # Generate cache key for geocoded results
        cache_key = hashlib.md5((address_template + str(len(df))).encode()).hexdigest()
        cache_file = self.cache_dir / f"{cache_key}_geocoded.parquet"

        # Check cache
        if cache_file.exists():
            logger.info(f"Using cached geocoded data from {cache_file}")
            return gpd.read_parquet(cache_file)

        # Geocode each row
        logger.info(f"Geocoding {len(df)} addresses...")
        geometries = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            for idx, row in df.iterrows():
                # Build address string
                try:
                    address = address_template.format(**row.to_dict())
                except (KeyError, ValueError) as e:
                    logger.warning(f"Failed to build address for row {idx}: {e}")
                    geometries.append(None)
                    continue

                # Geocode using PDOK Locatieserver
                coords = await self._geocode_pdok(client, address)

                if coords:
                    geometries.append(Point(coords))
                else:
                    logger.warning(f"Failed to geocode: {address}")
                    geometries.append(None)

                # Progress logging
                row_num = int(idx) if isinstance(idx, (int, float)) else len(geometries)
                if row_num % 100 == 0:
                    logger.info(f"Geocoded {row_num}/{len(df)} addresses")

        # Create GeoDataFrame
        df_copy = df.copy()
        df_copy["geometry"] = geometries
        gdf = gpd.GeoDataFrame(df_copy, geometry="geometry", crs="EPSG:4326")

        # Remove rows with no geometry
        gdf = gdf[gdf.geometry.notna()]

        # Transform to target CRS
        if target_crs != "EPSG:4326":
            gdf = gdf.to_crs(target_crs)

        # Cache geocoded results
        gdf.to_parquet(cache_file)
        logger.info(f"Cached geocoded data to {cache_file}")

        return gdf

    async def _geocode_pdok(
        self, client: httpx.AsyncClient, address: str
    ) -> Optional[tuple[float, float]]:
        """Geocode address using PDOK Locatieserver.

        Args:
            client: HTTP client
            address: Address string

        Returns:
            (lon, lat) tuple in EPSG:4326, or None if geocoding failed
        """
        try:
            response = await client.get(
                "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free",
                params={"q": address, "rows": 1},
            )
            response.raise_for_status()
            data = response.json()

            if data["response"]["numFound"] > 0:
                doc = data["response"]["docs"][0]
                # Extract coordinates from centroide_ll "POINT(lon lat)"
                centroid = doc["centroide_ll"]
                coords_str = centroid.replace("POINT(", "").replace(")", "")
                lon, lat = map(float, coords_str.split())
                return (lon, lat)

        except Exception as e:
            logger.debug(f"Geocoding failed for '{address}': {e}")

        return None


# Register protocol factory
def _create_csv_protocol(config: dict[str, Any]) -> "CSVProtocol":
    """Factory function for creating CSV protocol instances.

    Args:
        config: Configuration dictionary (base_url not required for CSV)

    Returns:
        CSVProtocol instance
    """
    # CSV protocol takes URL from service config at fetch time
    return CSVProtocol()


# Register with global registry
from giskit.protocols.registry import register_protocol

register_protocol("csv", _create_csv_protocol)
