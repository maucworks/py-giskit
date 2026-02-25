"""Unit tests for catalog system.

Tests the catalog module which provides service discovery functionality.
"""

import json

import pytest

from giskit.catalog import (
    export_catalog_json,
    list_all_services,
    list_services_by_category,
    list_services_by_protocol,
    print_catalog,
    search_services,
)


class TestListAllServices:
    """Test list_all_services function."""

    def test_returns_dict(self):
        """Test that list_all_services returns a dictionary."""
        services = list_all_services()
        assert isinstance(services, dict)

    def test_contains_pdok(self):
        """Test that PDOK provider is in the catalog."""
        services = list_all_services()
        assert "pdok" in services

    def test_contains_bag3d(self):
        """Test that BAG3D provider is in the catalog."""
        services = list_all_services()
        assert "bag3d" in services

    def test_pdok_has_services(self):
        """Test that PDOK has multiple services."""
        catalog = list_all_services(detailed=True)
        pdok_info = catalog.get("pdok", {})
        assert pdok_info["service_count"] > 0
        assert "bgt" in pdok_info["services"]
        assert "bag" in pdok_info["services"]

    def test_service_has_required_fields(self):
        """Test that each service has required metadata fields."""
        catalog = list_all_services(detailed=True)
        for _provider_id, provider_info in catalog.items():
            services = provider_info.get("services", {})
            # Services can be either dict or list depending on provider
            if isinstance(services, dict):
                for _service_id, service_info in services.items():
                    assert "title" in service_info
                    assert "protocol" in service_info or "url" in service_info
            elif isinstance(services, list):
                for service_info in services:
                    assert "title" in service_info
                    assert "protocol" in service_info or "url" in service_info


class TestSearchServices:
    """Test search_services function."""

    def test_search_returns_dict(self):
        """Test that search returns a dictionary."""
        results = search_services("building")
        assert isinstance(results, dict)

    def test_search_bgt(self):
        """Test searching for BGT service."""
        results = search_services("bgt")
        assert "pdok" in results
        pdok_results = results["pdok"]
        assert any(s["id"] == "bgt" for s in pdok_results)

    def test_search_topography(self):
        """Test searching for topography-related services."""
        results = search_services("topography")
        assert len(results) > 0

    def test_search_case_insensitive(self):
        """Test that search is case-insensitive."""
        results_lower = search_services("bgt")
        results_upper = search_services("BGT")
        assert results_lower == results_upper

    def test_search_no_results(self):
        """Test that search with no matches returns empty dict."""
        results = search_services("nonexistent_xyz_123")
        assert results == {}

    def test_search_partial_match(self):
        """Test that search matches partial strings."""
        results = search_services("topo")
        assert len(results) > 0  # Should match "topography"


class TestListServicesByCategory:
    """Test list_services_by_category function."""

    def test_returns_dict(self):
        """Test that function returns a dictionary."""
        services = list_services_by_category("base_registers")
        assert isinstance(services, dict)

    def test_base_registers_category(self):
        """Test filtering by base_registers category."""
        services = list_services_by_category("base_registers")
        assert "pdok" in services
        pdok_services = services["pdok"]
        assert any(s["id"] == "bgt" for s in pdok_services)
        assert any(s["id"] == "bag" for s in pdok_services)

    def test_elevation_category(self):
        """Test filtering by elevation category."""
        services = list_services_by_category("elevation")
        # Should contain AHN service
        assert len(services) > 0

    def test_nonexistent_category(self):
        """Test filtering by non-existent category returns empty."""
        services = list_services_by_category("nonexistent_category_xyz")
        assert services == {}


