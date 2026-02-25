"""Integration tests for WCS Provider.

Tests WCSProvider with real PDOK WCS services (AHN elevation data).
These tests make actual API calls and verify the ConfigDrivenProvider pattern.

Note: These tests are marked as @pytest.mark.integration and @pytest.mark.slow
since they require network access and may take several seconds.
"""

from unittest.mock import AsyncMock, patch

import pytest

from giskit.core.recipe import Dataset, Location, LocationType
from giskit.providers.wcs import WCSProvider


class TestWCSProviderConfiguration:
    """Test WCS provider configuration loading."""

    @pytest.mark.integration
    def test_provider_initialization(self):
        """Test that WCSProvider loads pdok-wcs config correctly."""
        provider = WCSProvider("pdok-wcs")

        assert provider.name == "pdok-wcs"
        assert "ahn" in provider.services

    @pytest.mark.integration
    def test_protocols_registered(self):
        """Test that WCS protocols are registered for each coverage."""
        provider = WCSProvider("pdok-wcs")

        # Check that coverage protocols are registered (service.coverage format)
        assert "ahn.dsm" in provider.protocols
        assert "ahn.dtm" in provider.protocols

    @pytest.mark.integration
    def test_supported_protocols(self):
        """Test that provider reports wcs as supported protocol."""
        provider = WCSProvider("pdok-wcs")
        protocols = provider.get_supported_protocols()

        assert protocols == ["wcs"]

    @pytest.mark.integration
    def test_service_config_structure(self):
        """Test that service configs have expected structure."""
        provider = WCSProvider("pdok-wcs")
        ahn = provider.services["ahn"]

        assert "url" in ahn
        assert "title" in ahn
        assert "coverages" in ahn
        assert "native_resolution" in ahn
        assert "native_crs" in ahn
        assert ahn["native_crs"] == "EPSG:28992"
        assert ahn["native_resolution"] == 0.5

    @pytest.mark.integration
    def test_protocol_has_correct_config(self):
        """Test that WCS protocols have correct configuration."""
        provider = WCSProvider("pdok-wcs")

        dsm_protocol = provider.protocols["ahn.dsm"]
        assert dsm_protocol.coverage_id == "dsm_05m"
        assert dsm_protocol.native_crs == "EPSG:28992"
        assert dsm_protocol.native_resolution == 0.5

        dtm_protocol = provider.protocols["ahn.dtm"]
        assert dtm_protocol.coverage_id == "dtm_05m"


class TestWCSProviderDownload:
    """Test WCS provider download functionality."""

    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_download_ahn_dtm_mock(self, tmp_path):
        """Test downloading AHN DTM elevation data (mocked to avoid large download)."""
        provider = WCSProvider("pdok-wcs")

        # Create a small test bbox in Amsterdam (RD New coordinates)
        location = Location(
            type=LocationType.BBOX,
            value=[120000.0, 487000.0, 120100.0, 487100.0],  # 100x100m bbox
        )

        dataset = Dataset(
            provider="pdok-wcs",
            service="ahn.dtm",
            layers=None,
            resolution=0.5,  # 0.5m resolution
        )

        output_path = tmp_path

        # Mock the protocol.save_coverage_as_geotiff to avoid actual download
        mock_output_file = tmp_path / "ahn_dtm.tif"
        with patch.object(
            provider.protocols["ahn.dtm"],
            "save_coverage_as_geotiff",
            new_callable=AsyncMock,
        ) as mock_save:
            mock_save.return_value = mock_output_file

            # Create a fake GeoTIFF file
            mock_output_file.touch()

            result = await provider.download_dataset(
                dataset=dataset,
                location=location,
                output_path=output_path,
                output_crs="EPSG:28992",
            )

            # Verify the mock was called with correct parameters
            mock_save.assert_called_once()
            call_kwargs = mock_save.call_args.kwargs

            assert call_kwargs["bbox"] == (120000.0, 487000.0, 120100.0, 487100.0)
            assert call_kwargs["resolution"] == 0.5
            assert call_kwargs["crs"] == "EPSG:28992"

        # WCS returns GeoDataFrame with metadata
        assert len(result) == 1
        assert result.iloc[0]["coverage"] == "ahn.dtm"
        assert result.iloc[0]["resolution"] == 0.5
        assert str(mock_output_file) in result.iloc[0]["file"]

    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_download_ahn_dsm_mock(self, tmp_path):
        """Test downloading AHN DSM surface model (mocked)."""
        provider = WCSProvider("pdok-wcs")

        location = Location(
            type=LocationType.BBOX,
            value=[120000.0, 487000.0, 120100.0, 487100.0],
        )

        dataset = Dataset(
            provider="pdok-wcs",
            service="ahn.dsm",
            layers=None,
            resolution=1.0,  # 1m resolution
        )

        output_path = tmp_path

        mock_output_file = tmp_path / "ahn_dsm.tif"
        with patch.object(
            provider.protocols["ahn.dsm"],
            "save_coverage_as_geotiff",
            new_callable=AsyncMock,
        ) as mock_save:
            mock_save.return_value = mock_output_file
            mock_output_file.touch()

            result = await provider.download_dataset(
                dataset=dataset,
                location=location,
                output_path=output_path,
            )

            # Verify resolution parameter was used
            call_kwargs = mock_save.call_args.kwargs
            assert call_kwargs["resolution"] == 1.0

        assert len(result) == 1
        assert result.iloc[0]["coverage"] == "ahn.dsm"

    @pytest.mark.integration
    def test_invalid_service_format_error(self, tmp_path):
        """Test error when service format is invalid."""
        provider = WCSProvider("pdok-wcs")

        location = Location(
            type=LocationType.BBOX,
            value=[120000.0, 487000.0, 120100.0, 487100.0],
        )

        # Missing coverage part (should be "ahn.dtm")
        dataset = Dataset(
            provider="pdok-wcs",
            service="ahn",  # Invalid: missing coverage
            layers=None,
        )

        with pytest.raises(ValueError, match="service.coverage"):
            import asyncio

            asyncio.run(
                provider.download_dataset(
                    dataset=dataset,
                    location=location,
                    output_path=tmp_path,
                )
            )

    @pytest.mark.integration
    def test_unknown_coverage_error(self, tmp_path):
        """Test error when coverage not found."""
        provider = WCSProvider("pdok-wcs")

        location = Location(
            type=LocationType.BBOX,
            value=[120000.0, 487000.0, 120100.0, 487100.0],
        )

        dataset = Dataset(
            provider="pdok-wcs",
            service="ahn.unknown",
            layers=None,
        )

        with pytest.raises(ValueError, match="not found"):
            import asyncio

            asyncio.run(
                provider.download_dataset(
                    dataset=dataset,
                    location=location,
                    output_path=tmp_path,
                )
            )

    @pytest.mark.integration
    def test_non_bbox_location_error(self, tmp_path):
        """Test error when location type is not bbox."""
        provider = WCSProvider("pdok-wcs")

        # Point location not yet supported
        location = Location(
            type=LocationType.POINT,
            value=[5.0, 52.0],
        )

        dataset = Dataset(
            provider="pdok-wcs",
            service="ahn.dtm",
            layers=None,
        )

        with pytest.raises(NotImplementedError, match="not yet supported"):
            import asyncio

            asyncio.run(
                provider.download_dataset(
                    dataset=dataset,
                    location=location,
                    output_path=tmp_path,
                )
            )


