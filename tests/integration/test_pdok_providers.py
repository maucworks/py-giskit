"""Integration tests for PDOK Providers with ConfigDrivenProvider pattern.

Tests that the refactored PDOK providers (WMTS and WCS) work correctly with
the ConfigDrivenProvider base class and ProtocolRegistry pattern.

These tests verify:
1. ConfigDrivenProvider loads YAML configurations correctly
2. ProtocolRegistry creates appropriate protocol instances
3. Providers integrate correctly with core refactored modules
4. Real PDOK services are accessible and configured properly

Note: These tests are marked as @pytest.mark.integration since they test
the integration between multiple refactored components.
"""

import pytest

from giskit.protocols.registry import get_protocol_registry
from giskit.providers.base import get_provider
from giskit.providers.config_driven import ConfigDrivenProvider
from giskit.providers.wcs import WCSProvider
from giskit.providers.wmts import WMTSProvider


class TestPDOKWMTSConfigDrivenProvider:
    """Test PDOK WMTS provider uses ConfigDrivenProvider correctly."""

    @pytest.mark.integration
    def test_pdok_wmts_is_config_driven(self):
        """Test that PDOK WMTS provider inherits from ConfigDrivenProvider."""
        provider = get_provider("pdok-wmts")

        assert isinstance(provider, ConfigDrivenProvider)
        assert isinstance(provider, WMTSProvider)

    @pytest.mark.integration
    def test_pdok_wmts_loads_yaml_config(self):
        """Test that PDOK WMTS provider loads config from YAML."""
        provider = WMTSProvider("pdok-wmts")

        # Should have services from pdok-wmts.yml
        assert len(provider.services) > 0
        assert "luchtfoto" in provider.services
        assert "brt-achtergrondkaart" in provider.services
        assert "satellite" in provider.services

    @pytest.mark.integration
    def test_pdok_wmts_service_has_yaml_metadata(self):
        """Test that services have metadata loaded from YAML."""
        provider = WMTSProvider("pdok-wmts")

        luchtfoto = provider.services["luchtfoto"]

        # Check YAML fields are loaded
        assert luchtfoto["title"] == "Luchtfoto Beeldmateriaal Nederland"
        assert luchtfoto["category"] == "imagery"
        assert "description" in luchtfoto
        assert "keywords" in luchtfoto
        assert "luchtfoto" in luchtfoto["keywords"]

    @pytest.mark.integration
    def test_pdok_wmts_get_service_config(self):
        """Test get_service_config() method from ConfigDrivenProvider."""
        provider = WMTSProvider("pdok-wmts")

        # Use ConfigDrivenProvider method
        luchtfoto_config = provider.get_service_config("luchtfoto")

        assert luchtfoto_config is not None
        assert luchtfoto_config["title"] == "Luchtfoto Beeldmateriaal Nederland"
        assert "url" in luchtfoto_config

    @pytest.mark.integration
    def test_pdok_wmts_get_service_config_not_found(self):
        """Test get_service_config() raises error for unknown service."""
        provider = WMTSProvider("pdok-wmts")

        with pytest.raises(ValueError, match="not found"):
            provider.get_service_config("unknown-service")


class TestPDOKWCSConfigDrivenProvider:
    """Test PDOK WCS provider uses ConfigDrivenProvider correctly."""

    @pytest.mark.integration
    def test_pdok_wcs_is_config_driven(self):
        """Test that PDOK WCS provider inherits from ConfigDrivenProvider."""
        provider = get_provider("pdok-wcs")

        assert isinstance(provider, ConfigDrivenProvider)
        assert isinstance(provider, WCSProvider)

    @pytest.mark.integration
    def test_pdok_wcs_loads_yaml_config(self):
        """Test that PDOK WCS provider loads config from YAML."""
        provider = WCSProvider("pdok-wcs")

        # Should have services from pdok-wcs.yml
        assert len(provider.services) > 0
        assert "ahn" in provider.services

    @pytest.mark.integration
    def test_pdok_wcs_service_has_yaml_metadata(self):
        """Test that AHN service has metadata loaded from YAML."""
        provider = WCSProvider("pdok-wcs")

        ahn = provider.services["ahn"]

        # Check YAML fields are loaded
        assert ahn["title"] == "Actueel Hoogtebestand Nederland (AHN)"
        assert ahn["category"] == "elevation"
        assert "description" in ahn
        assert "keywords" in ahn
        assert "ahn4" in ahn["keywords"]
        assert ahn["native_resolution"] == 0.5
        assert ahn["native_crs"] == "EPSG:28992"

    @pytest.mark.integration
    def test_pdok_wcs_get_service_config(self):
        """Test get_service_config() method from ConfigDrivenProvider."""
        provider = WCSProvider("pdok-wcs")

        # Use ConfigDrivenProvider method
        ahn_config = provider.get_service_config("ahn")

        assert ahn_config is not None
        assert ahn_config["title"] == "Actueel Hoogtebestand Nederland (AHN)"
        assert "url" in ahn_config
        assert "coverages" in ahn_config


