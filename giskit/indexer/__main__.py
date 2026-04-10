#!/usr/bin/env python3
"""CLI tool for PDOK service index monitoring and maintenance.

Usage:
    # Check all services
    python -m giskit.indexer check-all

    # Check specific service
    python -m giskit.indexer check bgt

    # Discover new services
    python -m giskit.indexer discover

    # Generate full report
    python -m giskit.indexer report

    # Generate report and save to file
    python -m giskit.indexer report --output report.txt
"""

import argparse
import asyncio
import sys
from pathlib import Path

from giskit.config.loader import load_services
from giskit.indexer.monitor import PDOKServiceMonitor


async def cmd_check_all_async(args):
    """Check health of all PDOK services."""
    monitor = PDOKServiceMonitor(timeout=args.timeout)
    results = await monitor.check_all_services()

    print("\n" + "=" * 80)
    print("HEALTH CHECK COMPLETE")
    print("=" * 80)
    print(f"Healthy:   {len(results['healthy'])}")
    print(f"Unhealthy: {len(results['unhealthy'])}")
    print(f"Warnings:  {len(results['warnings'])}")

    if results["unhealthy"]:
        print("\n⚠️  ATTENTION: Some services are unhealthy!")
        print("Run with --report to see details")
        return 1

    return 0


def cmd_check_all(args):
    """Wrapper for async cmd_check_all."""
    return asyncio.run(cmd_check_all_async(args))


async def cmd_check_one_async(args):
    """Check health of a single service."""
    # Load PDOK services from config
    pdok_services = load_services("pdok")

    if args.service_id not in pdok_services:
        print(f"Error: Unknown service '{args.service_id}'")
        print(f"Available services: {', '.join(sorted(pdok_services.keys()))}")
        return 1

    monitor = PDOKServiceMonitor(timeout=args.timeout)
    result = await monitor.check_service_health(args.service_id, pdok_services[args.service_id])

    print(f"\nService: {args.service_id}")
    print(f"Status:  {result['status']}")

    if result.get("collections_found"):
        print(f"Collections: {result['collections_found']}")

    if result.get("response_time"):
        print(f"Response time: {result['response_time']:.2f}s")

    if result.get("error"):
        print(f"Error: {result['error']}")
        return 1

    return 0


def cmd_check_one(args):
    """Wrapper for async cmd_check_one."""
    return asyncio.run(cmd_check_one_async(args))


def cmd_discover(args):
    """Discover new PDOK services."""
    monitor = PDOKServiceMonitor(timeout=args.timeout)
    discovered = monitor.discover_new_services()

    if discovered:
        print(f"\n✓ Found {len(discovered)} new services!")
        print("\nAdd these to config/providers/pdok/ogc-features.yml:")
        print("-" * 80)

        for svc in discovered:
            # Extract service ID from URL
            url_parts = svc["url"].rstrip("/").split("/")
            service_id = "_".join(url_parts[-3:-1])  # e.g., "bgt_ogc"

            print(
                f"""
    "{service_id}": {{
        "url": "{svc["url"]}",
        "title": "TODO: Add title",
        "category": "TODO: Add category",
        "description": "TODO: Add description",
        "keywords": ["TODO"],
    }},"""
            )
    else:
        print("\n✓ No new services found - index is up to date!")

    return 0


async def cmd_report_async(args):
    """Generate comprehensive health report."""
    monitor = PDOKServiceMonitor(timeout=args.timeout)

    # Run all checks
    print("Checking all services...")
    await monitor.check_all_services()

    print("\nDiscovering new services...")
    monitor.discover_new_services()

    # Generate report
    output_path = Path(args.output) if args.output else None
    report = monitor.generate_report(output_path)

    if not args.output:
        print("\n" + report)

    # Return non-zero if there are issues
    has_issues = (
        len(monitor.results["unhealthy"]) > 0
        or len(monitor.results["warnings"]) > 0
        or len(monitor.results["discovered"]) > 0
    )

    return 1 if has_issues else 0


def cmd_report(args):
    """Wrapper for async cmd_report."""
    return asyncio.run(cmd_report_async(args))


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="PDOK Service Index Monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--timeout", type=float, default=10.0, help="Request timeout in seconds (default: 10.0)"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # check-all command
    parser_check_all = subparsers.add_parser(
        "check-all", help="Check health of all registered services"
    )
    parser_check_all.set_defaults(func=cmd_check_all)

    # check command (single service)
    parser_check = subparsers.add_parser("check", help="Check health of a specific service")
    parser_check.add_argument("service_id", help="Service ID (e.g., bgt, bag)")
    parser_check.set_defaults(func=cmd_check_one)

    # discover command
    parser_discover = subparsers.add_parser(
        "discover", help="Discover new PDOK services not in index"
    )
    parser_discover.set_defaults(func=cmd_discover)

    # report command
    parser_report = subparsers.add_parser("report", help="Generate comprehensive health report")
    parser_report.add_argument(
        "--output", "-o", help="Save report to file (default: print to stdout)"
    )
    parser_report.set_defaults(func=cmd_report)

    args = parser.parse_args()

    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        return 130
    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        if "--debug" in sys.argv:
            raise
        return 1


if __name__ == "__main__":
    sys.exit(main())
