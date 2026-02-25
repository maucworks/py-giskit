"""Unit tests for ProtocolRegistry."""

import pytest

from giskit.protocols.registry import ProtocolRegistry, clear_registry, register_protocol


class TestProtocolRegistry:
    """Tests for ProtocolRegistry pattern."""

    def test_register_protocol(self):
        """Test protocol registration."""

        def test_factory(config):
            return "test_protocol_instance"

        # Clear registry before test
        clear_registry()

        register_protocol("test_protocol", test_factory)

        assert "test_protocol" in ProtocolRegistry._factories
        assert ProtocolRegistry._factories["test_protocol"] == test_factory

    def test_create_protocol(self):
        """Test protocol creation from factory."""
        clear_registry()

        def test_factory(config):
            return f"protocol_for_{config['url']}"

        register_protocol("test_proto", test_factory)

        protocol = ProtocolRegistry.create_protocol("test_proto", {"url": "http://example.com"})

        assert protocol == "protocol_for_http://example.com"

    def test_create_unknown_protocol(self):
        """Test error when creating unknown protocol."""
        clear_registry()

        with pytest.raises(ValueError, match="Unknown protocol: unknown"):
            ProtocolRegistry.create_protocol("unknown", {})

    def test_get_available_protocols(self):
        """Test getting list of available protocols."""
        clear_registry()

        register_protocol("proto1", lambda c: None)
        register_protocol("proto2", lambda c: None)

        available = ProtocolRegistry.get_available_protocols()

        assert "proto1" in available
        assert "proto2" in available
        assert len(available) >= 2

    def test_duplicate_registration_warning(self):
        """Test warning when registering duplicate protocol."""
        clear_registry()

        register_protocol("dup_test", lambda c: "v1")

        # Second registration should work but might log a warning
        register_protocol("dup_test", lambda c: "v2")

        # Latest registration should win
        protocol = ProtocolRegistry.create_protocol("dup_test", {})
        assert protocol == "v2"

    def test_clear_registry(self):
        """Test clearing the registry."""
        clear_registry()

        register_protocol("temp", lambda c: None)
        assert "temp" in ProtocolRegistry._factories

        clear_registry()
        assert len(ProtocolRegistry._factories) == 0

    def test_built_in_protocols_registered(self):
        """Test that built-in protocols are registered on import."""
        # Import triggers registration

        available = ProtocolRegistry.get_available_protocols()

        # These should all be registered
        assert "ogc_features" in available
        assert "wcs" in available
        assert "wfs" in available
        assert "wmts" in available
