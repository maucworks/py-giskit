"""Integration tests for WMTS Provider.

Tests WMTSProvider with real PDOK WMTS services (aerial imagery, maps).
These tests make actual API calls and verify the ConfigDrivenProvider pattern.

Note: These tests are marked as @pytest.mark.integration and @pytest.mark.slow
since they require network access and may take several seconds.
"""

from unittest.mock import AsyncMock, patch

import pytest

from giskit.core.recipe import Dataset, Location, LocationType
from giskit.providers.wmts import WMTSProvider


class TestWMTSProviderConfiguration:
    """Test WMTS provider configuration loading."""

    @pytest.mark.integration
    def test_provider_initialization(self):
        """Test that WMTSProvider loads pdok-wmts config correctly."""
        provider = WMTSProvider("pdok-wmts")

        assert provider.name == "pdok-wmts"
        assert "luchtfoto" in provider.services
        assert "brt-achtergrondkaart" in provider.services

    @pytest.mark.integration
    def test_protocols_registered(self):
        """Test that WMTS protocols are registered for each layer."""
        provider = WMTSProvider("pdok-wmts")

        # Check that layer protocols are registered (service.layer format)
        assert "luchtfoto.actueel_25cm" in provider.protocols
        assert "luchtfoto.actueel_8cm" in provider.protocols
        assert "brt-achtergrondkaart.standaard" in provider.protocols
        assert "satellite.actueel" in provider.protocols

    @pytest.mark.integration
    def test_supported_protocols(self):
        """Test that provider reports wmts as supported protocol."""
        provider = WMTSProvider("pdok-wmts")
        protocols = provider.get_supported_protocols()

        assert protocols == ["wmts"]

    @pytest.mark.integration
    def test_service_config_structure(self):
        """Test that service configs have expected structure."""
        provider = WMTSProvider("pdok-wmts")
        luchtfoto = provider.services["luchtfoto"]

        assert "url" in luchtfoto
        assert "title" in luchtfoto
        assert "layers" in luchtfoto
        assert "tile_format" in luchtfoto
        assert luchtfoto["tile_format"] in ["jpeg", "png"]


class TestWMTSProviderDownload:
    """Test WMTS provider download functionality."""

    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_download_aerial_imagery_mock(self, tmp_path):
        """Test downloading aerial imagery (mocked to avoid large download)."""
        provider = WMTSProvider("pdok-wmts")

        # Create a small test bbox in Amsterdam (RD New coordinates)
        location = Location(
            type=LocationType.BBOX,
            value=[120000.0, 487000.0, 120100.0, 487100.0],  # 100x100m bbox
        )

        dataset = Dataset(
            provider="pdok-wmts",
            service="luchtfoto.actueel_25cm",
            layers=None,
        )

        output_path = tmp_path / "test_aerial.gpkg"

        # Mock the protocol.get_coverage to avoid actual download
        with patch.object(
            provider.protocols["luchtfoto.actueel_25cm"],
            "get_coverage",
            new_callable=AsyncMock,
        ) as mock_get:
            # Create a mock PIL Image
            from PIL import Image

            mock_image = Image.new("RGB", (100, 100), color="red")
            mock_get.return_value = mock_image

            # Also need to patch the context manager
            with patch.object(
                provider.protocols["luchtfoto.actueel_25cm"],
                "__aenter__",
                new_callable=AsyncMock,
                return_value=provider.protocols["luchtfoto.actueel_25cm"],
            ), patch.object(
                provider.protocols["luchtfoto.actueel_25cm"],
                "__aexit__",
                new_callable=AsyncMock,
            ):
                result = await provider.download_dataset(
                    dataset=dataset,
                    location=location,
                    output_path=output_path,
                    output_crs="EPSG:28992",
                )

            # Verify the mock was called
            assert mock_get.called

        # WMTS returns empty GeoDataFrame
        assert len(result) == 0

        # Check that output was saved as image (extension changed from .gpkg to .jpg)
        expected_file = tmp_path / "test_aerial_aerial.jpg"
        assert expected_file.exists()

    @pytest.mark.integration
    def test_invalid_service_format_error(self, tmp_path):
        """Test error when service format is invalid."""
        provider = WMTSProvider("pdok-wmts")

        location = Location(
            type=LocationType.BBOX,
            value=[120000.0, 487000.0, 120100.0, 487100.0],
        )

        # Missing layer part (should be "luchtfoto.actueel_25cm")
        dataset = Dataset(
            provider="pdok-wmts",
            service="luchtfoto",  # Invalid: missing layer
            layers=None,
        )

        with pytest.raises(ValueError, match="service.layer"):
            # Use asyncio.run for async test
            import asyncio

            asyncio.run(
                provider.download_dataset(
                    dataset=dataset,
                    location=location,
                    output_path=tmp_path / "test.gpkg",
                )
            )

    @pytest.mark.integration
    def test_unknown_service_error(self, tmp_path):
        """Test error when service/layer combination not found."""
        provider = WMTSProvider("pdok-wmts")

        location = Location(
            type=LocationType.BBOX,
            value=[120000.0, 487000.0, 120100.0, 487100.0],
        )

        dataset = Dataset(
            provider="pdok-wmts",
            service="unknown.layer",
            layers=None,
        )

        with pytest.raises(ValueError, match="not found"):
            import asyncio

            asyncio.run(
                provider.download_dataset(
                    dataset=dataset,
                    location=location,
                    output_path=tmp_path / "test.gpkg",
                )
            )


