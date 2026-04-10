"""
Schema adapters for different IFC versions.

Provides abstraction layer for schema-specific differences (IFC2X3, IFC4, IFC4X3).
"""

from typing import Any, Tuple

import ifcopenshell
import ifcopenshell.api


def sanitize_ifc_name(name: str) -> str:
    """Sanitize IFC name to avoid Blender crash.

    Blender's BLI_string_split_name_number parses the suffix after the last dot
    as an integer using std::stoi(). This throws std::out_of_range if:
    1. Suffix is non-numeric (std::invalid_argument)
    2. Suffix is too large for 32-bit int (std::out_of_range)

    SIMPLIFIED APPROACH: Replace ALL dots with underscores to completely
    avoid the int parsing issue. Names like "NL.IMBAG.Pand.123" become "NL_IMBAG_Pand_123".

    Args:
        name: Original name

    Returns:
        Sanitized name
    """
    name = name.replace(",", "_").replace(" ", "_").replace("-", "_")
    name = name.replace(".", "_")

    return name


def clean_ifc_name(name: str) -> str:
    """Clean IFC name - replace dots/commas/special chars with underscores.

    This removes ALL dots that might trigger Blender's name parsing.
    Use for style names, property names, etc.

    Args:
        name: Original name

    Returns:
        Cleaned name with only alphanumeric and underscores
    """
    name = name.replace(".", "_")
    name = name.replace(",", "_").replace(" ", "_").replace("-", "_")

    while "__" in name:
        name = name.replace("__", "_")

    return name.strip("_")


class SchemaAdapter:
    """Base class for IFC schema adapters."""

    def __init__(self, ifc_file: Any):
        self.ifc = ifc_file
        self.schema = ifc_file.schema

    def create_road(self, name: str) -> Tuple[Any, str]:
        """Create a road element.

        Returns:
            (entity, assignment_method) where assignment_method is 'aggregate' or 'container'
        """
        raise NotImplementedError

    def create_bridge(self, name: str) -> Tuple[Any, str]:
        """Create a bridge element."""
        raise NotImplementedError

    def create_railway(self, name: str) -> Tuple[Any, str]:
        """Create a railway element."""
        raise NotImplementedError

    def assign_to_site(self, site: Any, element: Any, method: str) -> None:
        """Assign element to site using the specified method.

        Args:
            site: IfcSite entity
            element: Element to assign
            method: 'aggregate' or 'container'
        """
        if method == "aggregate":
            ifcopenshell.api.run(
                "aggregate.assign_object", self.ifc, relating_object=site, products=[element]
            )
        elif method == "container":
            ifcopenshell.api.run(
                "spatial.assign_container", self.ifc, relating_structure=site, products=[element]
            )
        else:
            raise ValueError(f"Unknown assignment method: {method}")


class IFC4Adapter(SchemaAdapter):
    """Adapter for IFC4 schema."""

    def create_road(self, name: str) -> Tuple[Any, str]:
        """Create road as IfcCivilElement in IFC4."""
        safe_name = sanitize_ifc_name(name)
        road = ifcopenshell.api.run(
            "root.create_entity", self.ifc, ifc_class="IfcCivilElement", name=safe_name
        )
        road.ObjectType = "Road"
        return road, "container"

    def create_bridge(self, name: str) -> Tuple[Any, str]:
        """Create bridge as IfcCivilElement in IFC4."""
        safe_name = sanitize_ifc_name(name)
        bridge = ifcopenshell.api.run(
            "root.create_entity", self.ifc, ifc_class="IfcCivilElement", name=safe_name
        )
        bridge.ObjectType = "Bridge"
        return bridge, "container"

    def create_railway(self, name: str) -> Tuple[Any, str]:
        """Create railway as IfcCivilElement in IFC4."""
        safe_name = sanitize_ifc_name(name)
        railway = ifcopenshell.api.run(
            "root.create_entity", self.ifc, ifc_class="IfcCivilElement", name=safe_name
        )
        railway.ObjectType = "Railway"
        return railway, "container"


class IFC4X3Adapter(SchemaAdapter):
    """Adapter for IFC4X3 schema."""

    def create_road(self, name: str) -> Tuple[Any, str]:
        """Create road as IfcRoad in IFC4X3."""
        safe_name = sanitize_ifc_name(name)
        road = ifcopenshell.api.run(
            "root.create_entity", self.ifc, ifc_class="IfcRoad", name=safe_name
        )
        return road, "aggregate"

    def create_bridge(self, name: str) -> Tuple[Any, str]:
        """Create bridge as IfcBridge in IFC4X3."""
        safe_name = sanitize_ifc_name(name)
        bridge = ifcopenshell.api.run(
            "root.create_entity", self.ifc, ifc_class="IfcBridge", name=safe_name
        )
        return bridge, "aggregate"

    def create_railway(self, name: str) -> Tuple[Any, str]:
        """Create railway as IfcRailway in IFC4X3."""
        safe_name = sanitize_ifc_name(name)
        railway = ifcopenshell.api.run(
            "root.create_entity", self.ifc, ifc_class="IfcRailway", name=safe_name
        )
        return railway, "aggregate"


class IFC2X3Adapter(SchemaAdapter):
    """Adapter for IFC2X3 schema.

    IFC2X3 lacks civil infrastructure entities (IfcRoad, IfcBridge, IfcRailway)
    and IfcCivilElement/IfcGeographicElement. We use IfcBuildingElementProxy
    with ObjectType for classification.
    """

    def create_road(self, name: str) -> Tuple[Any, str]:
        """Create road as IfcBuildingElementProxy in IFC2X3."""
        safe_name = sanitize_ifc_name(name)
        road = ifcopenshell.api.run(
            "root.create_entity", self.ifc, ifc_class="IfcBuildingElementProxy", name=safe_name
        )
        road.ObjectType = "Road"
        return road, "container"

    def create_bridge(self, name: str) -> Tuple[Any, str]:
        """Create bridge as IfcBuildingElementProxy in IFC2X3."""
        safe_name = sanitize_ifc_name(name)
        bridge = ifcopenshell.api.run(
            "root.create_entity", self.ifc, ifc_class="IfcBuildingElementProxy", name=safe_name
        )
        bridge.ObjectType = "Bridge"
        return bridge, "container"

    def create_railway(self, name: str) -> Tuple[Any, str]:
        """Create railway as IfcBuildingElementProxy in IFC2X3."""
        safe_name = sanitize_ifc_name(name)
        railway = ifcopenshell.api.run(
            "root.create_entity", self.ifc, ifc_class="IfcBuildingElementProxy", name=safe_name
        )
        railway.ObjectType = "Railway"
        return railway, "container"


def get_schema_adapter(ifc_file: Any) -> SchemaAdapter:
    """Get appropriate schema adapter for IFC file.

    Args:
        ifc_file: ifcopenshell file instance

    Returns:
        SchemaAdapter instance for the file's schema
    """
    schema = ifc_file.schema

    if schema.startswith("IFC4X3"):
        return IFC4X3Adapter(ifc_file)
    elif schema == "IFC4":
        return IFC4Adapter(ifc_file)
    elif schema == "IFC2X3":
        return IFC2X3Adapter(ifc_file)
    else:
        raise ValueError(f"Unsupported IFC schema: {schema}")