class TestPDOKProvidersProtocolRegistry:
    """Test PDOK providers integrate with ProtocolRegistry."""

    @pytest.mark.integration
    def test_wmts_protocol_registered(self):
        """Test that WMTS protocol is registered in global registry."""
        registry = get_protocol_registry()

        protocols = registry.get_available_protocols()

        assert "wmts" in protocols

    @pytest.mark.integration
    def test_wcs_protocol_registered(self):
        """Test that WCS protocol is registered in global registry."""
        registry = get_protocol_registry()

        protocols = registry.get_available_protocols()

        assert "wcs" in protocols

    @pytest.mark.integration
    def test_wmts_provider_creates_protocol_instances(self):
        """Test that WMTS provider creates protocol instances for layers."""
        provider = WMTSProvider("pdok-wmts")

        # Check that protocols dict is populated
        assert len(provider.protocols) > 0

        # Check specific protocols exist
        assert "luchtfoto.actueel_25cm" in provider.protocols
        assert "luchtfoto.actueel_8cm" in provider.protocols

        # Check protocol type
        from giskit.protocols.wmts import WMTSProtocol

        protocol = provider.protocols["luchtfoto.actueel_25cm"]
        assert isinstance(protocol, WMTSProtocol)

    @pytest.mark.integration
    def test_wcs_provider_creates_protocol_instances(self):
        """Test that WCS provider creates protocol instances for coverages."""
        provider = WCSProvider("pdok-wcs")

        # Check that protocols dict is populated
        assert len(provider.protocols) > 0

        # Check specific protocols exist
        assert "ahn.dsm" in provider.protocols
        assert "ahn.dtm" in provider.protocols

        # Check protocol type
        from giskit.protocols.wcs import WCSProtocol

        protocol = provider.protocols["ahn.dtm"]
        assert isinstance(protocol, WCSProtocol)


class TestPDOKProvidersConfigCaching:
    """Test that ConfigDrivenProvider caches configurations correctly."""

    @pytest.mark.integration
    def test_wmts_provider_caches_config(self):
        """Test that WMTS provider caches loaded configuration."""
        # Create two instances with same name
        provider1 = WMTSProvider("pdok-wmts")
        provider2 = WMTSProvider("pdok-wmts")

        # Both should have same services (from cache or loaded)
        assert provider1.services == provider2.services

        # Services should be the loaded dict
        assert len(provider1.services) > 0

    @pytest.mark.integration
    def test_wcs_provider_caches_config(self):
        """Test that WCS provider caches loaded configuration."""
        # Create two instances with same name
        provider1 = WCSProvider("pdok-wcs")
        provider2 = WCSProvider("pdok-wcs")

        # Both should have same services
        assert provider1.services == provider2.services
        assert len(provider1.services) > 0


class TestPDOKProvidersServiceCoverage:
    """Test that PDOK providers expose expected services."""

    @pytest.mark.integration
    def test_pdok_wmts_has_aerial_imagery(self):
        """Test that PDOK WMTS has aerial imagery services."""
        provider = WMTSProvider("pdok-wmts")

        # Should have luchtfoto service with multiple resolutions
        assert "luchtfoto" in provider.services

        luchtfoto = provider.services["luchtfoto"]
        layers = luchtfoto.get("layers", {})

        # Should have various resolutions available
        assert "actueel_25cm" in layers
        assert "actueel_8cm" in layers

    @pytest.mark.integration
    def test_pdok_wmts_has_background_maps(self):
        """Test that PDOK WMTS has background map services."""
        provider = WMTSProvider("pdok-wmts")

        # Should have BRT background maps
        assert "brt-achtergrondkaart" in provider.services

        brt = provider.services["brt-achtergrondkaart"]
        layers = brt.get("layers", {})

        # Should have multiple styles
        assert "standaard" in layers
        assert "grijs" in layers
        assert "pastel" in layers

    @pytest.mark.integration
    def test_pdok_wcs_has_ahn_elevation(self):
        """Test that PDOK WCS has AHN elevation services."""
        provider = WCSProvider("pdok-wcs")

        # Should have AHN service
        assert "ahn" in provider.services

        ahn = provider.services["ahn"]
        coverages = ahn.get("coverages", {})

        # Should have both DTM and DSM
        assert "dtm" in coverages
        assert "dsm" in coverages
        assert coverages["dtm"] == "dtm_05m"
        assert coverages["dsm"] == "dsm_05m"


class TestPDOKProvidersURLConfiguration:
    """Test that PDOK providers have correct API URLs."""

    @pytest.mark.integration
    def test_pdok_wmts_luchtfoto_url(self):
        """Test that luchtfoto has correct PDOK WMTS URL."""
        provider = WMTSProvider("pdok-wmts")

        luchtfoto = provider.services["luchtfoto"]
        url = luchtfoto.get("url", "")

        assert "service.pdok.nl" in url
        assert "wmts" in url.lower()
        assert "luchtfotorgb" in url

    @pytest.mark.integration
    def test_pdok_wcs_ahn_url(self):
        """Test that AHN has correct PDOK WCS URL."""
        provider = WCSProvider("pdok-wcs")

        ahn = provider.services["ahn"]
        url = ahn.get("url", "")

        assert "service.pdok.nl" in url
        assert "wcs" in url.lower()
        assert "ahn" in url.lower()
