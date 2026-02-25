"""Unit tests for RecipeRunner."""

from unittest.mock import AsyncMock, MagicMock, patch

import geopandas as gpd
import pytest
from shapely.geometry import Point

from giskit.core.recipe import Dataset, Location, LocationType, Output, OutputFormat, Recipe
from giskit.core.runner import RecipeRunner


class TestRecipeRunner:
    """Tests for RecipeRunner class."""

    @pytest.fixture
    def sample_recipe(self, tmp_path):
        """Create a sample recipe for testing."""
        return Recipe(
            name="Test Recipe",
            description="Test description",
            location=Location(
                type=LocationType.BBOX,
                value=[4.8, 52.3, 4.9, 52.4],
                crs="EPSG:4326",
                radius=None,
            ),
            datasets=[
                Dataset(
                    provider="pdok",
                    service="bgt",
                    layers=["pand"],
                    query=None,
                    product=None,
                    resolution=None,
                    temporal=None,
                    colors=None,
                )
            ],
            output=Output(
                path=tmp_path / "output.gpkg",
                format=OutputFormat.GPKG,
                crs="EPSG:28992",
                overwrite=True,
                layer_prefix=None,
                ifc_export=None,
            ),
        )

    @pytest.fixture
    def runner(self, sample_recipe, tmp_path):
        """Create a RecipeRunner instance."""
        return RecipeRunner(sample_recipe, tmp_path)

    @pytest.mark.asyncio
    async def test_execute_basic(self, runner):
        """Test basic recipe execution."""
        # Mock the download to avoid actual API calls
        with patch("giskit.core.runner.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_gdf = gpd.GeoDataFrame(
                {"name": ["test"], "_layer": ["pand"]}, geometry=[Point(0, 0)], crs="EPSG:28992"
            )
            mock_provider.download_dataset = AsyncMock(return_value=mock_gdf)
            mock_get_provider.return_value = mock_provider

            result = await runner.execute()

            assert result is not None
            assert isinstance(result, dict)
            # Should have at least one layer
            assert len(result) > 0

    @pytest.mark.asyncio
    async def test_execute_with_progress_callback(self, runner):
        """Test execution with progress callback."""
        progress_messages = []

        def progress_callback(message: str, progress: float):
            progress_messages.append((message, progress))

        with patch("giskit.core.runner.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_gdf = gpd.GeoDataFrame(
                {"name": ["test"]}, geometry=[Point(0, 0)], crs="EPSG:28992"
            )
            mock_provider.download_dataset = AsyncMock(return_value=mock_gdf)
            mock_get_provider.return_value = mock_provider

            await runner.execute(progress_callback)

            # Should have received progress updates
            assert len(progress_messages) > 0
            # Final message should be complete
            assert progress_messages[-1] == ("Complete", 1.0)

    @pytest.mark.asyncio
    async def test_execute_no_data(self, runner):
        """Test execution when no data is downloaded."""
        with patch("giskit.core.runner.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            # Return empty GeoDataFrame
            mock_gdf = gpd.GeoDataFrame(geometry=[], crs="EPSG:28992")
            mock_provider.download_dataset = AsyncMock(return_value=mock_gdf)
            mock_get_provider.return_value = mock_provider

            result = await runner.execute()

            # Should return None when no data
            assert result is None

    def test_to_snake_case(self):
        """Test snake_case conversion."""
        assert RecipeRunner._to_snake_case("Perceel") == "perceel"
        assert RecipeRunner._to_snake_case("BuildingPart") == "building_part"
        assert RecipeRunner._to_snake_case("pand") == "pand"
        assert RecipeRunner._to_snake_case("camelCase") == "camel_case"
        assert RecipeRunner._to_snake_case("PascalCase") == "pascal_case"
        assert RecipeRunner._to_snake_case("HTTPServer") == "http_server"

    def test_normalize_layer_names_with_collection(self, runner):
        """Test layer name normalization with _collection column."""
        layers = {}
        gdf = gpd.GeoDataFrame(
            {"name": ["a", "b"], "_collection": ["BuildingPart", "BuildingPart"]},
            geometry=[Point(0, 0), Point(1, 1)],
            crs="EPSG:28992",
        )
        dataset = Dataset(
            provider="pdok",
            service="bgt",
            layers=None,
            query=None,
            product=None,
            resolution=None,
            temporal=None,
            colors=None,
        )

        runner._normalize_layer_names(layers, gdf, dataset)

        assert "bgt_building_part" in layers
        assert len(layers["bgt_building_part"]) == 2

    def test_normalize_layer_names_with_layer(self, runner):
        """Test layer name normalization with _layer column."""
        layers = {}
        gdf = gpd.GeoDataFrame(
            {"name": ["a"], "_layer": ["pand"]},
            geometry=[Point(0, 0)],
            crs="EPSG:28992",
        )
        dataset = Dataset(
            provider="pdok",
            service="bgt",
            layers=None,
            query=None,
            product=None,
            resolution=None,
            temporal=None,
            colors=None,
        )

        runner._normalize_layer_names(layers, gdf, dataset)

        assert "bgt_pand" in layers
        assert len(layers["bgt_pand"]) == 1

    def test_normalize_layer_names_single_layer(self, runner):
        """Test layer name normalization for single layer."""
        layers = {}
        gdf = gpd.GeoDataFrame({"name": ["a"]}, geometry=[Point(0, 0)], crs="EPSG:28992")
        dataset = Dataset(
            provider="pdok",
            service="bgt",
            layers=["pand"],
            query=None,
            product=None,
            resolution=None,
            temporal=None,
            colors=None,
        )

        runner._normalize_layer_names(layers, gdf, dataset)

        assert "bgt_pand" in layers
        assert len(layers["bgt_pand"]) == 1

    def test_normalize_layer_names_no_layers(self, runner):
        """Test layer name normalization when no layers specified."""
        layers = {}
        gdf = gpd.GeoDataFrame({"name": ["a"]}, geometry=[Point(0, 0)], crs="EPSG:28992")
        dataset = Dataset(
            provider="pdok",
            service="bgt",
            layers=None,
            query=None,
            product=None,
            resolution=None,
            temporal=None,
            colors=None,
        )

        runner._normalize_layer_names(layers, gdf, dataset)

        # Should use service name as layer name
        assert "bgt" in layers
        assert len(layers["bgt"]) == 1

    @pytest.mark.asyncio
    async def test_calculate_origin_point_bbox(self, runner):
        """Test origin point calculation for BBOX location."""
        bbox_output_crs = (100000, 400000, 110000, 410000)
        origin_x, origin_y = await runner._calculate_origin_point(bbox_output_crs)

        # Should be center of bbox
        assert origin_x == 105000
        assert origin_y == 405000

    @pytest.mark.asyncio
    async def test_calculate_origin_point_point(self, tmp_path):
        """Test origin point calculation for POINT location."""
        recipe = Recipe(
            name="Test",
            description=None,
            location=Location(
                type=LocationType.POINT,
                value=[4.9, 52.37],
                crs="EPSG:4326",
                radius=None,
            ),
            datasets=[],
            output=Output(
                path=tmp_path / "output.gpkg",
                format=OutputFormat.GPKG,
                crs="EPSG:28992",
                overwrite=True,
                layer_prefix=None,
                ifc_export=None,
            ),
        )
        runner = RecipeRunner(recipe, tmp_path)

        bbox_output_crs = (100000, 400000, 110000, 410000)
        origin_x, origin_y = await runner._calculate_origin_point(bbox_output_crs)

        # Should be transformed point coordinates
        assert isinstance(origin_x, (int, float))
        assert isinstance(origin_y, (int, float))

    def test_build_metadata_dict(self, runner):
        """Test metadata dictionary building."""
        bbox_output_crs = (100000, 400000, 110000, 410000)
        origin_x, origin_y = 105000, 405000

        metadata_dict = runner._build_metadata_dict(bbox_output_crs, origin_x, origin_y)

        assert metadata_dict["x"] == [origin_x]
        assert metadata_dict["y"] == [origin_y]
        assert metadata_dict["bbox_minx"] == [100000]
        assert metadata_dict["bbox_miny"] == [400000]
        assert metadata_dict["bbox_maxx"] == [110000]
        assert metadata_dict["bbox_maxy"] == [410000]
        assert metadata_dict["crs"] == ["EPSG:28992"]
        assert "download_date" in metadata_dict
        assert metadata_dict["bgt_layers"] == [["pand"]]

    def test_build_metadata_dict_many_bgt_layers(self, tmp_path):
        """Test metadata dict with many BGT layers."""
        # Create recipe with many BGT layers
        recipe = Recipe(
            name="Test",
            description=None,
            location=Location(
                type=LocationType.BBOX,
                value=[4.8, 52.3, 4.9, 52.4],
                crs="EPSG:4326",
                radius=None,
            ),
            datasets=[
                Dataset(
                    provider="pdok",
                    service="bgt",
                    layers=[f"layer{i}" for i in range(20)],  # Many layers
                    query=None,
                    product=None,
                    resolution=None,
                    temporal=None,
                    colors=None,
                )
            ],
            output=Output(
                path=tmp_path / "output.gpkg",
                format=OutputFormat.GPKG,
                crs="EPSG:28992",
                overwrite=True,
                layer_prefix=None,
                ifc_export=None,
            ),
        )
        runner = RecipeRunner(recipe, tmp_path)

        metadata_dict = runner._build_metadata_dict((0, 0, 1, 1), 0.5, 0.5)

        # Should use "all" for many layers
        assert metadata_dict["bgt_layers"] == ["all"]

    def test_build_metadata_dict_bag3d_lods(self, tmp_path):
        """Test metadata dict with BAG3D LOD levels."""
        recipe = Recipe(
            name="Test",
            description=None,
            location=Location(
                type=LocationType.BBOX,
                value=[4.8, 52.3, 4.9, 52.4],
                crs="EPSG:4326",
                radius=None,
            ),
            datasets=[
                Dataset(
                    provider="bag3d",
                    service="bag3d",
                    layers=["lod12", "lod22"],
                    query=None,
                    product=None,
                    resolution=None,
                    temporal=None,
                    colors=None,
                )
            ],
            output=Output(
                path=tmp_path / "output.gpkg",
                format=OutputFormat.GPKG,
                crs="EPSG:28992",
                overwrite=True,
                layer_prefix=None,
                ifc_export=None,
            ),
        )
        runner = RecipeRunner(recipe, tmp_path)

        metadata_dict = runner._build_metadata_dict((0, 0, 1, 1), 0.5, 0.5)

        # Should convert lod12 -> 1.2, lod22 -> 2.2
        assert metadata_dict["bag3d_lods"] == ["1.2,2.2"]