class TestWMTSProviderImageFormats:
    """Test WMTS provider image format handling."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_output_path_extension_conversion(self, tmp_path):
        """Test that vector format extensions are converted to image formats."""
        provider = WMTSProvider("pdok-wmts")

        location = Location(
            type=LocationType.BBOX,
            value=[120000.0, 487000.0, 120100.0, 487100.0],
        )

        dataset = Dataset(
            provider="pdok-wmts",
            service="luchtfoto.actueel_25cm",
            layers=None,
        )

        # Mock download to test path conversion logic
        with patch.object(
            provider.protocols["luchtfoto.actueel_25cm"],
            "get_coverage",
            new_callable=AsyncMock,
        ) as mock_get, patch.object(
            provider.protocols["luchtfoto.actueel_25cm"],
            "__aenter__",
            new_callable=AsyncMock,
            return_value=provider.protocols["luchtfoto.actueel_25cm"],
        ), patch.object(
            provider.protocols["luchtfoto.actueel_25cm"],
            "__aexit__",
            new_callable=AsyncMock,
        ):
            from PIL import Image

            mock_image = Image.new("RGB", (100, 100))
            mock_get.return_value = mock_image

            # Test with different vector extensions
            for ext in [".gpkg", ".geojson", ".shp"]:
                output_path = tmp_path / f"test{ext}"
                await provider.download_dataset(
                    dataset=dataset,
                    location=location,
                    output_path=output_path,
                    output_crs="EPSG:28992",
                )

                # Should be converted to _aerial.jpg
                expected = tmp_path / "test_aerial.jpg"
                assert expected.exists()
                expected.unlink()  # Clean up for next iteration

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_png_format_support(self, tmp_path):
        """Test PNG format for services that use PNG tiles."""
        provider = WMTSProvider("pdok-wmts")

        location = Location(
            type=LocationType.BBOX,
            value=[120000.0, 487000.0, 120100.0, 487100.0],
        )

        # BRT background map uses PNG format
        dataset = Dataset(
            provider="pdok-wmts",
            service="brt-achtergrondkaart.standaard",
            layers=None,
        )

        with patch.object(
            provider.protocols["brt-achtergrondkaart.standaard"],
            "get_coverage",
            new_callable=AsyncMock,
        ) as mock_get, patch.object(
            provider.protocols["brt-achtergrondkaart.standaard"],
            "__aenter__",
            new_callable=AsyncMock,
            return_value=provider.protocols["brt-achtergrondkaart.standaard"],
        ), patch.object(
            provider.protocols["brt-achtergrondkaart.standaard"],
            "__aexit__",
            new_callable=AsyncMock,
        ):
            from PIL import Image

            mock_image = Image.new("RGBA", (100, 100))
            mock_get.return_value = mock_image

            output_path = tmp_path / "test.png"
            await provider.download_dataset(
                dataset=dataset,
                location=location,
                output_path=output_path,
                output_crs="EPSG:28992",
            )

            assert output_path.exists()
