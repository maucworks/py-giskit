"""Raster result dataclass for carrying downloaded raster data through the pipeline.

Raster data (WMTS imagery, WCS elevation) follows a different path than vector data:
- Vector  → GeoDataFrame → OutputManager.save_layers()
- Raster  → RasterResult → OutputManager.save_raster_layers()

The RasterResult carries a PIL Image (always RGB), the georeferencing bbox in
both RD New (EPSG:28992) and WGS84, and the layer name used for file naming.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image


@dataclass
class RasterResult:
    """Carries a downloaded raster layer through the output pipeline.

    Attributes:
        layer_name: Unique name for this layer, used in output filenames
                    (e.g., "luchtfoto_actueel_25cm", "ahn_dtm").
        image: RGB PIL Image of the raster data.
               For elevation (WCS), this is a false-colour or greyscale
               visualisation derived from the raw numpy array.
        bbox_rd: Bounding box in RD New / EPSG:28992 as (minx, miny, maxx, maxy).
                 Used for GeoTIFF georeferencing and GLB plane placement.
        bbox_wgs84: Bounding box in WGS84 / EPSG:4326 as (minx, miny, maxx, maxy).
                    Informational; not used for file writing.
        source_crs: CRS string of bbox_rd (default "EPSG:28992").
    """

    layer_name: str
    image: "Image.Image"
    bbox_rd: tuple[float, float, float, float]
    bbox_wgs84: tuple[float, float, float, float]
    source_crs: str = field(default="EPSG:28992")

    # ------------------------------------------------------------------ #
    # Convenience properties                                               #
    # ------------------------------------------------------------------ #

    @property
    def width_m(self) -> float:
        """Width of the bbox in metres (RD units)."""
        return self.bbox_rd[2] - self.bbox_rd[0]

    @property
    def height_m(self) -> float:
        """Height of the bbox in metres (RD units)."""
        return self.bbox_rd[3] - self.bbox_rd[1]

    @property
    def pixel_size_x(self) -> float:
        """Horizontal pixel size in metres."""
        return self.width_m / self.image.width if self.image.width else 0.0

    @property
    def pixel_size_y(self) -> float:
        """Vertical pixel size in metres (positive, top-to-bottom)."""
        return self.height_m / self.image.height if self.image.height else 0.0
