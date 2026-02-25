"""Protocol registry for dynamic protocol instantiation.

This module provides a registry pattern for protocols, eliminating the need for
long if/elif chains when creating protocol instances. Each protocol can register
itself with a factory function.

Example:
    >>> # Register a protocol
    >>> def create_wfs(config):
    ...     return WFSProtocol(config["url"])
    >>> registry.register("wfs", create_wfs)
    >>>
    >>> # Create protocol instance
    >>> protocol = registry.create("wfs", {"url": "https://..."})
"""

from typing import Any, Callable, Protocol as TypingProtocol

from giskit.protocols.base import Protocol

# Type alias for protocol factory functions
ProtocolFactory = Callable[[dict[str, Any]], Protocol]


class ProtocolRegistry:
    """Registry for protocol factories.

    Maintains a mapping of protocol names to factory functions that create
    protocol instances. This eliminates the need for if/elif chains when
    instantiating protocols dynamically.
    """

    def __init__(self) -> None:
        """Initialize empty protocol registry."""
        self._factories: dict[str, ProtocolFactory] = {}

    def register(self, name: str, factory: ProtocolFactory) -> None:
        """Register a protocol factory.

        Args:
            name: Protocol identifier (e.g., "ogc-features", "wcs", "wmts")
            factory: Function that creates protocol instances from config dict

        Raises:
            ValueError: If protocol name already registered
        """
        if name in self._factories:
            raise ValueError(f"Protocol '{name}' already registered")

        self._factories[name] = factory

    def create(self, name: str, config: dict[str, Any]) -> Protocol:
        """Create a protocol instance.

        Args:
            name: Protocol identifier
            config: Configuration dictionary for the protocol

        Returns:
            Protocol instance created by the registered factory

        Raises:
            ValueError: If protocol not registered
        """
        if name not in self._factories:
            available = ", ".join(self._factories.keys())
            raise ValueError(f"Protocol '{name}' not registered. Available protocols: {available}")

        return self._factories[name](config)

    def is_registered(self, name: str) -> bool:
        """Check if a protocol is registered.

        Args:
            name: Protocol identifier

        Returns:
            True if protocol is registered, False otherwise
        """
        return name in self._factories

    def list_protocols(self) -> list[str]:
        """Get list of registered protocol names.

        Returns:
            List of protocol identifiers
        """
        return list(self._factories.keys())


# Global registry instance
_registry = ProtocolRegistry()


def register_protocol(name: str, factory: ProtocolFactory) -> None:
    """Register a protocol factory in the global registry.

    Args:
        name: Protocol identifier (e.g., "ogc-features", "wcs", "wmts")
        factory: Function that creates protocol instances from config dict

    Example:
        >>> def create_wfs(config):
        ...     return WFSProtocol(config["url"])
        >>> register_protocol("wfs", create_wfs)
    """
    _registry.register(name, factory)


def create_protocol(name: str, config: dict[str, Any]) -> Protocol:
    """Create a protocol instance from the global registry.

    Args:
        name: Protocol identifier
        config: Configuration dictionary for the protocol

    Returns:
        Protocol instance

    Raises:
        ValueError: If protocol not registered

    Example:
        >>> protocol = create_protocol("wfs", {"url": "https://..."})
    """
    return _registry.create(name, config)


def get_registry() -> ProtocolRegistry:
    """Get the global protocol registry.

    Returns:
        Global ProtocolRegistry instance
    """
    return _registry


def clear_registry() -> None:
    """Clear all registered protocols from the global registry.

    This is primarily used for testing to ensure a clean state.

    Example:
        >>> clear_registry()  # Reset registry for tests
        >>> register_protocol("test", lambda c: TestProtocol())
    """
    _registry._factories.clear()
