"""WFS (Web Feature Service) protocol implementation.

Supports WFS 2.0 for downloading vector features.
Used by PDOK services like BAG and BRK that don't support OGC API Features yet.
"""

from typing import Any, Optional

import geopandas as gpd
import httpx

from giskit.protocols.base import Protocol


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
                print(f"Warning: Failed to download {layer_name}: {e}")

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

        try:
            response = await client.get(self.base_url, params=params)
            response.raise_for_status()

            # Parse GeoJSON response
            geojson = response.json()

            # Convert to GeoDataFrame
            if "features" in geojson and geojson["features"]:
                gdf = gpd.GeoDataFrame.from_features(geojson["features"])
                gdf.set_crs(crs, inplace=True)
                return gdf
            else:
                return gpd.GeoDataFrame()

        except httpx.HTTPError as e:
            raise WFSError(f"Failed to download {layer_name}: {e}") from e

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
            "WFS protocol does not support raster coverage. " "Use WCS or WMTS protocol instead."
        )
