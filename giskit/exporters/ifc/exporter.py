"""IFC exporter for GeoPackage data.

Exports GeoPackage layers to YAML-configured colors and materials.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.api.owner.settings as owner_settings

from .layer_exporter import LayerExporter
from .materials import MaterialsManager
from .schema_adapter import get_schema_adapter

logger = logging.getLogger(__name__)


class IFCExporter:
    """Export GeoPackage to IFC format."""

    def __init__(
        self,
        ifc_version: str = "IFC4X3_ADD2",
        author: str = "GISKit",
        organization: str = "A190",
        materials_manager: Optional[MaterialsManager] = None,
        color_overrides: Optional[dict[str, dict[str, list[float]]]] = None,
    ):
        """Initialize IFC exporter.

        Args:
            ifc_version: IFC schema version (IFC4X3_ADD2, IFC4, IFC2X3)
            author: Author name for IFC metadata
            organization: Organization name for IFC metadata
            materials_manager: Optional MaterialsManager (creates default if None)
            color_overrides: Recipe-level color overrides per layer
                Format: {"layer_name": {"surface_type": [R, G, B]}}
        """
        # Type narrowing for IFC schema
        schema: Any = ifc_version
        self.ifc = ifcopenshell.file(schema=schema)
        self.author = author
        self.organization = organization

        # Setup owner history BEFORE any API calls (required for ifcopenshell)
        self._setup_owner_history()

        # Materials manager - create with color overrides
        if materials_manager:
            self.materials = materials_manager
        else:
            self.materials = MaterialsManager(color_overrides=color_overrides)

        # Schema adapter for version-specific logic
        self.schema_adapter = get_schema_adapter(self.ifc)

        # Layer exporter
        self.layer_exporter = LayerExporter(self.materials)

        # IFC context and units
        self.project: Any = None
        self.site: Any = None
        self.context: Any = None

        # Reference point (will be set from metadata or first feature)
        self.ref_x: float = 0.0
        self.ref_y: float = 0.0

    def _setup_owner_history(self) -> None:
        """Setup owner history for ifcopenshell API.

        Required before any ifcopenshell.api.run() calls in newer versions.
        This registers the default user and application for the API to use.
        """
        # Create entities for owner history
        person = self.ifc.createIfcPerson(None, self.author, None, None, None, None, None, None)
        organization = self.ifc.createIfcOrganization(None, self.organization, None, None, None)
        person_and_org = self.ifc.createIfcPersonAndOrganization(person, organization, None)
        application = self.ifc.createIfcApplication(
            organization, "1.0", "GISKit IFC Exporter", "GISKit"
        )

        # Store for later use
        self._person_and_org = person_and_org
        self._application = application

        # Register as default for API calls
        owner_settings.get_user = lambda file: person_and_org
        owner_settings.get_application = lambda file: application

    def export(
        self,
        db_path: Path,
        output_path: Path,
        layers: Optional[List[str]] = None,
        exclude_layers: Optional[List[str]] = None,
        normalize_z: bool = True,
        site_name: str = "Site",
        ref_x: Optional[float] = None,
        ref_y: Optional[float] = None,
    ) -> None:
        """Export GeoPackage to IFC file.

        IFC Coordinate System:
            - Site placement is always at (0, 0, 0) - IFC best practice
            - Vertex coordinates are relative to site (small local coordinates)
            - IfcMapConversion (IFC4+) provides transformation to RD (EPSG:28992)
            - RD reference point also stored in properties for backward compatibility

        Args:
            db_path: Path to GeoPackage database
            output_path: Output IFC file path
            layers: List of layer names to export (None = all supported)
            exclude_layers: List of layer names to exclude
            normalize_z: Normalize 3D building Z coordinates to ground level
            site_name: Name for the IFC site
            ref_x: Reference point X (auto-detect if None)
            ref_y: Reference point Y (auto-detect if None)
        """
        logger.info(f"Exporting to IFC: {output_path}")

        # Set reference point
        if ref_x is not None and ref_y is not None:
            self.ref_x = ref_x
            self.ref_y = ref_y
        else:
            # Auto-detect from first feature's centroid
            self.ref_x, self.ref_y = self._auto_detect_reference_point(db_path, layers)

        logger.info(f"Reference point: ({self.ref_x:.2f}, {self.ref_y:.2f})")
        logger.info(f"Z-normalization: {'enabled' if normalize_z else 'disabled'}")

        # Create IFC structure (Site always at 0,0,0 with IfcMapConversion)
        self._create_project(site_name)
        self._create_site(site_name)

        # Determine which layers to export
        if layers is None:
            layers = self._get_available_layers(db_path)

        # Filter out excluded layers
        if exclude_layers:
            layers = [layer for layer in layers if layer not in exclude_layers]

        # Filter to only supported layers
        supported_layers = [
            layer for layer in layers if self.materials.get_layer_config(layer) is not None
        ]

        logger.info(f"Exporting {len(supported_layers)} layer(s)...")

        # Statistics
        total_stats: Dict[str, int] = {}

        # Export each layer
        for layer in supported_layers:
            logger.info(f"  - {layer}...")

            try:
                stats = self.layer_exporter.export(
                    layer_name=layer,
                    ifc_file=self.ifc,
                    site=self.site,
                    context=self.context,
                    schema_adapter=self.schema_adapter,
                    db_path=str(db_path),
                    ref_x=self.ref_x,
                    ref_y=self.ref_y,
                    normalize_z=normalize_z,
                )
                # Accumulate stats
                for key, count in stats.items():
                    total_stats[key] = total_stats.get(key, 0) + count
                logger.info(f"    ✓ Exported {sum(stats.values())} entities")
            except Exception as e:
                logger.error(f"    ✗ Error: {e}")
                import traceback

                traceback.print_exc()

        # Write IFC file
        self.ifc.write(str(output_path))
        logger.info(f"Exported to {output_path}")

        # Print statistics
        logger.info(f"Total entities: {sum(total_stats.values())}")
        for entity_type, count in sorted(total_stats.items()):
            logger.info(f"  - {entity_type}: {count}")

    def _create_project(self, site_name: str) -> None:
        """Create IFC Project with metadata."""
        # Create project using API
        self.project = ifcopenshell.api.run(
            "root.create_entity",
            self.ifc,
            ifc_class="IfcProject",
            name=f"GISKit Export - {site_name}",
        )

        # Set project metadata
        person = self.ifc.createIfcPerson(None, self.author, None, None, None, None, None, None)

        organization_entity = self.ifc.createIfcOrganization(
            None, self.organization, None, None, None
        )

        person_and_org = self.ifc.createIfcPersonAndOrganization(person, organization_entity, None)

        application = self.ifc.createIfcApplication(
            organization_entity, "1.0", "GISKit IFC Exporter", "GISKit"
        )

        owner_history = self.ifc.createIfcOwnerHistory(
            person_and_org,
            application,
            None,
            "ADDED",
            None,
            None,
            None,
            int(datetime.now().timestamp()),
        )

        self.project.OwnerHistory = owner_history

        # Create geometric representation context
        self.context = self.ifc.createIfcGeometricRepresentationContext(
            None,
            "Model",
            3,
            1.0e-5,
            self.ifc.createIfcAxis2Placement3D(
                self.ifc.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None
            ),
            None,
        )

        # Add georeferencing (IFC4+ IfcMapConversion + IfcProjectedCRS)
        # This is the proper way to define coordinate system transformations
        self._add_georeferencing()

        # Set units (meters, square meters, cubic meters)
        units = [
            self.ifc.createIfcSIUnit(None, "LENGTHUNIT", None, "METRE"),
            self.ifc.createIfcSIUnit(None, "AREAUNIT", None, "SQUARE_METRE"),
            self.ifc.createIfcSIUnit(None, "VOLUMEUNIT", None, "CUBIC_METRE"),
        ]

        unit_assignment = self.ifc.createIfcUnitAssignment(units)
        self.project.UnitsInContext = unit_assignment

        # Add context to project
        self.project.RepresentationContexts = [self.context]

    def _create_site(self, site_name: str) -> None:
        """Create IFC Site with geo-referencing.

        Site is always placed at (0, 0, 0) per IFC best practices.
        IfcMapConversion provides the transformation to RD coordinates.
        """
        # Create site
        self.site = ifcopenshell.api.run(
            "root.create_entity", self.ifc, ifc_class="IfcSite", name=site_name
        )

        # Site placement always at origin (IFC best practice)
        # IfcMapConversion handles transformation to RD coordinates
        site_x, site_y, site_z = 0.0, 0.0, 0.0

        # CompositionType is required for IFC2X3, optional for IFC4+
        # Use "ELEMENT" which means the site is not decomposed
        schema_version = self.ifc.schema
        composition_type = "ELEMENT" if schema_version == "IFC2X3" else None

        # Set site location
        # NOTE: Geometry coordinates are ALWAYS relative to this placement
        site_location = self.ifc.createIfcSite(
            self.site.GlobalId,
            self.site.OwnerHistory if hasattr(self.site, "OwnerHistory") else None,
            self.site.Name,
            None,  # Description
            None,  # ObjectType
            self.ifc.createIfcLocalPlacement(
                None,
                self.ifc.createIfcAxis2Placement3D(
                    self.ifc.createIfcCartesianPoint((site_x, site_y, site_z)), None, None
                ),
            ),
            None,  # Representation
            None,  # LongName
            composition_type,  # CompositionType (required for IFC2X3)
            None,  # RefLatitude
            None,  # RefLongitude
            None,  # RefElevation
            None,  # LandTitleNumber
            None,  # SiteAddress
        )

        # Replace site entity
        self.ifc.remove(self.site)
        self.site = site_location

        # Assign site to project
        ifcopenshell.api.run(
            "aggregate.assign_object", self.ifc, relating_object=self.project, products=[self.site]
        )

        # Store RD reference point in site properties (for GIS tools)
        # This allows reconstruction of absolute coordinates even in relative mode
        self._add_rd_reference_property()

    def _get_available_layers(self, db_path: Path) -> List[str]:
        """Get list of available layers in GeoPackage."""
        import fiona

        try:
            layers = fiona.listlayers(str(db_path))
            return layers
        except Exception as e:
            logger.warning(f"Could not list layers: {e}")
            return []

    def _auto_detect_reference_point(
        self, db_path: Path, layers: Optional[List[str]] = None
    ) -> tuple[float, float]:
        """Auto-detect reference point from metadata or first feature's centroid.

        Args:
            db_path: Path to GeoPackage
            layers: Optional list of layers to check

        Returns:
            Tuple of (ref_x, ref_y)
        """
        import geopandas as gpd

        # First try to read from _metadata table (created by giskit)
        try:
            metadata_gdf = gpd.read_file(str(db_path), layer="_metadata")
            if (
                len(metadata_gdf) > 0
                and "x" in metadata_gdf.columns
                and "y" in metadata_gdf.columns
            ):
                ref_x = float(metadata_gdf["x"].iloc[0])
                ref_y = float(metadata_gdf["y"].iloc[0])
                logger.info(f"Using reference point from _metadata: ({ref_x:.2f}, {ref_y:.2f})")
                return (ref_x, ref_y)
        except Exception:
            # _metadata table doesn't exist or is invalid, fall back to auto-detection
            pass

        if layers is None:
            layers = self._get_available_layers(db_path)

        # Try to find a feature with geometry
        for layer in layers:
            try:
                gdf = gpd.read_file(str(db_path), layer=layer, rows=1)
                if len(gdf) > 0 and gdf.geometry.iloc[0] is not None:
                    centroid = gdf.geometry.iloc[0].centroid
                    return (centroid.x, centroid.y)
            except Exception:
                continue

        # Default to origin if no features found
        return (0.0, 0.0)

    def _add_rd_reference_property(self) -> None:
        """Add RD reference point as property to the site.

        This allows GIS tools to reconstruct absolute RD coordinates
        even when using relative coordinate mode.
        """
        # Create property set for RD reference
        property_values = [
            self.ifc.createIfcPropertySingleValue(
                "RD_Reference_X",
                "Reference point X coordinate (EPSG:28992)",
                self.ifc.create_entity("IfcReal", self.ref_x),
                None,
            ),
            self.ifc.createIfcPropertySingleValue(
                "RD_Reference_Y",
                "Reference point Y coordinate (EPSG:28992)",
                self.ifc.create_entity("IfcReal", self.ref_y),
                None,
            ),
            self.ifc.createIfcPropertySingleValue(
                "CRS",
                "Coordinate Reference System",
                self.ifc.create_entity("IfcLabel", "EPSG:28992"),
                None,
            ),
        ]

        # Get owner history for IFC2X3 (required) or None for IFC4+
        owner_history = self._get_owner_history()

        property_set = self.ifc.createIfcPropertySet(
            ifcopenshell.guid.new(),
            owner_history,
            "RD_Georeference",
            "Rijksdriehoek (Amersfoort RD New) reference point",
            property_values,
        )

        # Attach to site
        self.ifc.createIfcRelDefinesByProperties(
            ifcopenshell.guid.new(),
            owner_history,
            "RD Reference",
            None,  # Description
            [self.site],
            property_set,
        )

    def _get_owner_history(self) -> Any:
        """Get or create owner history for IFC entities.

        Returns:
            OwnerHistory entity for IFC2X3 (required), None for IFC4+ (optional)
        """
        schema_version = self.ifc.schema

        # IFC4+ doesn't require OwnerHistory
        if schema_version != "IFC2X3":
            return None

        # IFC2X3 requires OwnerHistory - create one using stored person/org/app
        owner_history = self.ifc.createIfcOwnerHistory(
            self._person_and_org,
            self._application,
            None,  # State
            "ADDED",  # ChangeAction
            None,  # LastModifiedDate
            None,  # LastModifyingUser
            None,  # LastModifyingApplication
            int(datetime.now().timestamp()),  # CreationDate
        )
        return owner_history

    def _add_georeferencing(self) -> None:
        """Add IFC4+ georeferencing using IfcMapConversion and IfcProjectedCRS.

        This is the proper way according to IFC4+ specification to define
        the transformation between the IFC coordinate system and a projected CRS.

        The context's coordinate system is always local (origin at 0,0,0).
        The MapConversion defines how to transform to the projected CRS (RD).

        With IfcMapConversion:
        - IFC local coords (0,0,0) represents (ref_x, ref_y, 0) in RD
        - To get RD: add (Eastings, Northings, OrthogonalHeight) to IFC coords
        - BIM viewers can use this to show absolute positions
        """
        # Only add for IFC4+
        schema_version = self.ifc.schema
        if schema_version not in ["IFC4", "IFC4X3", "IFC4X3_ADD2"]:
            # IFC2X3 doesn't support IfcMapConversion
            return

        # Create IfcProjectedCRS for Amersfoort RD New (EPSG:28992)
        try:
            projected_crs = self.ifc.create_entity(
                "IfcProjectedCRS",
                Name="EPSG:28992",
                Description="Amersfoort / RD New",
                GeodeticDatum="Amersfoort",
                VerticalDatum="NAP",
                MapProjection="Oblique Stereographic",
                MapZone=None,
                MapUnit=self.ifc.createIfcSIUnit(None, "LENGTHUNIT", None, "METRE"),
            )

            # Create IfcMapConversion
            # This defines the transformation from IFC local coords to RD coords
            # Eastings/Northings = offset to add to IFC coords to get RD coords
            self.ifc.create_entity(
                "IfcMapConversion",
                SourceCRS=self.context,  # IFC local coordinate system
                TargetCRS=projected_crs,  # RD coordinate system
                Eastings=self.ref_x,  # RD X offset
                Northings=self.ref_y,  # RD Y offset
                OrthogonalHeight=0.0,  # RD Z offset (NAP)
                XAxisAbscissa=1.0,  # No rotation
                XAxisOrdinate=0.0,
                Scale=1.0,  # No scale
            )

            # Note: HasCoordinateOperation is an inverse attribute
            # It's automatically set when we create the IfcMapConversion with SourceCRS

        except Exception as e:
            # If georeferencing fails, continue without it
            # (Some IFC versions might not support all attributes)
            logger.warning(f"Could not add IfcMapConversion: {e}")
