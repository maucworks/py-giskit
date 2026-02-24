"""GTFS (General Transit Feed Specification) protocol handler.

Downloads and parses GTFS feeds for public transport data.
Focuses on stops/stations with geographic coordinates.
"""

import io
import zipfile
from pathlib import Path
from typing import Any, Optional

import geopandas as gpd
import httpx
import pandas as pd
from shapely.geometry import Point

from giskit.protocols.base import Protocol


class GTFSProtocol(Protocol):
    """GTFS protocol for public transport data.

    GTFS (General Transit Feed Specification) is a standard format for
    public transportation schedules and geographic information.

    Key files we use:
    - stops.txt: Station/stop locations with lat/lon coordinates
    - routes.txt: Transit routes (bus, tram, train, etc.)
    - trips.txt: Individual trips

    See: https://gtfs.org/
    """

    def __init__(
        self,
        base_url: str,
        cache_dir: Optional[Path] = None,
        cache_days: int = 1,
        timeout: float = 300.0,
        **kwargs: Any,
    ):
        """Initialize GTFS protocol.

        Args:
            base_url: URL to GTFS zip file
            cache_dir: Directory to cache downloaded GTFS data
            cache_days: Number of days to cache data (default: 1)
            timeout: Download timeout in seconds (default: 300 = 5 min)
            **kwargs: Additional configuration
        """
        super().__init__(base_url, timeout, **kwargs)
        self.cache_dir = cache_dir or Path.home() / ".cache" / "giskit" / "gtfs"
        self.cache_days = cache_days
        self._gtfs_data: Optional[dict[str, pd.DataFrame]] = None

    async def _download_gtfs(self) -> bytes:
        """Download GTFS zip file.

        Returns:
            Raw zip file bytes
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(self.base_url)
            response.raise_for_status()
            return response.content

    def _parse_gtfs_zip(self, zip_bytes: bytes) -> dict[str, pd.DataFrame]:
        """Parse GTFS zip file into dataframes.

        Args:
            zip_bytes: Raw zip file data

        Returns:
            Dictionary mapping filename to DataFrame:
            {
                "stops": DataFrame,
                "routes": DataFrame,
                "trips": DataFrame,
                ...
            }
        """
        data = {}

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            # Parse relevant GTFS files
            for filename in ["stops.txt", "routes.txt", "trips.txt"]:
                if filename in zf.namelist():
                    with zf.open(filename) as f:
                        # Read as text with BOM handling
                        content = f.read().decode("utf-8-sig")
                        df = pd.read_csv(io.StringIO(content))
                        # Store without .txt extension
                        data[filename.replace(".txt", "")] = df

        return data

    async def _load_gtfs_data(self) -> dict[str, pd.DataFrame]:
        """Load GTFS data (cached or fresh download).

        Returns:
            Dictionary of GTFS dataframes
        """
        if self._gtfs_data is not None:
            return self._gtfs_data

        # Check cache
        cache_file = self.cache_dir / f"{hash(self.base_url)}.zip"

        if cache_file.exists():
            # Check if cache is fresh
            import time

            age_days = (time.time() - cache_file.stat().st_mtime) / (24 * 3600)

            if age_days < self.cache_days:
                # Use cached data
                with open(cache_file, "rb") as f:
                    zip_bytes = f.read()
                self._gtfs_data = self._parse_gtfs_zip(zip_bytes)
                return self._gtfs_data

        # Download fresh data
        zip_bytes = await self._download_gtfs()

        # Save to cache
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(zip_bytes)

        # Parse and cache in memory
        self._gtfs_data = self._parse_gtfs_zip(zip_bytes)
        return self._gtfs_data

    async def get_capabilities(self) -> dict[str, Any]:
        """Get GTFS feed capabilities.

        Returns:
            Service metadata including available stops count
        """
        data = await self._load_gtfs_data()
        stops = data.get("stops", pd.DataFrame())

        return {
            "title": "GTFS Public Transport Feed",
            "layers": ["stops"],
            "crs": ["EPSG:4326"],
            "formats": ["geojson"],
            "stop_count": len(stops),
            "bbox": self._calculate_bbox(stops) if not stops.empty else None,
        }

    def _calculate_bbox(self, stops: pd.DataFrame) -> list[float]:
        """Calculate bounding box from stops.

        Args:
            stops: DataFrame with stop_lon and stop_lat columns

        Returns:
            [minx, miny, maxx, maxy]
        """
        if "stop_lon" not in stops.columns or "stop_lat" not in stops.columns:
            return [0, 0, 0, 0]

        return [
            float(stops["stop_lon"].min()),
            float(stops["stop_lat"].min()),
            float(stops["stop_lon"].max()),
            float(stops["stop_lat"].max()),
        ]

    async def get_features(
        self,
        bbox: tuple[float, float, float, float],
        layers: Optional[list[str]] = None,
        crs: str = "EPSG:4326",
        limit: Optional[int] = None,
        **kwargs: Any,
    ) -> gpd.GeoDataFrame:
        """Download GTFS stops within bounding box.

        Args:
            bbox: (minx, miny, maxx, maxy) in WGS84 (EPSG:4326)
            layers: Not used for GTFS (only "stops" available)
            crs: Target CRS for output (default: EPSG:4326)
            limit: Maximum number of stops to return
            **kwargs: Additional parameters (stop_type filter, etc.)

        Returns:
            GeoDataFrame with stops in specified CRS
        """
        data = await self._load_gtfs_data()
        stops = data.get("stops", pd.DataFrame())

        if stops.empty:
            return gpd.GeoDataFrame()

        # Ensure required columns exist
        if "stop_lon" not in stops.columns or "stop_lat" not in stops.columns:
            raise ValueError("GTFS stops.txt missing stop_lon or stop_lat columns")

        # Filter by bbox (in WGS84)
        minx, miny, maxx, maxy = bbox
        mask = (
            (stops["stop_lon"] >= minx)
            & (stops["stop_lon"] <= maxx)
            & (stops["stop_lat"] >= miny)
            & (stops["stop_lat"] <= maxy)
        )
        filtered = stops[mask].copy()

        # Apply limit
        if limit is not None:
            filtered = filtered.head(limit)

        # Create geometry from coordinates
        geometry = [
            Point(lon, lat)
            for lon, lat in zip(filtered["stop_lon"], filtered["stop_lat"], strict=False)
        ]

        # Create GeoDataFrame
        gdf = gpd.GeoDataFrame(filtered, geometry=geometry, crs="EPSG:4326")

        # Transform to target CRS if needed
        if crs != "EPSG:4326":
            gdf = gdf.to_crs(crs)

        return gdf

    async def get_coverage(
        self,
        bbox: tuple[float, float, float, float],
        product: str,
        resolution: int,
        crs: str = "EPSG:4326",
        **kwargs: Any,
    ) -> Any:
        """Not implemented for GTFS (vector data only)."""
        raise NotImplementedError("GTFS protocol only supports vector data (stops)")


# Register protocol factory
def _create_gtfs_protocol(config: dict[str, Any]) -> "GTFSProtocol":
    """Factory function for creating GTFS protocol instances.

    Args:
        config: Configuration dictionary (base_url not required for GTFS)

    Returns:
        GTFSProtocol instance
    """
    # GTFS protocol takes base_url from service config at fetch time
    return GTFSProtocol(base_url=config.get("url", ""))


# Register with global registry
from giskit.protocols.registry import register_protocol

register_protocol("gtfs", _create_gtfs_protocol)


__all__ = ["GTFSProtocol"]
