"""Unit tests for the raster pipeline.

Covers:
- RasterResult dataclass (properties, creation)
- OutputManager.save_raster_layers() (GeoTIFF + JPEG output, filenames)
- RecipeRunner vector/raster split (mock providers returning RasterResult)
- GLBExporter.add_raster_plane() (GLTF2 structure, nodes, textures, UV coords)
- WCSProvider._elevation_to_pil_image() (nodata handling, colour conversion)
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from giskit.core.raster import RasterResult
from giskit.core.recipe import (
    Dataset,
    Location,
    LocationType,
    Output,
    OutputFormat,
    Recipe,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rgb_image(width: int = 10, height: int = 8) -> Image.Image:
    """Return a small solid-red RGB PIL image."""
    return Image.new("RGB", (width, height), color=(255, 0, 0))


def _make_raster_result(
    layer_name: str = "test_layer",
    width: int = 10,
    height: int = 8,
    bbox_rd: tuple[float, float, float, float] = (100.0, 200.0, 200.0, 280.0),
    bbox_wgs84: tuple[float, float, float, float] = (4.8, 52.3, 4.9, 52.4),
) -> RasterResult:
    """Return a minimal RasterResult for testing."""
    return RasterResult(
        layer_name=layer_name,
        image=_make_rgb_image(width, height),
        bbox_rd=bbox_rd,
        bbox_wgs84=bbox_wgs84,
    )


def _make_recipe(tmp_path: Path, output_format: OutputFormat = OutputFormat.GPKG) -> Recipe:
    """Return a minimal Recipe whose output path is inside tmp_path."""
    return Recipe(
        name="Test",
        description="Test recipe",
        location=Location(
            type=LocationType.BBOX,
            value=[4.8, 52.3, 4.9, 52.4],
            crs="EPSG:4326",
            radius=None,
        ),
        datasets=[Dataset(provider="pdok", service="bgt")],
        output=Output(
            path=tmp_path / "output.gpkg",
            format=output_format,
            crs="EPSG:28992",
            overwrite=True,
            layer_prefix=None,
            ifc_export=None,
        ),
    )


# ---------------------------------------------------------------------------
# Tests — RasterResult dataclass
# ---------------------------------------------------------------------------


class TestRasterResult:
    """Tests for the RasterResult dataclass."""

    def test_creation_defaults(self):
        """RasterResult stores fields and defaults source_crs."""
        rr = _make_raster_result()
        assert rr.layer_name == "test_layer"
        assert rr.image is not None
        assert rr.bbox_rd == (100.0, 200.0, 200.0, 280.0)
        assert rr.bbox_wgs84 == (4.8, 52.3, 4.9, 52.4)
        assert rr.source_crs == "EPSG:28992"

    def test_width_m(self):
        """width_m returns difference of x-coordinates."""
        rr = _make_raster_result(bbox_rd=(100.0, 200.0, 350.0, 400.0))
        assert rr.width_m == pytest.approx(250.0)

    def test_height_m(self):
        """height_m returns difference of y-coordinates."""
        rr = _make_raster_result(bbox_rd=(100.0, 200.0, 350.0, 400.0))
        assert rr.height_m == pytest.approx(200.0)

    def test_pixel_size_x(self):
        """pixel_size_x = width_m / image.width."""
        # bbox is 100 m wide, image is 10 px wide → 10 m/px
        rr = _make_raster_result(width=10, height=8, bbox_rd=(0.0, 0.0, 100.0, 80.0))
        assert rr.pixel_size_x == pytest.approx(10.0)

    def test_pixel_size_y(self):
        """pixel_size_y = height_m / image.height."""
        # bbox is 80 m tall, image is 8 px tall → 10 m/px
        rr = _make_raster_result(width=10, height=8, bbox_rd=(0.0, 0.0, 100.0, 80.0))
        assert rr.pixel_size_y == pytest.approx(10.0)

    def test_pixel_size_zero_dimensions(self):
        """pixel_size returns 0.0 when image dimensions are 0 (guard against div-by-zero)."""
        img = Image.new("RGB", (0, 0))
        rr = RasterResult(
            layer_name="empty",
            image=img,
            bbox_rd=(0.0, 0.0, 100.0, 100.0),
            bbox_wgs84=(0.0, 0.0, 1.0, 1.0),
        )
        assert rr.pixel_size_x == 0.0
        assert rr.pixel_size_y == 0.0

    def test_custom_source_crs(self):
        """source_crs can be overridden."""
        img = _make_rgb_image()
        rr = RasterResult(
            layer_name="x",
            image=img,
            bbox_rd=(0.0, 0.0, 1.0, 1.0),
            bbox_wgs84=(0.0, 0.0, 1.0, 1.0),
            source_crs="EPSG:4326",
        )
        assert rr.source_crs == "EPSG:4326"


# ---------------------------------------------------------------------------
# Tests — OutputManager.save_raster_layers()
# ---------------------------------------------------------------------------


class TestSaveRasterLayers:
    """Tests for OutputManager.save_raster_layers()."""

    @pytest.fixture
    def manager(self, tmp_path):
        from giskit.core.output import OutputManager

        recipe = _make_recipe(tmp_path)
        return OutputManager(recipe, tmp_path)

    def test_returns_list_of_paths(self, manager, tmp_path):
        """save_raster_layers() returns a list of Path objects."""
        rr = _make_raster_result("luchtfoto")
        paths = manager.save_raster_layers({"luchtfoto": rr})

        assert isinstance(paths, list)
        assert len(paths) == 2  # one .tif + one .jpg

    def test_tif_and_jpg_created(self, manager, tmp_path):
        """Both a GeoTIFF (.tif) and JPEG (.jpg) file are written."""
        rr = _make_raster_result("luchtfoto")
        paths = manager.save_raster_layers({"luchtfoto": rr})

        suffixes = {p.suffix for p in paths}
        assert ".tif" in suffixes
        assert ".jpg" in suffixes
        for p in paths:
            assert p.exists(), f"{p} should exist"

    def test_filename_contains_layer_name(self, manager, tmp_path):
        """Output filenames contain the layer name."""
        rr = _make_raster_result("ahn_dtm")
        paths = manager.save_raster_layers({"ahn_dtm": rr})

        for p in paths:
            assert "ahn_dtm" in p.name, f"Layer name missing from filename: {p.name}"

    def test_filename_stem_matches_recipe_output_stem(self, manager, tmp_path):
        """Output filenames start with the recipe output stem ('output')."""
        rr = _make_raster_result("luchtfoto")
        paths = manager.save_raster_layers({"luchtfoto": rr})

        for p in paths:
            assert p.name.startswith("output_"), f"Expected stem 'output_', got: {p.name}"

    def test_multiple_layers_produce_separate_files(self, manager, tmp_path):
        """Each raster layer produces its own pair of tif/jpg files."""
        layers = {
            "luchtfoto": _make_raster_result("luchtfoto"),
            "ahn_dtm": _make_raster_result("ahn_dtm"),
        }
        paths = manager.save_raster_layers(layers)

        assert len(paths) == 4  # 2 layers × 2 files each
        names = {p.name for p in paths}
        assert any("luchtfoto" in n for n in names)
        assert any("ahn_dtm" in n for n in names)

    def test_progress_callback_called(self, manager, tmp_path):
        """Progress callback is called at least once per layer."""
        messages = []
        rr = _make_raster_result("luchtfoto")
        manager.save_raster_layers(
            {"luchtfoto": rr}, progress_callback=lambda m, _l: messages.append(m)
        )

        assert len(messages) >= 2  # at least one for .tif, one for .jpg

    def test_empty_dict_returns_empty_list(self, manager, tmp_path):
        """Passing an empty dict returns an empty list and writes no files."""
        paths = manager.save_raster_layers({})
        assert paths == []

    def test_geotiff_has_correct_dimensions(self, manager, tmp_path):
        """GeoTIFF file has the same pixel dimensions as the input image."""
        rasterio = pytest.importorskip("rasterio")
        rr = _make_raster_result("luchtfoto", width=10, height=8)
        paths = manager.save_raster_layers({"luchtfoto": rr})

        tif = next(p for p in paths if p.suffix == ".tif")
        with rasterio.open(str(tif)) as ds:
            assert ds.width == 10
            assert ds.height == 8
            assert ds.count == 3  # RGB bands

    def test_geotiff_has_crs(self, manager, tmp_path):
        """GeoTIFF file is written with a CRS (EPSG:28992)."""
        rasterio = pytest.importorskip("rasterio")
        rr = _make_raster_result("luchtfoto")
        paths = manager.save_raster_layers({"luchtfoto": rr})

        tif = next(p for p in paths if p.suffix == ".tif")
        with rasterio.open(str(tif)) as ds:
            assert ds.crs is not None
            assert "28992" in ds.crs.to_string()


# ---------------------------------------------------------------------------
# Tests — RecipeRunner vector/raster split
# ---------------------------------------------------------------------------


class TestRecipeRunnerRasterSplit:
    """Tests that RecipeRunner correctly splits vector and raster results."""

    @pytest.fixture
    def runner(self, tmp_path):
        from giskit.core.runner import RecipeRunner

        recipe = _make_recipe(tmp_path)
        return RecipeRunner(recipe, tmp_path)

    @pytest.mark.asyncio
    async def test_raster_result_goes_to_raster_layers(self, runner):
        """A RasterResult from a provider is placed in raster_layers, not vector_layers."""
        rr = _make_raster_result("luchtfoto")

        with patch("giskit.core.runner.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.download_dataset = AsyncMock(return_value=rr)
            mock_get_provider.return_value = mock_provider

            result = await runner.execute()

            assert result is not None
            vector_layers, raster_layers = result
            assert "luchtfoto" in raster_layers
            # Should not appear in vector layers
            assert "luchtfoto" not in vector_layers

    @pytest.mark.asyncio
    async def test_raster_result_is_raster_result_instance(self, runner):
        """The value in raster_layers is the original RasterResult."""
        rr = _make_raster_result("my_raster")

        with patch("giskit.core.runner.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.download_dataset = AsyncMock(return_value=rr)
            mock_get_provider.return_value = mock_provider

            result = await runner.execute()

            assert result is not None
            _, raster_layers = result
            assert isinstance(raster_layers["my_raster"], RasterResult)

    @pytest.mark.asyncio
    async def test_empty_geodataframe_excluded_from_vector(self, runner):
        """An empty GeoDataFrame is filtered out of vector_layers."""
        import geopandas as gpd

        gdf = gpd.GeoDataFrame(geometry=[], crs="EPSG:28992")

        with patch("giskit.core.runner.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.download_dataset = AsyncMock(return_value=gdf)
            mock_get_provider.return_value = mock_provider

            result = await runner.execute()

            # No data → runner returns None
            assert result is None


# ---------------------------------------------------------------------------
# Tests — WCSProvider._elevation_to_pil_image()
# ---------------------------------------------------------------------------


class TestElevationToPilImage:
    """Tests for the module-level _elevation_to_pil_image helper in wcs.py."""

    @pytest.fixture
    def fn(self):
        from giskit.providers.wcs import _elevation_to_pil_image

        return _elevation_to_pil_image

    def test_returns_pil_image(self, fn):
        """Result is a PIL Image."""
        arr = np.array([[1.0, 2.0], [3.0, 4.0]])
        img = fn(arr)
        assert isinstance(img, Image.Image)

    def test_mode_is_rgb(self, fn):
        """Result is in RGB mode."""
        arr = np.array([[0.0, 5.0], [10.0, 15.0]])
        img = fn(arr)
        assert img.mode == "RGB"

    def test_dimensions_match_array(self, fn):
        """Image dimensions match the array shape (height, width)."""
        arr = np.zeros((6, 9))
        img = fn(arr)
        assert img.size == (9, 6)  # PIL: (width, height)

    def test_all_nodata_returns_grey(self, fn):
        """An all-nodata array returns a uniform grey image."""
        arr = np.full((4, 4), np.nan)
        img = fn(arr)
        # All pixels should be the nodata grey (128, 128, 128)
        pixels = list(img.getdata())
        assert all(p == (128, 128, 128) for p in pixels)

    def test_nodata_sentinel_minus9999(self, fn):
        """Values <= -9999 are treated as nodata."""
        arr = np.array([[-9999.0, -9999.0], [-9999.0, -9999.0]])
        img = fn(arr)
        pixels = list(img.getdata())
        assert all(p == (128, 128, 128) for p in pixels)

    def test_mixed_nodata_and_valid(self, fn):
        """Nodata pixels are grey; valid pixels are coloured differently."""
        arr = np.array([[np.nan, 5.0], [10.0, np.nan]])
        img = fn(arr)
        pixels = np.array(img)  # shape (H, W, 3)

        # Pixel (0,0) and (1,1) are nodata → grey
        assert tuple(pixels[0, 0]) == (128, 128, 128)
        assert tuple(pixels[1, 1]) == (128, 128, 128)

        # Pixel (0,1) and (1,0) are valid → not grey
        assert tuple(pixels[0, 1]) != (128, 128, 128)
        assert tuple(pixels[1, 0]) != (128, 128, 128)

    def test_uniform_elevation_no_crash(self, fn):
        """A uniform elevation array (vmin == vmax) does not raise."""
        arr = np.full((4, 4), 5.0)
        img = fn(arr)
        assert isinstance(img, Image.Image)

    def test_low_elevation_is_different_from_high(self, fn):
        """Low and high elevations produce different colours."""
        arr = np.array([[0.0, 100.0]])
        img = fn(arr)
        pixels = np.array(img)
        low_px = tuple(pixels[0, 0])
        high_px = tuple(pixels[0, 1])
        assert low_px != high_px, "Low and high elevations should produce different colours"


# ---------------------------------------------------------------------------
# Tests — GLBExporter.add_raster_plane()
# ---------------------------------------------------------------------------


class TestGLBExporterAddRasterPlane:
    """Tests for GLBExporter.add_raster_plane()."""

    @pytest.fixture
    def exporter(self):
        """Return a GLBExporter instance (ifcopenshell optional dep; skip if missing)."""
        pytest.importorskip("ifcopenshell")
        pytest.importorskip("pygltflib")
        from giskit.exporters.glb_exporter import GLBExporter

        return GLBExporter()

    @pytest.fixture
    def fresh_gltf(self):
        """Return a minimal GLTF2 object with an empty binary blob and buffer."""
        import pygltflib

        gltf = pygltflib.GLTF2()
        gltf.buffers.append(pygltflib.Buffer(byteLength=0))
        gltf.set_binary_blob(b"")
        gltf.scenes.append(pygltflib.Scene(nodes=[]))
        gltf.scene = 0
        return gltf

    def test_adds_one_mesh(self, exporter, fresh_gltf):
        """add_raster_plane() adds exactly one mesh to the GLTF2 object."""
        rr = _make_raster_result("luchtfoto")
        exporter.add_raster_plane(fresh_gltf, rr, ref_x=0.0, ref_y=0.0)
        assert len(fresh_gltf.meshes) == 1

    def test_adds_one_node(self, exporter, fresh_gltf):
        """add_raster_plane() adds exactly one node to the GLTF2 object."""
        rr = _make_raster_result("luchtfoto")
        exporter.add_raster_plane(fresh_gltf, rr, ref_x=0.0, ref_y=0.0)
        assert len(fresh_gltf.nodes) == 1

    def test_node_added_to_scene(self, exporter, fresh_gltf):
        """The new node is appended to the active scene's node list."""
        rr = _make_raster_result("luchtfoto")
        exporter.add_raster_plane(fresh_gltf, rr, ref_x=0.0, ref_y=0.0)
        assert 0 in fresh_gltf.scenes[0].nodes

    def test_adds_one_material(self, exporter, fresh_gltf):
        """add_raster_plane() adds exactly one material."""
        rr = _make_raster_result("luchtfoto")
        exporter.add_raster_plane(fresh_gltf, rr, ref_x=0.0, ref_y=0.0)
        assert len(fresh_gltf.materials) == 1

    def test_material_name_contains_layer(self, exporter, fresh_gltf):
        """Material name contains the layer name."""
        rr = _make_raster_result("luchtfoto_actueel")
        exporter.add_raster_plane(fresh_gltf, rr, ref_x=0.0, ref_y=0.0)
        assert "luchtfoto_actueel" in fresh_gltf.materials[0].name

    def test_adds_texture_and_image(self, exporter, fresh_gltf):
        """add_raster_plane() adds exactly one texture and one image."""
        rr = _make_raster_result("luchtfoto")
        exporter.add_raster_plane(fresh_gltf, rr, ref_x=0.0, ref_y=0.0)
        assert len(fresh_gltf.textures) == 1
        assert len(fresh_gltf.images) == 1

    def test_adds_sampler(self, exporter, fresh_gltf):
        """add_raster_plane() adds exactly one sampler."""
        rr = _make_raster_result("luchtfoto")
        exporter.add_raster_plane(fresh_gltf, rr, ref_x=0.0, ref_y=0.0)
        assert len(fresh_gltf.samplers) == 1

    def test_mesh_has_texcoord_attribute(self, exporter, fresh_gltf):
        """The mesh primitive has a TEXCOORD_0 attribute set."""
        rr = _make_raster_result("luchtfoto")
        exporter.add_raster_plane(fresh_gltf, rr, ref_x=0.0, ref_y=0.0)
        prim = fresh_gltf.meshes[0].primitives[0]
        assert prim.attributes.TEXCOORD_0 is not None

    def test_z_offset_default_is_minus_0_01(self, exporter, fresh_gltf):
        """Default z_offset (-0.01) is encoded in the vertex positions."""
        import struct

        rr = _make_raster_result("luchtfoto", bbox_rd=(0.0, 0.0, 100.0, 80.0))
        exporter.add_raster_plane(fresh_gltf, rr, ref_x=0.0, ref_y=0.0)

        # Find the position accessor (first accessor, VEC3 FLOAT)
        pos_acc = fresh_gltf.accessors[0]
        bv = fresh_gltf.bufferViews[pos_acc.bufferView]
        blob = fresh_gltf.binary_blob()
        raw = blob[bv.byteOffset : bv.byteOffset + bv.byteLength]
        # 4 vertices × 3 floats × 4 bytes = 48 bytes
        floats = struct.unpack(f"{len(raw) // 4}f", raw)
        # Every 3rd element (index 2, 5, 8, 11) is the z coordinate
        z_values = [floats[i] for i in range(2, len(floats), 3)]
        assert all(abs(z - (-0.01)) < 1e-5 for z in z_values), f"z values: {z_values}"

    def test_custom_layer_name(self, exporter, fresh_gltf):
        """Passing a custom layer_name overrides raster.layer_name."""
        rr = _make_raster_result("original_name")
        exporter.add_raster_plane(fresh_gltf, rr, ref_x=0.0, ref_y=0.0, layer_name="custom")
        assert "custom" in fresh_gltf.meshes[0].name
        assert "original_name" not in fresh_gltf.meshes[0].name

    def test_two_planes_accumulate(self, exporter, fresh_gltf):
        """Calling add_raster_plane() twice adds two meshes and two nodes."""
        rr1 = _make_raster_result("layer_a", bbox_rd=(0.0, 0.0, 100.0, 80.0))
        rr2 = _make_raster_result("layer_b", bbox_rd=(100.0, 0.0, 200.0, 80.0))
        exporter.add_raster_plane(fresh_gltf, rr1, ref_x=0.0, ref_y=0.0)
        exporter.add_raster_plane(fresh_gltf, rr2, ref_x=0.0, ref_y=0.0)
        assert len(fresh_gltf.meshes) == 2
        assert len(fresh_gltf.nodes) == 2