class TestWCSProviderResolution:
    """Test WCS provider resolution handling."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_default_resolution_from_config(self, tmp_path):
        """Test that default resolution is used from protocol config."""
        provider = WCSProvider("pdok-wcs")

        location = Location(
            type=LocationType.BBOX,
            value=[120000.0, 487000.0, 120100.0, 487100.0],
        )

        # No resolution specified in dataset
        dataset = Dataset(
            provider="pdok-wcs",
            service="ahn.dtm",
            layers=None,
        )

        mock_output_file = tmp_path / "ahn_dtm.tif"
        with patch.object(
            provider.protocols["ahn.dtm"],
            "save_coverage_as_geotiff",
            new_callable=AsyncMock,
        ) as mock_save:
            mock_save.return_value = mock_output_file
            mock_output_file.touch()

            await provider.download_dataset(
                dataset=dataset,
                location=location,
                output_path=tmp_path,
            )

            # Should use native_resolution from protocol (0.5m)
            call_kwargs = mock_save.call_args.kwargs
            assert call_kwargs["resolution"] == 0.5

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_custom_resolution_override(self, tmp_path):
        """Test that dataset resolution overrides default."""
        provider = WCSProvider("pdok-wcs")

        location = Location(
            type=LocationType.BBOX,
            value=[120000.0, 487000.0, 120100.0, 487100.0],
        )

        # Specify custom resolution
        dataset = Dataset(
            provider="pdok-wcs",
            service="ahn.dtm",
            layers=None,
            resolution=2.0,  # Custom 2m resolution
        )

        mock_output_file = tmp_path / "ahn_dtm.tif"
        with patch.object(
            provider.protocols["ahn.dtm"],
            "save_coverage_as_geotiff",
            new_callable=AsyncMock,
        ) as mock_save:
            mock_save.return_value = mock_output_file
            mock_output_file.touch()

            await provider.download_dataset(
                dataset=dataset,
                location=location,
                output_path=tmp_path,
            )

            # Should use custom resolution
            call_kwargs = mock_save.call_args.kwargs
            assert call_kwargs["resolution"] == 2.0


class TestWCSProviderMetadata:
    """Test WCS provider metadata handling."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_metadata_geodataframe_structure(self, tmp_path):
        """Test that returned GeoDataFrame has correct metadata structure."""
        provider = WCSProvider("pdok-wcs")

        location = Location(
            type=LocationType.BBOX,
            value=[120000.0, 487000.0, 120100.0, 487100.0],
        )

        dataset = Dataset(
            provider="pdok-wcs",
            service="ahn.dtm",
            layers=None,
            resolution=0.5,
        )

        mock_output_file = tmp_path / "ahn_dtm.tif"
        with patch.object(
            provider.protocols["ahn.dtm"],
            "save_coverage_as_geotiff",
            new_callable=AsyncMock,
        ) as mock_save:
            mock_save.return_value = mock_output_file
            mock_output_file.touch()

            result = await provider.download_dataset(
                dataset=dataset,
                location=location,
                output_path=tmp_path,
            )

        # Check metadata structure
        assert len(result) == 1
        assert "coverage" in result.columns
        assert "file" in result.columns
        assert "resolution" in result.columns
        assert "geometry" in result.columns

        # Check CRS
        assert result.crs == "EPSG:28992"

        # Check geometry is bbox
        geom = result.iloc[0].geometry
        assert geom.bounds == (120000.0, 487000.0, 120100.0, 487100.0)
