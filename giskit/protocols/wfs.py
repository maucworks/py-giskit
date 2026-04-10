"""WFS (Web Feature Service) protocol implementation.

Supports WFS 2.0 for downloading vector features.
Used by PDOK services like BAG and BRK that don't support OGC API Features yet.
"""

import logging
from typing import Any, Optional

import geopandas as gpd
import httpx

from giskit.protocols.base import Protocol

logger = logging.getLogger(__name__)


class WFSError(Exception):
    """Raised when WFS requests fail."""

    pass


class WFSProtocol(Protocol):
    """WFS 2.0 protocol implementation."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 120.0,
        max_features: int = 10000,
        **kwargs: Any,
    ):
        """Initialize WFS protocol.

        Args:
            base_url: Base URL for WFS endpoint
            timeout: Request timeout in seconds
            max_features: Maximum features per request
            **kwargs: Additional configuration
        """
        super().__init__(base_url, timeout=timeout, **kwargs)
        self.max_features = max_features

    async def get_capabilities(self) -> dict[str, Any]:
        """Get WFS capabilities.

        Returns:
            Dictionary with service metadata
        """
        # For now, return basic info
        return {
            "type": "wfs",
            "version": "2.0.0",
            "url": self.base_url,
        }

    async def get_features(
        self,
        bbox: tuple[float, float, float, float],
        layers: Optional[list[str]] = None,
        crs: str = "EPSG:28992",
        limit: Optional[int] = None,
        **kwargs: Any,
    ) -> gpd.GeoDataFrame:
        """Download vector features within bounding box.

        Args:
            bbox: (minx, miny, maxx, maxy) in WGS84 (EPSG:4326)
            layers: Layer names to download (WFS typeNames)
            crs: Target CRS for output and WFS query
            limit: Maximum features per layer
            **kwargs: Additional query parameters (can include bbox_crs to override input CRS)

        Returns:
            GeoDataFrame with downloaded features
        """
        if not layers:
            return gpd.GeoDataFrame()

        # Transform bbox from WGS84 to target CRS if needed
        bbox_crs = kwargs.get("bbox_crs", "EPSG:4326")
        if bbox_crs != crs:
            from giskit.core.spatial import transform_bbox

            bbox_transformed = transform_bbox(bbox, bbox_crs, crs)
        else:
            bbox_transformed = bbox

        client = await self._get_client()
        all_gdfs = []

        for layer_name in layers:
            try:
                gdf = await self._download_layer(
                    client, layer_name, bbox_transformed, crs, limit or self.max_features
                )
                if not gdf.empty:
                    # Add layer name for identification
                    gdf["_collection"] = layer_name.split(":")[-1]  # Remove namespace
                    all_gdfs.append(gdf)
            except Exception as e:
                logger.warning(f"Failed to download {layer_name}: {e}")

        if not all_gdfs:
            return gpd.GeoDataFrame()

        # Combine all layers
        combined = gpd.GeoDataFrame(gpd.pd.concat(all_gdfs, ignore_index=True))
        combined.set_crs(crs, inplace=True)
        return combined

    async def _download_layer(
        self,
        client: httpx.AsyncClient,
        layer_name: str,
        bbox: tuple[float, float, float, float],
        crs: str,
        limit: int,
    ) -> gpd.GeoDataFrame:
        """Download a single WFS layer.

        Args:
            client: HTTP client
            layer_name: Layer/typeName to download
            bbox: Bounding box in target CRS
            crs: Target CRS
            limit: Feature limit

        Returns:
            GeoDataFrame with features
        """
        # Build WFS GetFeature request
        # WFS 2.0 spec: bbox should include CRS: minx,miny,maxx,maxy,CRS
        bbox_str = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]},{crs}"
        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeName": layer_name,
            "outputFormat": "json",
            "srsName": crs,
            "bbox": bbox_str,
            "count": limit,
        }

        response = await self._http_get(self.base_url, params=params)

        # Parse GeoJSON response
        geojson = response.json()

        # Convert to GeoDataFrame
        if "features" in geojson and geojson["features"]:
            gdf = gpd.GeoDataFrame.from_features(geojson["features"])
            gdf.set_crs(crs, inplace=True)
            return gdf
        else:
            return gpd.GeoDataFrame()

    async def get_coverage(
        self,
        bbox: tuple[float, float, float, float],
        product: str,
        resolution: int,
        crs: str = "EPSG:4326",
        **kwargs: Any,
    ) -> Any:
        """WFS does not support raster coverage.

        Raises:
            NotImplementedError: WFS is vector-only
        """
        raise NotImplementedError(
            "WFS protocol does not support raster coverage. Use WCS or WMTS protocol instead."
        )

    def _wrap_http_error(self, error: httpx.HTTPError, method: str, url: str) -> Exception:
        """Wrap HTTP error in WFSError.

        Args:
            error: Original HTTP error
            method: HTTP method (GET, POST, etc.)
            url: URL that was requested

        Returns:
            WFSError with descriptive message
        """
        return WFSError(f"Failed to {method} {url}: {error}")


# Register protocol factory
def _create_wfs_protocol(config: dict[str, Any]) -> "WFSProtocol":
    """Factory function for creating WFS protocol instances.

    Args:
        config: Configuration dictionary with keys:
            - url: Base URL for the WFS service

    Returns:
        WFSProtocol instance
    """
    return WFSProtocol(config.get("url", ""))


# Register with global registry
from giskit.protocols.registry import register_protocol

register_protocol("wfs", _create_wfs_protocol)
