"""Unit tests for OutputManager."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import geopandas as gpd
import pytest
from shapely.geometry import Point

from giskit.core.output import OutputManager
from giskit.core.recipe import Dataset, Location, LocationType, Output, OutputFormat, Recipe


class TestOutputManager:
    """Tests for OutputManager class."""

    @pytest.fixture
    def sample_recipe_gpkg(self, tmp_path):
        """Create a sample recipe with GPKG output."""
        return Recipe(
            name="Test Recipe",
            description="Test description",
            location=Location(
                type=LocationType.BBOX,
                value=[4.8, 52.3, 4.9, 52.4],
                crs="EPSG:4326",
                radius=None,
            ),
            datasets=[Dataset(provider="test", service="test_service")],
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
    def sample_layers(self):
        """Create sample layers for testing."""
        return {
            "layer1": gpd.GeoDataFrame(
                {"name": ["a", "b"], "_provider": ["test", "test"]},
                geometry=[Point(0, 0), Point(1, 1)],
                crs="EPSG:28992",
            ),
            "layer2": gpd.GeoDataFrame(
                {"name": ["c"], "_layer": ["test"]},
                geometry=[Point(2, 2)],
                crs="EPSG:28992",
            ),
        }

    def test_clean_internal_columns(self, sample_layers):
        """Test removal of internal columns."""
        gdf = sample_layers["layer1"]
        cleaned = OutputManager._clean_internal_columns(gdf)

        assert "_provider" not in cleaned.columns
        assert "name" in cleaned.columns
        assert len(cleaned) == 2

    def test_save_gpkg(self, sample_recipe_gpkg, sample_layers, tmp_path):
        """Test saving to GeoPackage format."""
        manager = OutputManager(sample_recipe_gpkg, tmp_path)
        output_path = manager.save_layers(sample_layers)

        assert output_path.exists()
        assert output_path.suffix == ".gpkg"

        # Verify layers were saved
        saved_layer1 = gpd.read_file(output_path, layer="layer1")
        assert len(saved_layer1) == 2
        assert "_provider" not in saved_layer1.columns

    def test_save_geojson(self, tmp_path, sample_layers):
        """Test saving to GeoJSON format."""
        recipe = Recipe(
            name="Test",
            description=None,
            location=Location(
                type=LocationType.BBOX,
                value=[4.8, 52.3, 4.9, 52.4],
                crs="EPSG:4326",
                radius=None,
            ),
            datasets=[Dataset(provider="test", service="test_service")],
            output=Output(
                path=tmp_path / "output.geojson",
                format=OutputFormat.GEOJSON,
                crs="EPSG:28992",
                overwrite=True,
                layer_prefix=None,
                ifc_export=None,
            ),
        )
        manager = OutputManager(recipe, tmp_path)
        output_path = manager.save_layers(sample_layers)

        assert output_path.exists()
        assert output_path.suffix == ".geojson"

        # Verify data was saved (combined layers)
        saved = gpd.read_file(output_path)
        assert len(saved) == 3  # 2 from layer1 + 1 from layer2

    def test_save_shapefile(self, tmp_path, sample_layers):
        """Test saving to Shapefile format."""
        recipe = Recipe(
            name="Test",
            description=None,
            location=Location(
                type=LocationType.BBOX,
                value=[4.8, 52.3, 4.9, 52.4],
                crs="EPSG:4326",
                radius=None,
            ),
            datasets=[Dataset(provider="test", service="test_service")],
            output=Output(
                path=tmp_path / "output.shp",
                format=OutputFormat.SHAPEFILE,
                crs="EPSG:28992",
                overwrite=True,
                layer_prefix=None,
                ifc_export=None,
            ),
        )
        manager = OutputManager(recipe, tmp_path)
        output_path = manager.save_layers(sample_layers)

        assert output_path.exists()
        assert output_path.suffix == ".shp"

    def test_save_flatgeobuf(self, tmp_path, sample_layers):
        """Test saving to FlatGeobuf format."""
        recipe = Recipe(
            name="Test",
            description=None,
            location=Location(
                type=LocationType.BBOX,
                value=[4.8, 52.3, 4.9, 52.4],
                crs="EPSG:4326",
                radius=None,
            ),
            datasets=[Dataset(provider="test", service="test_service")],
            output=Output(
                path=tmp_path / "output.fgb",
                format=OutputFormat.FLATGEOBUF,
                crs="EPSG:28992",
                overwrite=True,
                layer_prefix=None,
                ifc_export=None,
            ),
        )
        manager = OutputManager(recipe, tmp_path)
        output_path = manager.save_layers(sample_layers)

        assert output_path.exists()
        assert output_path.suffix == ".fgb"

    def test_save_unsupported_format(self, tmp_path, sample_layers):
        """Test that unsupported format raises error."""
        # Create recipe with invalid format by mocking
        recipe = Recipe(
            name="Test",
            description=None,
            location=Location(
                type=LocationType.BBOX,
                value=[4.8, 52.3, 4.9, 52.4],
                crs="EPSG:4326",
                radius=None,
            ),
            datasets=[Dataset(provider="test", service="test_service")],
            output=Output(
                path=tmp_path / "output.xyz",
                format=OutputFormat.GPKG,  # Set valid format initially
                crs="EPSG:28992",
                overwrite=True,
                layer_prefix=None,
                ifc_export=None,
            ),
        )
        # Mock the format value to test error handling
        recipe.output.format = MagicMock()
        recipe.output.format.value = "xyz"

        manager = OutputManager(recipe, tmp_path)

        with pytest.raises(ValueError, match="Unsupported output format"):
            manager.save_layers(sample_layers)

    def test_progress_callback(self, sample_recipe_gpkg, sample_layers, tmp_path):
        """Test progress callback is called."""
        messages = []

        def progress_callback(message: str, level: str):
            messages.append((message, level))

        manager = OutputManager(sample_recipe_gpkg, tmp_path)
        manager.save_layers(sample_layers, progress_callback)

        # Should have received at least one message
        assert len(messages) > 0
        # Should have success message
        assert any(level == "success" for _, level in messages)

    @patch("giskit.exporters.ifc.IFCExporter")
    def test_auto_export_ifc_not_configured(
        self, mock_ifc_exporter, sample_recipe_gpkg, sample_layers, tmp_path
    ):
        """Test that IFC auto-export is skipped when not configured."""
        manager = OutputManager(sample_recipe_gpkg, tmp_path)
        manager.save_layers(sample_layers)

        # IFCExporter should not be called (recipe has ifc_export=None)
        mock_ifc_exporter.assert_not_called()

    def test_relative_output_path(self, tmp_path, sample_layers):
        """Test that relative output paths are resolved correctly."""
        recipe = Recipe(
            name="Test",
            description=None,
            location=Location(
                type=LocationType.BBOX,
                value=[4.8, 52.3, 4.9, 52.4],
                crs="EPSG:4326",
                radius=None,
            ),
            datasets=[Dataset(provider="test", service="test_service")],
            output=Output(
                path=Path("relative/output.gpkg"),  # Relative path
                format=OutputFormat.GPKG,
                crs="EPSG:28992",
                overwrite=True,
                layer_prefix=None,
                ifc_export=None,
            ),
        )
        manager = OutputManager(recipe, tmp_path)
        output_path = manager.save_layers(sample_layers)

        # Should be resolved relative to recipe_dir
        assert output_path.is_absolute()
        assert output_path.parent.name == "relative"
