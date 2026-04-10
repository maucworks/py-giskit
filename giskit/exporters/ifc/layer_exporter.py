"""
Layer exporters for different GeoPackage layer types.

Generic plugin system that works with MaterialsManager and YAML configs.
"""

import logging
from typing import Any, Dict

import geopandas as gpd
import ifcopenshell
import ifcopenshell.api
from shapely.geometry import MultiPolygon, Polygon

from .geometry import (
    classify_surface,
    create_extruded_area_solid,
    create_faceted_brep,
    create_shape_representation,
    normalize_z_to_ground,
    polygon_3d_to_ifc_face,
    transform_to_relative,
)
from .materials import MaterialsManager
from .schema_adapter import SchemaAdapter, clean_ifc_name, sanitize_ifc_name

logger = logging.getLogger(__name__)


class LayerExporter:
    """Generic layer exporter that works with MaterialsManager configs."""

    def __init__(self, materials_manager: MaterialsManager):
        """Initialize exporter with materials manager.

        Args:
            materials_manager: MaterialsManager instance
        """
        self.materials = materials_manager
        self._material_cache: Dict[str, Any] = {}

    def export(
        self,
        layer_name: str,
        ifc_file: Any,
        site: Any,
        context: Any,
        schema_adapter: SchemaAdapter,
        db_path: str,
        ref_x: float,
        ref_y: float,
        normalize_z: bool = True,
    ) -> Dict[str, int]:
        """Export layer to IFC.

        Args:
            layer_name: Layer name in GeoPackage
            ifc_file: ifcopenshell file instance
            site: IfcSite entity
            context: IfcGeometricRepresentationContext
            schema_adapter: Schema adapter for version-specific logic
            db_path: Path to GeoPackage
            ref_x, ref_y: Reference point - geometry is always transformed relative to this
            normalize_z: Normalize 3D building Z coordinates to ground level

        Returns:
            Statistics dict (e.g., {'buildings': 3})
        """
        # Resolve container: features are assigned directly to site
        spatial_container = site
        # Get layer configuration
        layer_config = self.materials.get_layer_config(layer_name)
        if not layer_config:
            logger.warning("No configuration for layer %s, skipping", layer_name)
            return {}

        # Read GeoDataFrame
        gdf = gpd.read_file(db_path, layer=layer_name)

        # Detect if layer has 3D geometry
        is_3d = layer_name.startswith("bag3d")
        supports_surface_classification = self.materials.supports_surface_classification(layer_name)

        count = 0

        for _idx, row in gdf.iterrows():
            geom = row["geometry"]
            if geom is None or geom.is_empty:
                continue

            # Convert row to dict for materials manager
            feature_data = row.to_dict()

            # Transform geometry to be relative to reference point
            # NOTE: Vertex coordinates are ALWAYS relative to ref_x, ref_y
            # The 'relative' parameter only affects Site placement (0,0,0 vs RD coords)
            geom = transform_to_relative(geom, ref_x, ref_y)

            if is_3d and normalize_z:
                geom = normalize_z_to_ground(geom)

            # Create IFC entity
            entity = self._create_entity(
                layer_name, layer_config, feature_data, ifc_file, schema_adapter, site
            )

            # Create geometry representation
            if is_3d and supports_surface_classification:
                # BAG3D with surface classification
                self._create_3d_representation_with_surfaces(
                    entity, geom, ifc_file, context, site, layer_name, feature_data
                )
            elif is_3d:
                # BAG3D without surface classification
                self._create_3d_representation(
                    entity, geom, ifc_file, context, layer_name, feature_data
                )
            else:
                # 2D extruded geometry
                default_height = self.materials.get_default_height(layer_name)
                self._create_2d_representation(
                    entity, geom, ifc_file, context, layer_name, feature_data, default_height
                )

            # Add property set
            self._add_property_set(entity, layer_name, feature_data, ifc_file)

            # Assign to spatial container (zone or site)
            assignment_method = layer_config.get("assignment_method", "spatial")
            if assignment_method == "aggregate":
                ifcopenshell.api.run(
                    "aggregate.assign_object",
                    ifc_file,
                    relating_object=spatial_container,
                    products=[entity],
                )
            else:  # spatial / container
                ifcopenshell.api.run(
                    "spatial.assign_container",
                    ifc_file,
                    relating_structure=spatial_container,
                    products=[entity],
                )

            count += 1

        return {layer_name: count}

    def _create_entity(
        self,
        layer_name: str,
        layer_config: Dict,
        feature_data: Dict,
        ifc_file: Any,
        schema_adapter: SchemaAdapter,
        site: Any = None,
    ) -> Any:
        """Create IFC entity for a feature.

        Args:
            layer_name: Layer name
            layer_config: Layer configuration dict
            feature_data: Feature attributes
            ifc_file: IFC file instance
            schema_adapter: Schema adapter
            site: IfcSite entity (optional, used for placement)

        Returns:
            Created IFC entity
        """
        # Get IFC class
        ifc_class = self.materials.get_ifc_class(layer_name, ifc_file.schema)

        # Get name — prepend provider label so Blender outliner groups by provider
        provider = self._get_provider_label(layer_name)
        name_attr = layer_config.get("name_attribute")
        if name_attr and name_attr in feature_data:
            feature_name = sanitize_ifc_name(str(feature_data[name_attr]))
        else:
            feature_name = sanitize_ifc_name(f"{layer_name}.{id(feature_data)}")
        name = f"{provider} - {feature_name}"

        # Create entity
        entity = ifcopenshell.api.run(
            "root.create_entity", ifc_file, ifc_class=ifc_class, name=name
        )

        # CRITICAL: Set explicit ObjectPlacement at (0,0,0) relative to Site
        # This ensures consistent mesh origins in Blender/BIM viewers, especially
        # for large IFC files (>1000 meshes) where importers may otherwise place
        # mesh origins at the first vertex instead of the reference point.
        #
        # Context: In large export areas (e.g., radius=1000m), BlenderBIM/Bonsai
        # optimizes mesh origins for objects far from (0,0,0). Without explicit
        # placement, BAG3D building surfaces at dataset edges (~1km from origin)
        # get their mesh origin placed at their geometry location instead of the
        # common reference point, breaking rotation/scaling workflows.
        #
        # Solution: Explicitly set ObjectPlacement to (0,0,0) relative to Site.
        # This forces all meshes to share the same origin point, regardless of
        # their geometric location or the total number of objects in the file.
        if site and site.ObjectPlacement:
            entity.ObjectPlacement = self._create_placement_at_origin(ifc_file, site)

        return entity

    def _create_placement_at_origin(self, ifc_file: Any, site: Any) -> Any:
        """Create an IfcLocalPlacement at (0,0,0) relative to Site.

        This helper method creates an explicit placement at the origin to ensure
        consistent mesh origins in BIM viewers, particularly for large files.

        Args:
            ifc_file: IFC file instance
            site: IfcSite entity to use as placement parent

        Returns:
            IfcLocalPlacement at (0,0,0)
        """
        return ifc_file.createIfcLocalPlacement(
            PlacementRelTo=site.ObjectPlacement,
            RelativePlacement=ifc_file.createIfcAxis2Placement3D(
                Location=ifc_file.createIfcCartesianPoint((0.0, 0.0, 0.0)),
                Axis=None,  # Default Z-axis
                RefDirection=None,  # Default X-axis
            ),
        )

    def _create_2d_representation(
        self,
        entity: Any,
        geom: Any,
        ifc_file: Any,
        context: Any,
        layer_name: str,
        feature_data: Dict,
        height: float,
    ):
        """Create representation for 2D geometry (extruded)."""
        polygons = []
        if isinstance(geom, Polygon):
            polygons = [geom]
        elif isinstance(geom, MultiPolygon):
            polygons = list(geom.geoms)

        # Create material/style
        color = self.materials.get_color(layer_name, feature_data)
        material_name = self.materials.get_material_name(layer_name, feature_data)
        style = self._get_or_create_style(ifc_file, material_name, color)

        # Create solids
        solids = []
        for poly in polygons:
            if poly.is_valid and not poly.is_empty:
                solid = create_extruded_area_solid(ifc_file, poly, height)
                solids.append(solid)

        if not solids:
            return

        # Create shape representation
        rep = create_shape_representation(ifc_file, context, "SweptSolid", solids)

        # Assign style
        ifcopenshell.api.run(
            "style.assign_representation_styles", ifc_file, shape_representation=rep, styles=[style]
        )

        # Create product definition shape
        product_shape = ifc_file.createIfcProductDefinitionShape(None, None, [rep])
        entity.Representation = product_shape

    def _create_3d_representation(
        self,
        entity: Any,
        geom: Any,
        ifc_file: Any,
        context: Any,
        layer_name: str,
        feature_data: Dict,
    ):
        """Create representation for 3D geometry (no surface classification)."""
        polygons = []
        if isinstance(geom, Polygon):
            polygons = [geom]
        elif isinstance(geom, MultiPolygon):
            polygons = list(geom.geoms)

        # Create material/style
        color = self.materials.get_color(layer_name, feature_data)
        material_name = self.materials.get_material_name(layer_name, feature_data)
        style = self._get_or_create_style(ifc_file, material_name, color)

        # Create faces
        faces = []
        for poly in polygons:
            # Skip empty polygons
            if poly.is_empty:
                continue

            # For invalid polygons, check if they're vertical surfaces (walls)
            # Vertical surfaces are invalid in 2D but valid in 3D
            if not poly.is_valid:
                # Check if this is a vertical surface by examining Z coordinates
                coords = list(poly.exterior.coords)
                if len(coords) >= 4:  # Need at least 3 unique points + closure
                    z_values = [c[2] if len(c) > 2 else 0 for c in coords]
                    z_range = max(z_values) - min(z_values)

                    # If Z range is significant (>0.1m), it's likely a vertical surface
                    # Don't try to "fix" it with buffer(0) as that will make it empty
                    is_vertical = z_range > 0.1

                    if not is_vertical:
                        # Try to fix non-vertical invalid polygons
                        try:
                            poly = poly.buffer(0)
                        except Exception:
                            pass

                        # Skip if fixing made it empty
                        if poly.is_empty:
                            continue

            try:
                face = polygon_3d_to_ifc_face(ifc_file, poly)
                faces.append(face)
            except Exception as e:
                # Skip faces that can't be converted, but log for debugging
                logger.warning("Failed to create IFC face for polygon: %s", e)

        if not faces:
            return

        # Create B-rep
        brep = create_faceted_brep(ifc_file, faces)

        # Create shape representation
        rep = create_shape_representation(ifc_file, context, "Brep", [brep])

        # Assign style
        ifcopenshell.api.run(
            "style.assign_representation_styles", ifc_file, shape_representation=rep, styles=[style]
        )

        # Create product definition shape
        product_shape = ifc_file.createIfcProductDefinitionShape(None, None, [rep])
        entity.Representation = product_shape

    def _create_3d_representation_with_surfaces(
        self,
        entity: Any,
        geom: Any,
        ifc_file: Any,
        context: Any,
        site: Any,
        layer_name: str,
        feature_data: Dict,
    ):
        """Create representation for 3D geometry with surface classification.

        Creates separate IfcBuildingElementProxy child objects for each surface type
        (roof, wall, floor) to ensure proper display in Blender/BIM viewers.
        """
        polygons = []
        if isinstance(geom, Polygon):
            polygons = [geom]
        elif isinstance(geom, MultiPolygon):
            polygons = list(geom.geoms)

        # Create faces grouped by surface type
        faces_by_type = {"ROOF": [], "WALL": [], "FLOOR": []}

        for poly in polygons:
            # Skip empty polygons
            if poly.is_empty:
                continue

            # For invalid polygons, check if they're vertical surfaces (walls)
            # Vertical surfaces are invalid in 2D but valid in 3D
            if not poly.is_valid:
                # Check if this is a vertical surface by examining Z coordinates
                coords = list(poly.exterior.coords)
                if len(coords) >= 4:  # Need at least 3 unique points + closure
                    z_values = [c[2] if len(c) > 2 else 0 for c in coords]
                    z_range = max(z_values) - min(z_values)

                    # If Z range is significant (>0.1m), it's likely a vertical surface
                    # Don't try to "fix" it with buffer(0) as that will make it empty
                    is_vertical = z_range > 0.1

                    if not is_vertical:
                        # Try to fix non-vertical invalid polygons
                        try:
                            poly = poly.buffer(0)
                        except Exception:
                            pass

                        # Skip if fixing made it empty
                        if poly.is_empty:
                            continue

            try:
                surface_type = classify_surface(poly)
                face = polygon_3d_to_ifc_face(ifc_file, poly)
                faces_by_type[surface_type].append(face)
            except Exception as e:
                # Skip faces that can't be converted, but log for debugging
                logger.warning("Failed to create IFC face for polygon: %s", e)

        # Create separate representations for each surface type
        # NEW APPROACH: Create separate IfcBuildingElementProxy for each surface type
        # This ensures Blender/BIM tools show all surfaces correctly
        # Each surface type becomes a separate child object in the hierarchy

        created_elements = []

        for surface_type, faces in faces_by_type.items():
            if not faces:
                continue

            # Get color for this surface type
            surface_feature_data = feature_data.copy()
            surface_feature_data["surface_type"] = surface_type
            color = self.materials.get_color(layer_name, surface_feature_data)
            material_name = self.materials.get_material_name(layer_name, surface_feature_data)
            style = self._get_or_create_style(ifc_file, material_name, color)

            # Create B-rep for this surface type
            brep = create_faceted_brep(ifc_file, faces)

            # Create shape representation
            rep = create_shape_representation(ifc_file, context, "Brep", [brep])

            # Assign style
            ifcopenshell.api.run(
                "style.assign_representation_styles",
                ifc_file,
                shape_representation=rep,
                styles=[style],
            )

            # Create a child IfcBuildingElementProxy for this surface
            provider = self._get_provider_label(layer_name)
            element_name = f"{provider} - {sanitize_ifc_name(entity.Name)}"
            child_element = ifcopenshell.api.run(
                "root.create_entity",
                ifc_file,
                ifc_class="IfcBuildingElementProxy",
                name=element_name,
            )

            # Set predefined type to indicate what kind of surface this is
            child_element.ObjectType = surface_type

            # CRITICAL: Set explicit ObjectPlacement at (0,0,0) relative to Site
            # This ensures consistent mesh origins in Blender/BIM viewers, especially
            # for large IFC files (>1000 meshes) where importers may otherwise place
            # mesh origins at the first vertex instead of the reference point.
            #
            # Context: In large export areas (e.g., radius=1000m), BlenderBIM/Bonsai
            # optimizes mesh origins for objects far from (0,0,0). Without explicit
            # placement, BAG3D building surfaces at dataset edges (~1km from origin)
            # get their mesh origin placed at their geometry location instead of the
            # common reference point, breaking rotation/scaling workflows.
            #
            # Solution: Explicitly set ObjectPlacement to (0,0,0) relative to Site.
            # This forces all meshes to share the same origin point, regardless of
            # their geometric location or the total number of objects in the file.
            child_element.ObjectPlacement = self._create_placement_at_origin(ifc_file, site)

            # Assign representation to child element
            product_shape = ifc_file.createIfcProductDefinitionShape(None, None, [rep])
            child_element.Representation = product_shape

            # Add property set to child element with surface_type
            surface_feature_data_for_pset = surface_feature_data.copy()
            self._add_property_set(
                child_element, layer_name, surface_feature_data_for_pset, ifc_file
            )

            # Add child to site
            ifcopenshell.api.run(
                "spatial.assign_container",
                ifc_file,
                relating_structure=site,
                products=[child_element],
            )

            created_elements.append(child_element)

    def _add_property_set(self, entity: Any, layer_name: str, feature_data: Dict, ifc_file: Any):
        """Add property set to entity."""
        pset_name, properties = self.materials.get_pset_config(layer_name)

        # Clean pset_name to avoid Blender crash
        pset_name = clean_ifc_name(pset_name)

        # Build properties dict
        # Property names with underscores are fine
        props = {}
        for prop_name in properties:
            if prop_name in feature_data:
                value = feature_data[prop_name]
                if value is not None:
                    # Property names should have underscores (from YAML config)
                    props[prop_name] = str(value)

        if props:
            pset = ifcopenshell.api.run("pset.add_pset", ifc_file, product=entity, name=pset_name)
            ifcopenshell.api.run("pset.edit_pset", ifc_file, pset=pset, properties=props)

    def _get_provider_label(self, layer_name: str) -> str:
        """Return a short provider label derived from the layer name prefix.

        Used to prepend to IFC entity names so Blender's outliner groups
        objects visually by provider when sorted alphabetically.

        Examples:
            bgt_pand                        → BGT
            bag3d_lod22                     → BAG3D
            bag_pand                        → BAG
            kadastralekaart-wfs_perceel     → Kadastrale Kaart
            brk-percelen-wfs_cadastralparcel → BRK
        """
        prefixes = [
            ("bag3d", "BAG3D"),
            ("kadastralekaart-wfs", "Kadastrale Kaart"),
            ("kadastralekaart-ogc", "Kadastrale Kaart"),
            ("brk-percelen-wfs", "BRK"),
            ("brk", "BRK"),
            ("bag", "BAG"),
            ("bgt", "BGT"),
            ("ahn", "AHN"),
            ("luchtfoto", "Luchtfoto"),
            ("cbs", "CBS"),
            ("nwb", "NWB"),
        ]
        for prefix, label in prefixes:
            if layer_name.startswith(prefix):
                return label
        for sep in ("_", "-"):
            if sep in layer_name:
                return layer_name.split(sep)[0].upper()
        return layer_name.upper()

    def _get_or_create_style(self, ifc_file: Any, material_name: str, color: tuple) -> Any:
        """Get or create surface style for a material."""
        if material_name in self._material_cache:
            return self._material_cache[material_name]

        # Create surface style
        style = ifcopenshell.api.run("style.add_style", ifc_file, name=material_name)

        # Add rendering color
        ifcopenshell.api.run(
            "style.add_surface_style",
            ifc_file,
            style=style,
            ifc_class="IfcSurfaceStyleRendering",
            attributes={
                "SurfaceColour": {
                    "Name": None,
                    "Red": color[0],
                    "Green": color[1],
                    "Blue": color[2],
                },
                "Transparency": 1.0 - color[3] if len(color) > 3 else 0.0,
            },
        )

        self._material_cache[material_name] = style
        return style
