"""WMTS (Web Map Tile Service) protocol implementation.

Supports downloading tiled imagery from WMTS services.
Specification: https://www.ogc.org/standards/wmts
"""

import io
from typing import Any, Optional, Tuple

import httpx
from PIL import Image

from giskit.protocols.base import Protocol


class WMTSError(Exception):
    """Raised when WMTS requests fail."""

    pass


class WMTSProtocol(Protocol):
    """WMTS protocol implementation for tile-based imagery downloads.

    Features:
    - Automatic zoom level calculation based on target resolution
    - Parallel tile downloading
    - Automatic tile stitching
    - Bounding box cropping
    - Support for multiple TileMatrixSets (EPSG codes)
    """

    def __init__(
        self,
        base_url: str,
        layer: str,
        tile_matrix_set: str = "EPSG:28992",
        timeout: float = 30.0,
        tile_size: int = 256,
        tile_format: str = "jpeg",
        **kwargs: Any,
    ):
        """Initialize WMTS protocol.

        Args:
            base_url: Base URL for WMTS service
            layer: Layer identifier (e.g., "Actueel_ortho25")
            tile_matrix_set: TileMatrixSet identifier (default: "EPSG:28992" for RD New)
            timeout: Request timeout in seconds
            tile_size: Tile size in pixels (default: 256)
            tile_format: Tile format (jpeg, png)
            **kwargs: Additional configuration
        """
        super().__init__(base_url, timeout=timeout, **kwargs)
        self.layer = layer
        self.tile_matrix_set = tile_matrix_set
        self.tile_size = tile_size
        self.tile_format = tile_format

        # Parse EPSG code from tile_matrix_set
        self.crs_code = (
            tile_matrix_set.split(":")[-1] if ":" in tile_matrix_set else tile_matrix_set
        )

        # Tile matrix configuration
        self._init_tile_matrix()

    def _init_tile_matrix(self) -> None:
        """Initialize tile matrix based on CRS.

        Currently supports EPSG:28992 (RD New - Netherlands).
        Other CRS can be added as needed.
        """
        if self.tile_matrix_set == "EPSG:28992":
            # RD New (Netherlands) tile matrix
            # From PDOK WMTS capabilities
            self.tile_origin_x = -285401.92
            self.tile_origin_y = 903401.92

            # Zoom levels 0-19 with resolutions (meters/pixel)
            self.tile_matrix = {
                0: {"res": 3440.64, "matrix_width": 1, "matrix_height": 1},
                1: {"res": 1720.32, "matrix_width": 2, "matrix_height": 2},
                2: {"res": 860.16, "matrix_width": 4, "matrix_height": 4},
                3: {"res": 430.08, "matrix_width": 8, "matrix_height": 8},
                4: {"res": 215.04, "matrix_width": 16, "matrix_height": 16},
                5: {"res": 107.52, "matrix_width": 32, "matrix_height": 32},
                6: {"res": 53.76, "matrix_width": 64, "matrix_height": 64},
                7: {"res": 26.88, "matrix_width": 128, "matrix_height": 128},
                8: {"res": 13.44, "matrix_width": 256, "matrix_height": 256},
                9: {"res": 6.72, "matrix_width": 512, "matrix_height": 512},
                10: {"res": 3.36, "matrix_width": 1024, "matrix_height": 1024},
                11: {"res": 1.68, "matrix_width": 2048, "matrix_height": 2048},
                12: {"res": 0.84, "matrix_width": 4096, "matrix_height": 4096},
                13: {"res": 0.42, "matrix_width": 8192, "matrix_height": 8192},
                14: {"res": 0.21, "matrix_width": 16384, "matrix_height": 16384},
                15: {"res": 0.105, "matrix_width": 32768, "matrix_height": 32768},
                16: {"res": 0.0525, "matrix_width": 65536, "matrix_height": 65536},
                17: {"res": 0.02625, "matrix_width": 131072, "matrix_height": 131072},
                18: {"res": 0.013125, "matrix_width": 262144, "matrix_height": 262144},
                19: {"res": 0.0065625, "matrix_width": 524288, "matrix_height": 524288},
            }
        else:
            raise NotImplementedError(
                f"TileMatrixSet {self.tile_matrix_set} not yet supported. "
                "Currently only EPSG:28992 is implemented."
            )

    async def get_capabilities(self) -> dict[str, Any]:
        """Get WMTS service capabilities.

        Returns:
            Dictionary with service metadata
        """
        # For now, return basic info from configuration
        # TODO: Parse actual GetCapabilities XML if needed
        return {
            "title": f"WMTS Service - {self.layer}",
            "layers": [self.layer],
            "tile_matrix_sets": [self.tile_matrix_set],
            "formats": [f"image/{self.tile_format}"],
            "zoom_levels": list(self.tile_matrix.keys()),
        }

    def calculate_zoom_level(
        self,
        bbox: Tuple[float, float, float, float],
        target_resolution: Optional[float] = None,
    ) -> int:
        """Calculate appropriate zoom level for target resolution.

        Args:
            bbox: Bounding box (minx, miny, maxx, maxy)
            target_resolution: Target ground resolution in meters/pixel
                              (None = auto-calculate from bbox size)

        Returns:
            Zoom level
        """
        if target_resolution is None:
            # Auto-calculate based on bbox size
            # Aim for ~2000 pixels on longest side
            minx, miny, maxx, maxy = bbox
            width = maxx - minx
            height = maxy - miny
            max_dim = max(width, height)
            target_resolution = max_dim / 2000

        # Find zoom level closest to target resolution
        best_zoom = 13  # Default
        min_diff = float("inf")

        for zoom, info in self.tile_matrix.items():
            diff = abs(info["res"] - target_resolution)
            if diff < min_diff:
                min_diff = diff
                best_zoom = zoom

        return best_zoom

    def coords_to_tile(self, x: float, y: float, zoom: int) -> Tuple[int, int]:
        """Convert coordinates to tile indices.

        Args:
            x: X coordinate in TileMatrixSet CRS
            y: Y coordinate in TileMatrixSet CRS
            zoom: Zoom level

        Returns:
            (tile_col, tile_row) indices
        """
        res = self.tile_matrix[zoom]["res"]

        # Calculate offset from origin
        dx = x - self.tile_origin_x
        dy = self.tile_origin_y - y  # Y increases downward in tile space

        # Convert to tile indices
        tile_col = int(dx / (self.tile_size * res))
        tile_row = int(dy / (self.tile_size * res))

        return tile_col, tile_row

    def tile_to_coords(self, tile_col: int, tile_row: int, zoom: int) -> Tuple[float, float]:
        """Convert tile indices to coordinates (top-left corner).

        Args:
            tile_col: Tile column index
            tile_row: Tile row index
            zoom: Zoom level

        Returns:
            (x, y) coordinates of tile's top-left corner
        """
        res = self.tile_matrix[zoom]["res"]

        x = self.tile_origin_x + tile_col * self.tile_size * res
        y = self.tile_origin_y - tile_row * self.tile_size * res

        return x, y

    def get_tile_url(self, zoom: int, tile_col: int, tile_row: int) -> str:
        """Construct WMTS tile URL.

        Args:
            zoom: Zoom level
            tile_col: Tile column index
            tile_row: Tile row index

        Returns:
            WMTS tile URL
        """
        # RESTful URL template:
        # {base_url}/{layer}/{TileMatrixSet}/{zoom}/{col}/{row}.{format}
        return (
            f"{self.base_url}/{self.layer}/{self.tile_matrix_set}/"
            f"{zoom:02d}/{tile_col}/{tile_row}.{self.tile_format}"
        )

    async def download_tile(self, zoom: int, tile_col: int, tile_row: int) -> Optional[Image.Image]:
        """Download a single tile.

        Args:
            zoom: Zoom level
            tile_col: Tile column
            tile_row: Tile row

        Returns:
            PIL Image or None if download failed
        """
        url = self.get_tile_url(zoom, tile_col, tile_row)

        try:
            response = await self._http_get(url)

            # Load image from bytes
            img = Image.open(io.BytesIO(response.content))
            return img

        except WMTSError:
            # Tile might not exist (outside coverage area)
            return None

    async def get_features(
        self,
        bbox: tuple[float, float, float, float],
        layers: Optional[list[str]] = None,
        crs: str = "EPSG:4326",
        limit: Optional[int] = None,
        **kwargs: Any,
    ):
        """WMTS does not support vector features.

        Raises:
            NotImplementedError: WMTS is raster-only
        """
        raise NotImplementedError(
            "WMTS protocol does not support vector features. Use get_coverage() for raster imagery."
        )

    async def get_coverage(
        self,
        bbox: tuple[float, float, float, float],
        product: str,
        resolution: float,
        crs: str = "EPSG:28992",
        zoom: Optional[int] = None,
        progress_callback: Optional[Any] = None,
        **kwargs: Any,
    ) -> Image.Image:
        """Download raster imagery for bounding box.

        Args:
            bbox: Bounding box (minx, miny, maxx, maxy) in TileMatrixSet CRS
            product: Product/layer name (ignored - uses configured layer)
            resolution: Target resolution in meters/pixel (used for zoom calculation)
            crs: Coordinate reference system (must match TileMatrixSet)
            zoom: Explicit zoom level (overrides resolution-based calculation)
            progress_callback: Optional callback(message, percent)
            **kwargs: Additional parameters

        Returns:
            PIL Image with aerial imagery
        """
        self.validate_bbox(bbox)
        minx, miny, maxx, maxy = bbox

        # Validate CRS matches TileMatrixSet
        if crs != self.tile_matrix_set:
            raise ValueError(
                f"CRS {crs} does not match TileMatrixSet {self.tile_matrix_set}. "
                "Coordinate transformation not yet implemented."
            )

        # Determine zoom level
        if zoom is None:
            zoom = self.calculate_zoom_level(bbox, target_resolution=resolution)

        if progress_callback:
            res = self.tile_matrix[zoom]["res"]
            progress_callback(f"Using zoom level {zoom} (resolution: {res:.3f}m/px)", 0.0)

        # Calculate tile range
        min_col, max_row = self.coords_to_tile(minx, miny, zoom)  # bottom-left
        max_col, min_row = self.coords_to_tile(maxx, maxy, zoom)  # top-right

        cols = range(min_col, max_col + 1)
        rows = range(min_row, max_row + 1)
        total_tiles = len(cols) * len(rows)

        if progress_callback:
            progress_callback(f"Downloading {len(cols)}x{len(rows)} = {total_tiles} tiles", 0.1)

        # Download tiles in parallel
        tiles = {}
        downloaded = 0

        # Download tiles sequentially for now
        # TODO: Add parallel downloading with asyncio.gather
        for row in rows:
            for col in cols:
                tile_img = await self.download_tile(zoom, col, row)

                if tile_img:
                    tiles[(col, row)] = tile_img
                    downloaded += 1

                if progress_callback:
                    percent = 0.1 + 0.7 * (downloaded / total_tiles)
                    progress_callback(f"Downloaded {downloaded}/{total_tiles} tiles", percent)

        if not tiles:
            raise WMTSError("No tiles downloaded - area might be outside coverage")

        if progress_callback:
            progress_callback("Stitching tiles together...", 0.8)

        # Stitch tiles into single image
        width = len(cols) * self.tile_size
        height = len(rows) * self.tile_size
        result = Image.new("RGB", (width, height))

        for (col, row), tile_img in tiles.items():
            x = (col - min_col) * self.tile_size
            y = (row - min_row) * self.tile_size
            result.paste(tile_img, (x, y))

        # Crop to exact bbox
        res = self.tile_matrix[zoom]["res"]

        # Calculate pixel offsets for exact bbox
        tile_min_x, tile_max_y = self.tile_to_coords(min_col, min_row, zoom)

        left_px = int((minx - tile_min_x) / res)
        top_px = int((tile_max_y - maxy) / res)
        right_px = int((maxx - tile_min_x) / res)
        bottom_px = int((tile_max_y - miny) / res)

        # Ensure we don't exceed image bounds
        left_px = max(0, left_px)
        top_px = max(0, top_px)
        right_px = min(width, right_px)
        bottom_px = min(height, bottom_px)

        result = result.crop((left_px, top_px, right_px, bottom_px))

        if progress_callback:
            progress_callback(f"Final image: {result.width}x{result.height} pixels", 0.9)

        return result

    def _wrap_http_error(self, error: httpx.HTTPError, method: str, url: str) -> Exception:
        """Wrap HTTP error in WMTSError.

        Args:
            error: Original HTTP error
            method: HTTP method (GET, POST, etc.)
            url: URL that was requested

        Returns:
            WMTSError with descriptive message
        """
        return WMTSError(f"Failed to {method} {url}: {error}")


# Register protocol factory
def _create_wmts_protocol(config: dict[str, Any]) -> "WMTSProtocol":
    """Factory function for creating WMTS protocol instances.

    Args:
        config: Configuration dictionary with keys:
            - url: Base URL for the WMTS service
            - layer: Layer name (required)
            - tile_matrix_set: TileMatrixSet identifier (optional, default: EPSG:28992)
            - tile_format: Image format (optional, default: jpeg)

    Returns:
        WMTSProtocol instance

    Raises:
        ValueError: If required 'layer' parameter is missing
    """
    url = config.get("url", "")
    layer = config.get("layer")

    if not layer:
        raise ValueError("WMTS protocol requires 'layer' parameter in config")

    tile_matrix_set = config.get("tile_matrix_set", "EPSG:28992")
    tile_format = config.get("tile_format", "jpeg")

    return WMTSProtocol(
        base_url=url, layer=layer, tile_matrix_set=tile_matrix_set, tile_format=tile_format
    )


# Register with global registry
from giskit.protocols.registry import register_protocol

register_protocol("wmts", _create_wmts_protocol)
