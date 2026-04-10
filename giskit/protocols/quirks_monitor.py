"""Quirks monitoring and logging utilities.

Track which quirks are being applied and provide debugging information.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from giskit.protocols.quirks import ProtocolQuirks

# Configure logger
logger = logging.getLogger("giskit.quirks")


@dataclass
class QuirkUsage:
    """Track usage statistics for a specific quirk."""

    provider: str
    protocol: str
    quirk_type: str
    applied_count: int = 0
    last_applied: Optional[datetime] = None
    first_applied: Optional[datetime] = None

    def record_application(self):
        """Record that this quirk was applied."""
        self.applied_count += 1
        now = datetime.now()
        self.last_applied = now
        if self.first_applied is None:
            self.first_applied = now


class QuirksMonitor:
    """Monitor and track quirk usage across the application.

    This helps identify which quirks are most commonly used and
    can help with debugging API issues.

    Examples:
        >>> monitor = QuirksMonitor()
        >>> monitor.record_quirk_applied("pdok", "ogc-features", "format_param")
        >>> stats = monitor.get_statistics()
        >>> print(stats["pdok"]["ogc-features"]["format_param"].applied_count)
        1
    """

    def __init__(self):
        """Initialize quirks monitor."""
        self._usage: dict[str, dict[str, dict[str, QuirkUsage]]] = defaultdict(
            lambda: defaultdict(dict)
        )
        self._enabled = True

    def record_quirk_applied(self, provider: str, protocol: str, quirk_type: str):
        """Record that a quirk was applied.

        Args:
            provider: Provider name (e.g., "pdok")
            protocol: Protocol name (e.g., "ogc-features")
            quirk_type: Type of quirk (e.g., "format_param")
        """
        if not self._enabled:
            return

        # Get or create usage record
        if quirk_type not in self._usage[provider][protocol]:
            self._usage[provider][protocol][quirk_type] = QuirkUsage(
                provider=provider, protocol=protocol, quirk_type=quirk_type
            )

        # Record application
        usage = self._usage[provider][protocol][quirk_type]
        usage.record_application()

        # Log at debug level
        logger.debug(
            f"Applied quirk: {provider}/{protocol}/{quirk_type} (count: {usage.applied_count})"
        )

    def get_statistics(self) -> dict:
        """Get usage statistics for all quirks.

        Returns:
            Nested dict: provider -> protocol -> quirk_type -> QuirkUsage
        """
        return dict(self._usage)

    def get_provider_stats(self, provider: str) -> dict[str, dict[str, QuirkUsage]]:
        """Get statistics for a specific provider.

        Args:
            provider: Provider name

        Returns:
            Dict of protocol -> quirk_type -> QuirkUsage
        """
        return dict(self._usage.get(provider, {}))

    def get_most_used_quirks(self, limit: int = 10) -> list[QuirkUsage]:
        """Get the most frequently used quirks.

        Args:
            limit: Maximum number of results

        Returns:
            List of QuirkUsage sorted by applied_count (descending)
        """
        all_quirks = []
        for provider_data in self._usage.values():
            for protocol_data in provider_data.values():
                all_quirks.extend(protocol_data.values())

        # Sort by count
        all_quirks.sort(key=lambda x: x.applied_count, reverse=True)
        return all_quirks[:limit]

    def reset(self):
        """Reset all statistics."""
        self._usage.clear()
        logger.info("Quirks monitor statistics reset")

    def disable(self):
        """Disable monitoring (for performance)."""
        self._enabled = False
        logger.info("Quirks monitoring disabled")

    def enable(self):
        """Enable monitoring."""
        self._enabled = True
        logger.info("Quirks monitoring enabled")

    def print_report(self):
        """Print a human-readable report of quirk usage."""
        print("\n" + "=" * 70)
        print("QUIRKS USAGE REPORT")
        print("=" * 70)

        if not self._usage:
            print("No quirks have been applied yet.")
            return

        for provider, protocols in self._usage.items():
            print(f"\nProvider: {provider}")
            print("-" * 70)

            for protocol, quirks in protocols.items():
                print(f"  Protocol: {protocol}")

                for quirk_type, usage in quirks.items():
                    print(f"    {quirk_type}:")
                    print(f"      Applied: {usage.applied_count} times")
                    if usage.first_applied:
                        print(f"      First:   {usage.first_applied.isoformat()}")
                    if usage.last_applied:
                        print(f"      Last:    {usage.last_applied.isoformat()}")

        print("\nTop 5 Most Used Quirks:")
        print("-" * 70)
        for i, usage in enumerate(self.get_most_used_quirks(5), 1):
            print(
                f"{i}. {usage.provider}/{usage.protocol}/{usage.quirk_type} "
                f"({usage.applied_count} times)"
            )
        print("=" * 70 + "\n")


# Global monitor instance
_global_monitor = QuirksMonitor()


def get_monitor() -> QuirksMonitor:
    """Get the global quirks monitor instance.

    Returns:
        Global QuirksMonitor instance
    """
    return _global_monitor


def log_quirk_application(quirks: ProtocolQuirks, provider: str, protocol: str, operation: str):
    """Log which quirks were applied for an operation.

    Args:
        quirks: ProtocolQuirks instance
        provider: Provider name
        protocol: Protocol name
        operation: Operation being performed (e.g., "get_capabilities")
    """
    monitor = get_monitor()

    # Track which quirks are active
    if quirks.requires_trailing_slash:
        monitor.record_quirk_applied(provider, protocol, "trailing_slash")

    if quirks.require_format_param:
        monitor.record_quirk_applied(provider, protocol, "format_param")

    if quirks.max_features_limit:
        monitor.record_quirk_applied(provider, protocol, "max_features_limit")

    if quirks.custom_timeout:
        monitor.record_quirk_applied(provider, protocol, "custom_timeout")

    if quirks.custom_headers:
        monitor.record_quirk_applied(provider, protocol, "custom_headers")

    # Log summary at debug level
    active_quirks = []
    if quirks.requires_trailing_slash:
        active_quirks.append("trailing_slash")
    if quirks.require_format_param:
        active_quirks.append(
            f"format_param({quirks.format_param_name}={quirks.format_param_value})"
        )
    if quirks.max_features_limit:
        active_quirks.append(f"max_limit={quirks.max_features_limit}")
    if quirks.custom_timeout:
        active_quirks.append(f"timeout={quirks.custom_timeout}s")
    if quirks.custom_headers:
        active_quirks.append(f"headers={len(quirks.custom_headers)}")

    if active_quirks:
        logger.debug(
            f"{provider}/{protocol}.{operation} - Active quirks: {', '.join(active_quirks)}"
        )
    else:
        logger.debug(f"{provider}/{protocol}.{operation} - No quirks applied")
