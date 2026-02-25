"""Unit tests for ConfigDrivenProvider."""

from pathlib import Path
from unittest.mock import patch

import pytest

from giskit.providers.config_driven import ConfigDrivenProvider


class TestConfigDrivenProvider:
    """Tests for ConfigDrivenProvider base class."""

    @pytest.fixture
    def sample_config(self):
        """Create sample service configuration."""
        return {
            "name": "test_service",
            "protocol": "ogc_features",
            "url": "https://example.com/api",
            "description": "Test service",
        }

    def test_get_service_config_exists(self, sample_config):
        """Test getting existing service configuration."""

        class TestProvider(ConfigDrivenProvider):
            """Test provider implementation."""

            def _get_config_file(self) -> Path:
                return Path("test.yaml")

            def get_supported_protocols(self) -> list[str]:
                return ["ogc_features"]

            async def download_dataset(self, dataset, location, output_path, output_crs):
                pass

        provider = TestProvider()

        with patch.object(
            provider, "_load_yaml_config", return_value={"services": [sample_config]}
        ):
            config = provider.get_service_config("test_service")
            assert config["name"] == "test_service"
            assert config["protocol"] == "ogc_features"

    def test_get_service_config_not_found(self):
        """Test error when service not found."""

        class TestProvider(ConfigDrivenProvider):
            def _get_config_file(self) -> Path:
                return Path("test.yaml")

            def get_supported_protocols(self) -> list[str]:
                return ["ogc_features"]

            async def download_dataset(self, dataset, location, output_path, output_crs):
                pass

        provider = TestProvider()

        with patch.object(provider, "_load_yaml_config", return_value={"services": []}):
            with pytest.raises(ValueError, match="Service 'unknown' not found"):
                provider.get_service_config("unknown")

    def test_config_caching(self, sample_config):
        """Test that configuration is cached after first load."""

        class TestProvider(ConfigDrivenProvider):
            def _get_config_file(self) -> Path:
                return Path("test.yaml")

            def get_supported_protocols(self) -> list[str]:
                return ["ogc_features"]

            async def download_dataset(self, dataset, location, output_path, output_crs):
                pass

        provider = TestProvider()

        with patch.object(
            provider, "_load_yaml_config", return_value={"services": [sample_config]}
        ) as mock_load:
            # First call should load config
            provider.get_service_config("test_service")
            assert mock_load.call_count == 1

            # Second call should use cache
            provider.get_service_config("test_service")
            assert mock_load.call_count == 1  # Still 1, not called again
