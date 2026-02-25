"""Output management for saving data in various formats."""

import logging
import tempfile
from pathlib import Path
from typing import Callable, Optional

import geopandas as gpd

from giskit.core.recipe import Recipe

logger = logging.getLogger(__name__)


class OutputManager:
    """Manages output file saving and format conversion.

    The OutputManager handles all file I/O operations including:
    - Saving layers to various GIS formats (GPKG, GeoJSON, SHP, FGB)
    - Exporting to 3D formats (IFC, GLB, OBJ)
    - Handling auto-exports for configured formats
    - Cleaning up temporary files

    This separates output concerns from recipe execution and CLI presentation.
    """

    def __init__(self, recipe: Recipe, recipe_dir: Path):
        """Initialize the OutputManager.

        Args:
            recipe: Recipe with output configuration
            recipe_dir: Directory containing recipe file (for resolving relative paths)
        """
        self.recipe = recipe
        self.recipe_dir = recipe_dir

    def save_layers(
        self,
        layers: dict[str, gpd.GeoDataFrame],
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> Path:
        """Save layers to output file in the configured format.

        Args:
            layers: Dictionary mapping layer names to GeoDataFrames
            progress_callback: Optional callback(message: str, level: str) for status updates
                             level can be "info", "success", "warning", "error"

        Returns:
            Path to the saved output file

        Raises:
            ValueError: If output format is unsupported
            ImportError: If required dependencies are missing
        """
        # Resolve output path
        output_path = self.recipe.output.path
        if not output_path.is_absolute():
            output_path = self.recipe_dir / output_path

        output_format = self.recipe.output.format.value

        if progress_callback:
            progress_callback(f"Saving to {output_path}...", "info")

        if output_format == "gpkg":
            self._save_gpkg(layers, output_path, progress_callback)
        elif output_format in ("geojson", "shp", "fgb"):
            self._save_single_layer_format(layers, output_path, output_format, progress_callback)
        elif output_format == "ifc":
            self._save_ifc(layers, output_path, progress_callback)
        elif output_format == "glb":
            self._save_glb(layers, output_path, progress_callback)
        else:
            raise ValueError(f"Unsupported output format: {output_format}")

        return output_path

    def _save_gpkg(
        self,
        layers: dict[str, gpd.GeoDataFrame],
        output_path: Path,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        """Save layers to GeoPackage format.

        Args:
            layers: Dictionary mapping layer names to GeoDataFrames
            output_path: Path to save the GeoPackage
            progress_callback: Optional callback for status updates
        """
        total_features = 0

        for layer_name, gdf in layers.items():
            # Remove internal columns before saving
            save_gdf = self._clean_internal_columns(gdf)
            save_gdf.to_file(output_path, driver="GPKG", layer=layer_name)
            total_features += len(save_gdf)

        if progress_callback:
            progress_callback(
                f"Successfully saved {total_features} features in {len(layers)} layers to {output_path}",
                "success",
            )

        # Handle auto-exports
        if self.recipe.output.ifc_export:
            self._auto_export_ifc(output_path, progress_callback)

    def _save_single_layer_format(
        self,
        layers: dict[str, gpd.GeoDataFrame],
        output_path: Path,
        format_name: str,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        """Save layers to a single-layer format (GeoJSON, SHP, FGB).

        Args:
            layers: Dictionary mapping layer names to GeoDataFrames
            output_path: Path to save the file
            format_name: Format name ("geojson", "shp", or "fgb")
            progress_callback: Optional callback for status updates
        """
        # Combine all layers into one
        combined = gpd.GeoDataFrame(gpd.pd.concat(layers.values(), ignore_index=True))

        driver_map = {
            "geojson": "GeoJSON",
            "shp": "ESRI Shapefile",
            "fgb": "FlatGeobuf",
        }

        driver = driver_map.get(format_name)
        if not driver:
            raise ValueError(f"Unknown single-layer format: {format_name}")

        combined.to_file(output_path, driver=driver)

        if progress_callback:
            progress_callback(
                f"Successfully saved {len(combined)} features to {output_path}", "success"
            )

    def _save_ifc(
        self,
        layers: dict[str, gpd.GeoDataFrame],
        output_path: Path,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        """Save layers directly to IFC format.

        Args:
            layers: Dictionary mapping layer names to GeoDataFrames
            output_path: Path to save the IFC file
            progress_callback: Optional callback for status updates

        Raises:
            ImportError: If ifcopenshell is not installed
        """
        try:
            from giskit.exporters.ifc import IFCExporter
        except ImportError as e:
            if progress_callback:
                progress_callback("IFC export requires ifcopenshell", "error")
                progress_callback("Install with: pip install giskit[ifc]", "info")
            raise ImportError("ifcopenshell not installed") from e

        # Save to temporary GPKG first
        with tempfile.NamedTemporaryFile(suffix=".gpkg", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        # Delete the temp file so geopandas can create it fresh
        tmp_path.unlink()

        try:
            total_features = 0
            for layer_name, gdf in layers.items():
                save_gdf = self._clean_internal_columns(gdf)
                save_gdf.to_file(tmp_path, driver="GPKG", layer=layer_name)
                total_features += len(save_gdf)

            if progress_callback:
                progress_callback(f"Converting {total_features} features to IFC format...", "info")

            # Determine IFC versions to export
            ifc_versions: list[str] = []
            if self.recipe.output.ifc_export and self.recipe.output.ifc_export.ifc_versions:
                ifc_versions = self.recipe.output.ifc_export.ifc_versions
            else:
                ifc_versions = [
                    self.recipe.output.ifc_export.ifc_version
                    if self.recipe.output.ifc_export
                    else "IFC4X3_ADD2"
                ]

            # Export each IFC version
            for ifc_version in ifc_versions:
                # Determine output path for this version
                if len(ifc_versions) > 1:
                    # Multiple versions: output_IFC4X3_ADD2.ifc
                    versioned_path = output_path.with_stem(f"{output_path.stem}_{ifc_version}")
                else:
                    versioned_path = output_path

                if progress_callback:
                    progress_callback(f"Exporting to {ifc_version}...", "info")

                exporter = IFCExporter(
                    ifc_version=ifc_version,
                    author="GISKit",
                    organization="A190",
                    color_overrides=self.recipe.output.ifc_export.layer_colors
                    if self.recipe.output.ifc_export
                    else None,
                )

                site_name = (
                    self.recipe.output.ifc_export.site_name
                    if self.recipe.output.ifc_export and self.recipe.output.ifc_export.site_name
                    else "Site"
                )

                exporter.export(
                    db_path=tmp_path,
                    output_path=versioned_path,
                    layers=None,
                    normalize_z=self.recipe.output.ifc_export.normalize_z
                    if self.recipe.output.ifc_export
                    else True,
                    site_name=site_name,
                )

                if versioned_path.exists():
                    size_mb = versioned_path.stat().st_size / (1024 * 1024)
                    if progress_callback:
                        progress_callback(
                            f"Exported to {versioned_path} ({size_mb:.1f} MB)", "success"
                        )

            if progress_callback:
                progress_callback(f"Successfully exported {total_features} features", "success")

        finally:
            # Clean up temp file
            if tmp_path.exists():
                tmp_path.unlink()

    def _save_glb(
        self,
        layers: dict[str, gpd.GeoDataFrame],
        output_path: Path,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        """Save layers to GLB format (via IFC intermediate).

        Args:
            layers: Dictionary mapping layer names to GeoDataFrames
            output_path: Path to save the GLB file
            progress_callback: Optional callback for status updates

        Raises:
            ImportError: If required dependencies are missing
        """
        try:
            from giskit.exporters.glb_exporter import GLBExporter
            from giskit.exporters.ifc import IFCExporter
        except ImportError as e:
            if progress_callback:
                progress_callback("GLB export requires ifcopenshell and pygltflib", "error")
                progress_callback("Install with: pip install giskit[ifc]", "info")
            raise ImportError("Required dependencies not installed") from e

        # Create temporary GPKG and IFC files
        with tempfile.NamedTemporaryFile(suffix=".gpkg", delete=False) as tmp_gpkg:
            tmp_gpkg_path = Path(tmp_gpkg.name)
        with tempfile.NamedTemporaryFile(suffix=".ifc", delete=False) as tmp_ifc:
            tmp_ifc_path = Path(tmp_ifc.name)

        # Delete temp files so geopandas can create them fresh
        tmp_gpkg_path.unlink()
        tmp_ifc_path.unlink()

        try:
            # Save to GPKG
            total_features = 0
            for layer_name, gdf in layers.items():
                save_gdf = self._clean_internal_columns(gdf)
                save_gdf.to_file(tmp_gpkg_path, driver="GPKG", layer=layer_name)
                total_features += len(save_gdf)

            if progress_callback:
                progress_callback(f"Converting {total_features} features to IFC...", "info")

            # Export to IFC
            ifc_exporter = IFCExporter(
                ifc_version=self.recipe.output.ifc_export.ifc_version
                if self.recipe.output.ifc_export
                else "IFC4X3_ADD2",
                author="GISKit",
                organization="A190",
                color_overrides=self.recipe.output.ifc_export.layer_colors
                if self.recipe.output.ifc_export
                else None,
            )

            site_name = (
                self.recipe.output.ifc_export.site_name
                if self.recipe.output.ifc_export and self.recipe.output.ifc_export.site_name
                else "Site"
            )

            ifc_exporter.export(
                db_path=tmp_gpkg_path,
                output_path=tmp_ifc_path,
                layers=None,
                normalize_z=self.recipe.output.ifc_export.normalize_z
                if self.recipe.output.ifc_export
                else True,
                site_name=site_name,
            )

            if progress_callback:
                progress_callback("Converting IFC to GLB...", "info")

            # Convert to GLB
            glb_exporter = GLBExporter()
            if not glb_exporter.is_available():
                if progress_callback:
                    progress_callback("GLB export skipped: IfcConvert not found", "warning")
                    progress_callback("Install with: pip install ifcopenshell", "info")
                raise ImportError("IfcConvert not available")

            glb_exporter.ifc_to_glb(
                ifc_path=tmp_ifc_path,
                glb_path=output_path,
                use_world_coords=self.recipe.output.ifc_export.glb_use_world_coords
                if self.recipe.output.ifc_export
                else True,
                center_model=self.recipe.output.ifc_export.glb_center_model
                if self.recipe.output.ifc_export
                else False,
                compress=self.recipe.output.ifc_export.glb_compress
                if self.recipe.output.ifc_export
                else True,
            )

            if output_path.exists():
                size_mb = output_path.stat().st_size / (1024 * 1024)
                if progress_callback:
                    progress_callback(
                        f"Successfully exported {total_features} features to {output_path} ({size_mb:.1f} MB)",
                        "success",
                    )

        finally:
            # Clean up temp files
            if tmp_gpkg_path.exists():
                tmp_gpkg_path.unlink()
            if tmp_ifc_path.exists():
                tmp_ifc_path.unlink()

    def _auto_export_ifc(
        self,
        gpkg_path: Path,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        """Auto-export GPKG to IFC if configured.

        Args:
            gpkg_path: Path to the GeoPackage file
            progress_callback: Optional callback for status updates
        """
        if not self.recipe.output.ifc_export:
            return

        if progress_callback:
            progress_callback(
                f"Auto-exporting to IFC: {self.recipe.output.ifc_export.path}", "info"
            )

        try:
            from giskit.exporters.ifc import IFCExporter

            # Create exporter with color overrides
            exporter = IFCExporter(
                ifc_version=self.recipe.output.ifc_export.ifc_version,
                author="GISKit",
                organization="A190",
                color_overrides=self.recipe.output.ifc_export.layer_colors,
            )

            # Determine site name
            site_name = self.recipe.output.ifc_export.site_name
            if site_name is None and self.recipe.location.type.value == "address":
                if isinstance(self.recipe.location.value, str):
                    site_name = self.recipe.location.value
            if site_name is None:
                site_name = "Site"

            # Export
            exporter.export(
                db_path=gpkg_path,
                output_path=self.recipe.output.ifc_export.path,
                layers=None,
                normalize_z=self.recipe.output.ifc_export.normalize_z,
                site_name=site_name,
            )

            # Show file size
            if self.recipe.output.ifc_export.path.exists():
                size_mb = self.recipe.output.ifc_export.path.stat().st_size / (1024 * 1024)
                if progress_callback:
                    progress_callback(
                        f"IFC export complete: {self.recipe.output.ifc_export.path} ({size_mb:.1f} MB)",
                        "success",
                    )

            # Auto-export to GLB if configured
            if self.recipe.output.ifc_export.glb_path:
                self._auto_export_glb(progress_callback)

            # Auto-export to OBJ ZIP if configured
            if self.recipe.output.ifc_export.obj_zip_path:
                self._auto_export_obj(progress_callback)

        except ImportError:
            if progress_callback:
                progress_callback("IFC export skipped: ifcopenshell not installed", "warning")
                progress_callback("Install with: pip install giskit[ifc]", "info")
        except Exception as e:
            logger.error(f"IFC export failed: {e}", exc_info=True)
            if progress_callback:
                progress_callback(f"IFC export failed: {e}", "error")

    def _auto_export_glb(
        self,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        """Auto-export IFC to GLB if configured.

        Args:
            progress_callback: Optional callback for status updates
        """
        if not self.recipe.output.ifc_export or not self.recipe.output.ifc_export.glb_path:
            return

        if progress_callback:
            progress_callback(
                f"Auto-exporting to GLB: {self.recipe.output.ifc_export.glb_path}", "info"
            )

        try:
            from giskit.exporters.glb_exporter import GLBExporter

            glb_exporter = GLBExporter()
            if not glb_exporter.is_available():
                if progress_callback:
                    progress_callback("GLB export skipped: IfcConvert not found", "warning")
                    progress_callback("Install with: pip install ifcopenshell", "info")
                return

            glb_exporter.ifc_to_glb(
                ifc_path=self.recipe.output.ifc_export.path,
                glb_path=self.recipe.output.ifc_export.glb_path,
                use_world_coords=self.recipe.output.ifc_export.glb_use_world_coords,
                center_model=self.recipe.output.ifc_export.glb_center_model,
            )

            if self.recipe.output.ifc_export.glb_path.exists():
                glb_mb = self.recipe.output.ifc_export.glb_path.stat().st_size / (1024 * 1024)
                if progress_callback:
                    progress_callback(
                        f"GLB export complete: {self.recipe.output.ifc_export.glb_path} ({glb_mb:.1f} MB)",
                        "success",
                    )

        except Exception as e:
            logger.error(f"GLB export failed: {e}", exc_info=True)
            if progress_callback:
                progress_callback(f"GLB export failed: {e}", "error")

    def _auto_export_obj(
        self,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        """Auto-export IFC to OBJ ZIP if configured.

        Args:
            progress_callback: Optional callback for status updates
        """
        if not self.recipe.output.ifc_export or not self.recipe.output.ifc_export.obj_zip_path:
            return

        if progress_callback:
            progress_callback(
                f"Auto-exporting to OBJ ZIP: {self.recipe.output.ifc_export.obj_zip_path}", "info"
            )

        try:
            from giskit.exporters.obj_zip_exporter import OBJZipExporter

            obj_exporter = OBJZipExporter()
            if not obj_exporter.is_available():
                if progress_callback:
                    progress_callback("OBJ export skipped: ifcopenshell not found", "warning")
                    progress_callback("Install with: pip install ifcopenshell", "info")
                return

            obj_exporter.ifc_to_obj_zip(
                ifc_path=self.recipe.output.ifc_export.path,
                output_zip_path=self.recipe.output.ifc_export.obj_zip_path,
                use_world_coords=True,
            )

            if self.recipe.output.ifc_export.obj_zip_path.exists():
                obj_mb = self.recipe.output.ifc_export.obj_zip_path.stat().st_size / (1024 * 1024)
                if progress_callback:
                    progress_callback(
                        f"OBJ ZIP export complete: {self.recipe.output.ifc_export.obj_zip_path} ({obj_mb:.1f} MB)",
                        "success",
                    )

        except Exception as e:
            logger.error(f"OBJ export failed: {e}", exc_info=True)
            if progress_callback:
                progress_callback(f"OBJ export failed: {e}", "error")

    @staticmethod
    def _clean_internal_columns(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Remove internal columns before saving.

        Args:
            gdf: GeoDataFrame to clean

        Returns:
            Cleaned GeoDataFrame (copy)
        """
        save_gdf = gdf.copy()
        internal_cols = ["_provider", "_service", "_layer", "_collection"]
        for col in internal_cols:
            if col in save_gdf.columns:
                save_gdf = save_gdf.drop(columns=[col])
        return save_gdf
