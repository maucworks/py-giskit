"""Unit tests for ProtocolRegistry."""

import pytest

from giskit.protocols.registry import (
    clear_registry,
    create_protocol,
    get_registry,
    register_protocol,
)


class TestProtocolRegistry:
    """Tests for ProtocolRegistry pattern."""

    def test_register_protocol(self):
        """Test protocol registration."""

        def test_factory(config):
            return "test_protocol_instance"

        # Clear registry before test
        clear_registry()

        register_protocol("test_protocol", test_factory)

        registry = get_registry()
        assert "test_protocol" in registry._factories
        assert registry._factories["test_protocol"] == test_factory

    def test_create_protocol(self):
        """Test protocol creation from factory."""
        clear_registry()

        def test_factory(config):
            return f"protocol_for_{config['url']}"

        register_protocol("test_proto", test_factory)

        protocol = create_protocol("test_proto", {"url": "http://example.com"})

        assert protocol == "protocol_for_http://example.com"

    def test_create_unknown_protocol(self):
        """Test error when creating unknown protocol."""
        clear_registry()

        with pytest.raises(ValueError, match="not registered"):
            create_protocol("unknown", {})

    def test_get_available_protocols(self):
        """Test getting list of available protocols."""
        clear_registry()

        register_protocol("proto1", lambda c: None)
        register_protocol("proto2", lambda c: None)

        registry = get_registry()
        available = registry.list_protocols()

        assert "proto1" in available
        assert "proto2" in available
        assert len(available) >= 2

    def test_duplicate_registration_warning(self):
        """Test that duplicate registration raises error."""
        clear_registry()

        register_protocol("dup_test", lambda c: "v1")

        # Second registration should raise ValueError
        with pytest.raises(ValueError, match="already registered"):
            register_protocol("dup_test", lambda c: "v2")

    def test_clear_registry(self):
        """Test clearing the registry."""
        clear_registry()

        register_protocol("temp", lambda c: None)
        registry = get_registry()
        assert "temp" in registry._factories

        clear_registry()
        assert len(registry._factories) == 0

    def test_built_in_protocols_registered(self):
        """Test that built-in protocols are registered on import."""
        # Import triggers registration

        registry = get_registry()
        available = registry.list_protocols()

        # These should all be registered
        assert "ogc_features" in available
        assert "wcs" in available
        assert "wfs" in available
        assert "wmts" in available
