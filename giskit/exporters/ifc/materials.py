"""
Materials manager for IFC export.

Loads color and material configurations from YAML files and provides
lookup functions for assigning colors and materials to IFC entities.
"""

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

from .schema_adapter import clean_ifc_name


class MaterialsManager:
    """Manages colors and materials from YAML configuration."""

    def __init__(
        self,
        colors_path: Optional[Path] = None,
        layer_mappings_path: Optional[Path] = None,
        color_overrides: Optional[dict[str, dict[str, list[float]]]] = None,
    ):
        """Initialize materials manager.

        Args:
            colors_path: Path to colors.yml config file
            layer_mappings_path: Path to layer_mappings.yml config file
            color_overrides: Recipe-level color overrides per layer
                Format: {"layer_name": {"surface_type": [R, G, B]}}
        """
        # Default to config directory (giskit/giskit/config/export/)
        if colors_path is None:
            # __file__ is .../giskit/giskit/exporters/ifc/materials.py
            # Need to go up to giskit/giskit/config/export/
            config_dir = Path(__file__).parent.parent.parent / "config" / "export"
            colors_path = config_dir / "colors.yml"

        if layer_mappings_path is None:
            config_dir = Path(__file__).parent.parent.parent / "config" / "export"
            layer_mappings_path = config_dir / "layer_mappings.yml"

        # Load YAML configs
        with open(colors_path, "r") as f:
            self.colors = yaml.safe_load(f)

        with open(layer_mappings_path, "r") as f:
            mappings_data = yaml.safe_load(f)
            self.layer_mappings = mappings_data.get("layer_mappings", {})

        # Store color overrides from recipe
        self.color_overrides = color_overrides or {}

    def get_color(
        self, layer_name: str, feature_data: Dict[str, Any]
    ) -> Tuple[float, float, float, float]:
        """Get RGB color for a feature based on its layer and attributes.

        Priority order:
        1. Recipe color overrides (from IFCExportConfig.layer_colors)
        2. YAML color configuration (colors.yml)
        3. Default gray

        Args:
            layer_name: Name of the GeoPackage layer
            feature_data: Feature attributes (GeoDataFrame row as dict)

        Returns:
            RGBA tuple (r, g, b, a) in 0-1 range
        """
        # Normalize layer name for config lookup
        normalized_layer = self._normalize_layer_name(layer_name)

        # Check for recipe-level color overrides FIRST
        if layer_name in self.color_overrides:
            override_colors = self.color_overrides[layer_name]

            # For BAG3D: check surface_type
            if layer_name.startswith("bag3d") and "surface_type" in feature_data:
                surface_type = feature_data.get("surface_type", "").lower()
                if surface_type in override_colors:
                    return self._ensure_rgba(override_colors[surface_type])

            # Check for default override
            if "default" in override_colors:
                return self._ensure_rgba(override_colors["default"])

        # Fall back to YAML color config (use normalized name)
        layer_colors = self.colors.get(normalized_layer, {})

        # Special handling for BAG3D surface classification
        if layer_name.startswith("bag3d") and "surface_type" in feature_data:
            surface_type = feature_data.get("surface_type", "").lower()
            color = layer_colors.get(surface_type)
            if color:
                return self._ensure_rgba(color)

        # Get layer mapping to find color_attributes priority order
        layer_config = self.get_layer_config(layer_name)
        color_attributes = layer_config.get("color_attributes", [])

        # Try each color attribute in priority order
        for attr in color_attributes:
            if attr in feature_data:
                value = str(feature_data[attr]).lower()
                color = layer_colors.get(value)
                if color:
                    return self._ensure_rgba(color)

        # Fall back to default color
        default_color = layer_colors.get("default", [0.7, 0.7, 0.7])
        return self._ensure_rgba(default_color)

    def _ensure_rgba(self, color: list) -> Tuple[float, float, float, float]:
        """Ensure color is RGBA tuple.

        Args:
            color: RGB or RGBA list

        Returns:
            RGBA tuple (r, g, b, a)
        """
        if len(color) == 3:
            return (color[0], color[1], color[2], 1.0)
        elif len(color) == 4:
            return (color[0], color[1], color[2], color[3])
        else:
            return (0.7, 0.7, 0.7, 1.0)  # Default gray

    def get_material_name(self, layer_name: str, feature_data: Dict[str, Any]) -> str:
        """Get material name for a feature.

        Args:
            layer_name: Name of the GeoPackage layer
            feature_data: Feature attributes

        Returns:
            Material name string
        """
        # For BAG3D with surface classification
        if layer_name.startswith("bag3d") and "surface_type" in feature_data:
            surface_type = feature_data.get("surface_type", "default")
            return clean_ifc_name(f"BAG3D_{surface_type.upper()}")

        # For layers with specific attribute-based naming
        layer_config = self.get_layer_config(layer_name)
        color_attributes = layer_config.get("color_attributes", [])

        # Try to build name from first color attribute
        if color_attributes and color_attributes[0] in feature_data:
            attr_value = str(feature_data[color_attributes[0]])
            name = f"{layer_name.upper()}_{attr_value.upper()}"
            return clean_ifc_name(name)

        # Default material name
        return clean_ifc_name(f"{layer_name.upper()}_DEFAULT")

    def _normalize_layer_name(self, layer_name: str) -> str:
        """Normalize layer name by stripping common BGT suffixes.

        BGT layers often have suffixes like _vlak, _lijn, _punt, _kruinlijn.
        This method strips them to match base configuration keys.

        Args:
            layer_name: Raw layer name (e.g., 'bgt_kunstwerkdeel_vlak')

        Returns:
            Normalized layer name (e.g., 'bgt_kunstwerkdeel')
        """
        # Common BGT suffixes to strip
        suffixes = ["_vlak", "_lijn", "_punt", "_kruinlijn", "_multivlak", "_multipunt"]

        for suffix in suffixes:
            if layer_name.endswith(suffix):
                return layer_name[: -len(suffix)]

        return layer_name

    def get_layer_config(self, layer_name: str) -> Dict[str, Any]:
        """Get complete layer configuration.

        Tries exact match first, then normalized name (strips BGT suffixes).

        Args:
            layer_name: Name of the GeoPackage layer

        Returns:
            Layer configuration dict
        """
        # Try exact match first
        config = self.layer_mappings.get(layer_name)
        if config:
            return config

        # Try normalized name (strip suffixes like _vlak, _lijn, etc.)
        normalized = self._normalize_layer_name(layer_name)
        return self.layer_mappings.get(normalized, {})

    def get_ifc_class(self, layer_name: str, ifc_schema: str = "IFC4X3") -> str:
        """Get IFC class for a layer based on schema version.

        Args:
            layer_name: Name of the GeoPackage layer
            ifc_schema: IFC schema version (e.g., 'IFC2X3', 'IFC4', 'IFC4X3')

        Returns:
            IFC class name
        """
        layer_config = self.get_layer_config(layer_name)

        # IFC2X3 fallback - lacks IfcCivilElement, IfcGeographicElement, etc.
        if ifc_schema == "IFC2X3":
            # Check for explicit IFC2X3 fallback in config
            if "ifc_class_ifc2x3" in layer_config:
                return layer_config["ifc_class_ifc2x3"]

            ifc_class = layer_config.get("ifc_class", "IfcBuildingElementProxy")
            # Map IFC4+ entities to IFC2X3 equivalents
            ifc4_only_classes = {
                "IfcCivilElement",
                "IfcGeographicElement",
                "IfcRoad",
                "IfcBridge",
                "IfcRailway",
            }
            if ifc_class in ifc4_only_classes:
                return "IfcBuildingElementProxy"
            return ifc_class

        # IFC4 fallback
        if ifc_schema == "IFC4" and "ifc_class_fallback" in layer_config:
            return layer_config["ifc_class_fallback"]

        return layer_config.get("ifc_class", "IfcGeographicElement")

    def get_default_height(self, layer_name: str) -> float:
        """Get default extrusion height for a layer.

        Args:
            layer_name: Name of the GeoPackage layer

        Returns:
            Height in meters
        """
        layer_config = self.get_layer_config(layer_name)
        return layer_config.get("default_height", 0.1)

    def get_pset_config(self, layer_name: str) -> Tuple[str, list]:
        """Get property set configuration for a layer.

        Args:
            layer_name: Name of the GeoPackage layer

        Returns:
            Tuple of (pset_name, properties_list)
        """
        layer_config = self.get_layer_config(layer_name)
        pset_name = layer_config.get("pset_name", f"Pset.{layer_name}")
        pset_name = clean_ifc_name(pset_name)
        properties = layer_config.get("properties", [])
        return pset_name, properties

    def supports_surface_classification(self, layer_name: str) -> bool:
        """Check if layer supports surface classification (roof/wall/floor).

        Args:
            layer_name: Name of the GeoPackage layer

        Returns:
            True if surface classification enabled
        """
        layer_config = self.get_layer_config(layer_name)
        return layer_config.get("surface_classification", False)