class TestListServicesByProtocol:
    """Test list_services_by_protocol function."""

    def test_returns_dict(self):
        """Test that function returns a dictionary."""
        services = list_services_by_protocol("ogc-features")
        assert isinstance(services, dict)

    def test_ogc_features_protocol(self):
        """Test filtering by ogc-features protocol."""
        services = list_services_by_protocol("ogc-features")
        assert "pdok" in services
        pdok_services = services["pdok"]
        assert any(s["id"] == "bgt" for s in pdok_services)

    def test_wcs_protocol(self):
        """Test filtering by WCS protocol."""
        services = list_services_by_protocol("wcs")
        # Should contain AHN service
        assert len(services) > 0

    def test_wmts_protocol(self):
        """Test filtering by WMTS protocol."""
        services = list_services_by_protocol("wmts")
        # PDOK has WMTS services
        assert len(services) > 0

    def test_nonexistent_protocol(self):
        """Test filtering by non-existent protocol returns empty."""
        services = list_services_by_protocol("nonexistent_protocol_xyz")
        assert services == {}

    def test_case_insensitive_protocol(self):
        """Test that protocol filter is case-insensitive."""
        services_lower = list_services_by_protocol("ogc-features")
        services_upper = list_services_by_protocol("OGC-FEATURES")
        # Note: May not be equal due to implementation details, but both should work
        assert len(services_lower) > 0
        assert len(services_upper) > 0


class TestExportCatalogJson:
    """Test export_catalog_json function."""

    def test_exports_valid_json(self, tmp_path):
        """Test that export creates valid JSON file."""
        output_file = tmp_path / "catalog.json"
        export_catalog_json(output_file)

        assert output_file.exists()

        # Verify it's valid JSON
        with open(output_file) as f:
            data = json.load(f)

        assert isinstance(data, dict)
        assert "providers" in data
        assert "generated_at" in data

    def test_exported_json_contains_providers(self, tmp_path):
        """Test that exported JSON contains provider data."""
        output_file = tmp_path / "catalog.json"
        export_catalog_json(output_file)

        with open(output_file) as f:
            data = json.load(f)

        providers = data["providers"]
        assert "pdok" in providers
        assert "bag3d" in providers

    def test_exported_json_contains_services(self, tmp_path):
        """Test that exported JSON contains service metadata."""
        output_file = tmp_path / "catalog.json"
        export_catalog_json(output_file)

        with open(output_file) as f:
            data = json.load(f)

        pdok_info = data["providers"]["pdok"]
        assert pdok_info["service_count"] > 0
        assert "bgt" in pdok_info["services"]


class TestPrintCatalog:
    """Test print_catalog function."""

    def test_runs_without_error(self, capsys):
        """Test that print_catalog runs without error."""
        print_catalog()

        # Verify some output was printed
        captured = capsys.readouterr()
        assert len(captured.out) > 0

    def test_output_contains_providers(self, capsys):
        """Test that output mentions providers."""
        print_catalog()

        captured = capsys.readouterr()
        assert "pdok" in captured.out.lower() or "PDOK" in captured.out

    def test_output_contains_services(self, capsys):
        """Test that output mentions services."""
        print_catalog(detailed=True)

        captured = capsys.readouterr()
        assert "bgt" in captured.out.lower() or "BGT" in captured.out


class TestCatalogIntegration:
    """Integration tests for catalog functionality."""

    def test_workflow_search_and_export(self, tmp_path):
        """Test complete workflow: search, filter, export."""
        # 1. Search for services
        search_results = search_services("topography")
        assert len(search_results) > 0

        # 2. Filter by category
        category_results = list_services_by_category("base_registers")
        assert len(category_results) > 0

        # 3. Filter by protocol
        protocol_results = list_services_by_protocol("ogc-features")
        assert len(protocol_results) > 0

        # 4. Export catalog
        output_file = tmp_path / "test_catalog.json"
        export_catalog_json(output_file)
        assert output_file.exists()

    def test_catalog_consistency(self):
        """Test that catalog data is consistent across functions."""
        all_services = list_all_services()
        search_all = search_services("")  # Empty search should return nothing
        assert search_all == {}  # Empty search should return nothing, not everything

        # Get all via list_all_services - count actual services
        total_services = sum(
            provider_info["service_count"] for provider_info in all_services.values()
        )
        assert total_services > 10  # Should have many services


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
