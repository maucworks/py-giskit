"""Recipe execution engine - core business logic for running recipes."""

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Union

import geopandas as gpd
from shapely.geometry import Point, Polygon

from giskit.core.constants import BGT_ALL_LAYERS_THRESHOLD
from giskit.core.geocoding import geocode
from giskit.core.raster import RasterResult
from giskit.core.recipe import Dataset, Location, LocationType, Recipe
from giskit.core.spatial import transform_bbox, transform_point
from giskit.providers.base import get_provider

logger = logging.getLogger(__name__)


class RecipeRunner:
    """Executes recipes to download and process spatial data.

    The RecipeRunner handles the core business logic of recipe execution,
    including downloading datasets, normalizing layer names, adding metadata,
    and managing the overall execution flow.

    This class is separate from CLI concerns, making it testable and reusable
    from other contexts (e.g., web services, notebooks).
    """

    def __init__(self, recipe: Recipe, recipe_dir: Path):
        """Initialize the RecipeRunner.

        Args:
            recipe: Recipe to execute
            recipe_dir: Directory containing the recipe file (for resolving relative paths)
        """
        self.recipe = recipe
        self.recipe_dir = recipe_dir

    async def execute(
        self, progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> Optional[tuple[dict[str, gpd.GeoDataFrame], dict[str, RasterResult]]]:
        """Execute the recipe and return downloaded data as layers.

        Args:
            progress_callback: Optional callback function(message: str, progress: float)
                             Called to report progress (0.0 to 1.0)

        Returns:
            Tuple of (vector_layers, raster_layers), or None if no data downloaded.
            - vector_layers: dict mapping layer names to GeoDataFrames
            - raster_layers: dict mapping layer names to RasterResults
        """
        # Calculate bounding box
        if progress_callback:
            progress_callback("Calculating bounding box...", 0.0)

        bbox = await self.recipe.get_bbox_wgs84()
        logger.debug(f"BBox (WGS84): {bbox}")

        # Download datasets — split into vector and raster
        layers, raster_layers = await self._download_datasets(bbox, progress_callback)

        # Add metadata layer if we have vector data and output format is gpkg
        if layers and self.recipe.output.format.value == "gpkg":
            if progress_callback:
                progress_callback("Adding metadata layer...", 0.95)

            metadata_gdf = await self._add_metadata_layer(bbox)
            layers["_metadata"] = metadata_gdf

        if progress_callback:
            progress_callback("Complete", 1.0)

        if not layers and not raster_layers:
            return None
        return layers, raster_layers

    async def _download_datasets(
        self,
        bbox: tuple[float, float, float, float],
        progress_callback: Optional[Callable[[str, float], None]] = None,
    ) -> tuple[dict[str, gpd.GeoDataFrame], dict[str, RasterResult]]:
        """Download all datasets specified in the recipe in parallel.

        Args:
            bbox: Bounding box in WGS84 (minx, miny, maxx, maxy)
            progress_callback: Optional progress callback

        Returns:
            Tuple of (vector_layers, raster_layers)
        """
        layers: dict[str, gpd.GeoDataFrame] = {}
        raster_layers: dict[str, RasterResult] = {}

        # Convert bbox to Location for compatibility
        bbox_location = Location(
            type=LocationType.BBOX, value=list(bbox), crs="EPSG:4326", radius=None
        )

        # Resolve output path
        output_path = self.recipe.output.path
        if not output_path.is_absolute():
            output_path = self.recipe_dir / output_path

        total_datasets = len(self.recipe.datasets)
        completed_count = 0
        lock = asyncio.Lock()

        async def _download_one(
            dataset: Dataset,
        ) -> tuple[str, Union[gpd.GeoDataFrame, RasterResult, None]]:
            """Download a single dataset and return (provider_label, result_or_None)."""
            provider = get_provider(dataset.provider)
            label = dataset.provider
            try:
                result = await provider.download_dataset(
                    dataset=dataset,
                    location=bbox_location,
                    output_path=output_path,
                    output_crs=self.recipe.output.crs,
                )
                return label, result
            except Exception as e:
                logger.error(f"Failed to download {label}: {e}", exc_info=True)
                return label, None

        async def _tracked_download(
            dataset: Dataset,
        ) -> tuple[str, Union[gpd.GeoDataFrame, RasterResult, None]]:
            """Wrap download with progress reporting."""
            nonlocal completed_count
            result = await _download_one(dataset)
            async with lock:
                completed_count += 1
                progress = completed_count / total_datasets * 0.9
                if progress_callback:
                    progress_callback(
                        f"Completed {completed_count}/{total_datasets} datasets", progress
                    )
            return result

        if progress_callback:
            progress_callback(f"Downloading {total_datasets} datasets in parallel...", 0.0)

        # Launch all downloads concurrently
        results = await asyncio.gather(
            *(_tracked_download(dataset) for dataset in self.recipe.datasets)
        )

        # Collect results in recipe order — split raster and vector
        for (label, result), dataset in zip(results, self.recipe.datasets, strict=False):
            if result is None:
                continue
            if isinstance(result, RasterResult):
                logger.info(f"Downloaded raster layer '{result.layer_name}' from {label}")
                raster_layers[result.layer_name] = result
            elif isinstance(result, gpd.GeoDataFrame):
                if not result.empty:
                    logger.info(f"Downloaded {len(result)} features from {label}")
                    self._normalize_layer_names(layers, result, dataset)
                else:
                    logger.warning(f"No features found for {label}")

        return layers, raster_layers

    def _normalize_layer_names(
        self,
        layers: dict[str, gpd.GeoDataFrame],
        gdf: gpd.GeoDataFrame,
        dataset: Dataset,
    ) -> None:
        """Normalize layer names and add to layers dictionary.

        Handles multi-layer datasets (with _collection or _layer columns) and
        single-layer datasets. Converts layer names to snake_case for consistency.

        Args:
            layers: Dictionary to add layers to (modified in-place)
            gdf: GeoDataFrame with downloaded data
            dataset: Dataset specification
        """
        service = dataset.service or dataset.provider

        # Check if gdf has collection/layer information (from multi-layer downloads)
        if "_collection" in gdf.columns:
            # Split by collection/layer
            for collection_name in gdf["_collection"].unique():
                layer_gdf = gdf[gdf["_collection"] == collection_name].copy()
                # Normalize collection name to snake_case
                normalized_name = self._to_snake_case(collection_name)
                full_layer_name = f"{service}_{normalized_name}"
                layers[full_layer_name] = layer_gdf

        elif "_layer" in gdf.columns:
            # Alternative layer column name
            for layer_name in gdf["_layer"].unique():
                layer_gdf = gdf[gdf["_layer"] == layer_name].copy()
                # Normalize layer name to snake_case
                normalized_name = self._to_snake_case(layer_name)
                full_layer_name = f"{service}_{normalized_name}"
                layers[full_layer_name] = layer_gdf

        else:
            # Single layer - use service name or first layer from request
            if dataset.layers and len(dataset.layers) == 1:
                layer_name = f"{service}_{dataset.layers[0]}"
            else:
                layer_name = service
            layers[layer_name] = gdf

    @staticmethod
    def _to_snake_case(name: str) -> str:
        """Convert string to snake_case.

        Converts PascalCase/camelCase to snake_case for consistency.

        Examples:
            Perceel -> perceel
            BuildingPart -> building_part
            pand -> pand (already lowercase)

        Args:
            name: String to convert

        Returns:
            snake_case version of the string
        """
        # Insert underscore before uppercase letters (but not at start)
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        # Insert underscore before uppercase letters that follow lowercase
        s2 = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1)
        # Convert to lowercase
        return s2.lower()

    async def _add_metadata_layer(
        self, bbox: tuple[float, float, float, float]
    ) -> gpd.GeoDataFrame:
        """Create metadata layer with recipe execution information.

        The metadata layer contains information about the download location,
        bounding box, CRS, datasets, and other execution details. This is
        compatible with Sitedb schema.

        Args:
            bbox: Bounding box in WGS84 (minx, miny, maxx, maxy)

        Returns:
            GeoDataFrame with single point geometry and metadata attributes
        """
        # Transform bbox to output CRS
        bbox_output_crs = transform_bbox(bbox, "EPSG:4326", self.recipe.output.crs)

        # Calculate origin point based on location type
        origin_x, origin_y = await self._calculate_origin_point(bbox_output_crs)

        # Build metadata dictionary
        metadata_dict = self._build_metadata_dict(bbox_output_crs, origin_x, origin_y)

        # Create metadata GeoDataFrame
        metadata_gdf = gpd.GeoDataFrame(
            metadata_dict, geometry=[Point(origin_x, origin_y)], crs=self.recipe.output.crs
        )

        return metadata_gdf

    async def _calculate_origin_point(
        self, bbox_output_crs: tuple[float, float, float, float]
    ) -> tuple[float, float]:
        """Calculate the origin point based on location type.

        The origin point is the point that will be at (0,0,0) in IFC exports.
        It varies based on location type:
        - POINT: exact coordinates specified
        - ADDRESS: geocoded address coordinates
        - BBOX: center of bbox
        - POLYGON: centroid of polygon

        Args:
            bbox_output_crs: Bounding box in output CRS (minx, miny, maxx, maxy)

        Returns:
            Tuple of (x, y) coordinates in output CRS
        """
        location = self.recipe.location

        if location.type == LocationType.POINT:
            # Point location - use the exact coordinates specified
            point_coords: list = location.value  # type: ignore
            lon, lat = float(point_coords[0]), float(point_coords[1])
            # Transform from location CRS to output CRS
            origin_x, origin_y = transform_point(lon, lat, location.crs, self.recipe.output.crs)

        elif location.type == LocationType.ADDRESS:
            # Address location - geocode to get the point, then transform
            address_str: str = location.value  # type: ignore
            lon, lat = await geocode(address_str)
            origin_x, origin_y = transform_point(lon, lat, "EPSG:4326", self.recipe.output.crs)

        elif location.type == LocationType.BBOX:
            # Bbox location - use center of bbox
            origin_x = (bbox_output_crs[0] + bbox_output_crs[2]) / 2
            origin_y = (bbox_output_crs[1] + bbox_output_crs[3]) / 2

        elif location.type == LocationType.POLYGON:
            # Polygon location - use 2D centroid
            poly_coords: list = location.value  # type: ignore
            polygon = Polygon(poly_coords)
            centroid = polygon.centroid
            # Transform centroid from location CRS to output CRS
            origin_x, origin_y = transform_point(
                centroid.x, centroid.y, location.crs, self.recipe.output.crs
            )

        else:
            # Fallback to bbox center
            origin_x = (bbox_output_crs[0] + bbox_output_crs[2]) / 2
            origin_y = (bbox_output_crs[1] + bbox_output_crs[3]) / 2

        return origin_x, origin_y

    def _build_metadata_dict(
        self, bbox_output_crs: tuple[float, float, float, float], origin_x: float, origin_y: float
    ) -> dict[str, list[Any]]:
        """Build metadata dictionary with recipe execution information.

        The metadata format matches Sitedb schema for compatibility.

        Args:
            bbox_output_crs: Bounding box in output CRS (minx, miny, maxx, maxy)
            origin_x: Origin point X coordinate
            origin_y: Origin point Y coordinate

        Returns:
            Dictionary with metadata fields (all values are single-element lists)
        """
        location = self.recipe.location

        # Build metadata dict - exact column order matching Sitedb
        metadata_dict = {
            "address": [None],
            "x": [origin_x],
            "y": [origin_y],
            "radius": [None],
            "bbox_minx": [bbox_output_crs[0]],
            "bbox_miny": [bbox_output_crs[1]],
            "bbox_maxx": [bbox_output_crs[2]],
            "bbox_maxy": [bbox_output_crs[3]],
            "download_date": [datetime.now().isoformat()],
            "crs": [self.recipe.output.crs],
            "grid_size": [None],  # For raster data, optional
            "bgt_layers": [None],  # Which BGT layers were requested
            "bag3d_lods": [None],  # Which BAG3D LOD levels were requested
        }

        # Add location-specific fields
        if location.type == LocationType.ADDRESS:
            metadata_dict["address"] = [location.value]
            if location.radius is not None:
                metadata_dict["radius"] = [location.radius]
        elif location.type == LocationType.POINT:
            if location.radius is not None:
                metadata_dict["radius"] = [location.radius]

        # Extract dataset-specific metadata for traceability
        bgt_layers_list = []
        bag3d_lods_list = []

        for dataset in self.recipe.datasets:
            service = dataset.service or dataset.provider

            # Track BGT layers
            if service == "bgt" and dataset.layers:
                bgt_layers_list.extend(dataset.layers)

            # Track BAG3D LOD levels
            elif service == "bag3d" and dataset.layers:
                # Extract LOD levels (lod12 -> 1.2, lod13 -> 1.3, lod22 -> 2.2)
                for layer in dataset.layers:
                    if layer.startswith("lod"):
                        # Convert lod12 -> 1.2
                        lod_num = layer[3:]  # "12", "13", "22"
                        if len(lod_num) == 2:
                            lod_formatted = f"{lod_num[0]}.{lod_num[1]}"
                            bag3d_lods_list.append(lod_formatted)

            # Track grid_size if resolution is specified (for raster data)
            if dataset.resolution is not None:
                metadata_dict["grid_size"] = [dataset.resolution]

        # Store BGT layers (or "all" if many layers)
        if bgt_layers_list:
            # Sitedb uses "all" if all BGT layers are included
            if len(bgt_layers_list) > BGT_ALL_LAYERS_THRESHOLD:
                metadata_dict["bgt_layers"] = ["all"]
            else:
                metadata_dict["bgt_layers"] = [",".join(sorted(bgt_layers_list))]

        # Store BAG3D LOD levels
        if bag3d_lods_list:
            metadata_dict["bag3d_lods"] = [",".join(sorted(bag3d_lods_list))]

        return metadata_dict
