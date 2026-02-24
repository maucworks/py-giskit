"""Run and validate recipe commands."""

import asyncio
import re
from pathlib import Path

import click
from rich.console import Console

from giskit.core.constants import BGT_ALL_LAYERS_THRESHOLD
from giskit.core.recipe import Recipe

console = Console()


def _normalize_layer_name(name: str) -> str:
    """Normalize layer name to snake_case.

    Converts PascalCase/camelCase to snake_case for consistency.
    Examples:
        Perceel -> perceel
        BuildingPart -> building_part
        pand -> pand (already lowercase)
    """
    # Insert underscore before uppercase letters (but not at start)
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    # Insert underscore before uppercase letters that follow lowercase
    s2 = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1)
    # Convert to lowercase
    return s2.lower()


async def _execute_recipe(recipe: Recipe, recipe_dir: Path, console: Console, verbose: bool):
    """Execute a recipe asynchronously.

    Args:
        recipe: Recipe to execute
        recipe_dir: Directory containing the recipe file (for resolving relative paths)
        console: Rich console for output
        verbose: Verbose logging

    Returns:
        Dictionary mapping layer names to GeoDataFrames
    """
    import geopandas as gpd

    # Get bbox from location
    with console.status("[bold green]Calculating bounding box..."):
        bbox = await recipe.get_bbox_wgs84()

    if verbose:
        console.print(f"  BBox (WGS84): {bbox}")

    # Resolve output path relative to recipe directory if it's relative
    output_path = recipe.output.path
    if not output_path.is_absolute():
        output_path = recipe_dir / output_path

    # Download each dataset - store as separate layers
    layers = {}

    for i, dataset in enumerate(recipe.datasets, 1):
        console.print(f"\n[bold]Dataset {i}/{len(recipe.datasets)}:[/bold] {dataset.provider}")

        if dataset.service:
            console.print(f"  Service: {dataset.service}")
        if dataset.layers:
            console.print(f"  Layers: {', '.join(dataset.layers)}")

        try:
            # Get provider
            from giskit.providers.base import get_provider

            provider = get_provider(dataset.provider)

            # Convert bbox to Location for compatibility
            from giskit.core.recipe import Location, LocationType

            bbox_location = Location(
                type=LocationType.BBOX, value=list(bbox), crs="EPSG:4326", radius=None
            )

            # Download dataset
            with console.status(f"[bold green]Downloading from {dataset.provider}..."):
                gdf = await provider.download_dataset(
                    dataset=dataset,
                    location=bbox_location,
                    output_path=output_path,
                    output_crs=recipe.output.crs,
                )

            if not gdf.empty:
                console.print(f"  [green]✓[/green] Downloaded {len(gdf)} features")

                # Store with layer name: service_layer or just service
                service = dataset.service or dataset.provider

                # Check if gdf has collection/layer information (from multi-layer downloads)
                if "_collection" in gdf.columns:
                    # Split by collection/layer
                    for collection_name in gdf["_collection"].unique():
                        layer_gdf = gdf[gdf["_collection"] == collection_name].copy()
                        # Normalize collection name to snake_case
                        normalized_name = _normalize_layer_name(collection_name)
                        full_layer_name = f"{service}_{normalized_name}"
                        layers[full_layer_name] = layer_gdf
                elif "_layer" in gdf.columns:
                    # Alternative layer column name
                    for layer_name in gdf["_layer"].unique():
                        layer_gdf = gdf[gdf["_layer"] == layer_name].copy()
                        # Normalize layer name to snake_case
                        normalized_name = _normalize_layer_name(layer_name)
                        full_layer_name = f"{service}_{normalized_name}"
                        layers[full_layer_name] = layer_gdf
                else:
                    # Single layer - use service name or first layer from request
                    if dataset.layers and len(dataset.layers) == 1:
                        layer_name = f"{service}_{dataset.layers[0]}"
                    else:
                        layer_name = service
                    layers[layer_name] = gdf
            else:
                console.print("  [yellow]No features found[/yellow]")

        except Exception as e:
            console.print(f"  [red]✗[/red] Failed: {e}")
            if verbose:
                console.print_exception()
            # Continue with other datasets

    # Add metadata layer if we have a bbox
    if layers and recipe.output.format.value == "gpkg":
        from datetime import datetime

        from shapely.geometry import Point

        from giskit.core.spatial import transform_bbox

        # Transform bbox to output CRS
        bbox_output_crs = transform_bbox(bbox, "EPSG:4326", recipe.output.crs)

        # Get origin point from recipe location (the point the user specified)
        # This is the point that will be at (0,0,0) in IFC exports
        from giskit.core.geocoding import geocode
        from giskit.core.recipe import LocationType
        from giskit.core.spatial import transform_point

        if recipe.location.type == LocationType.POINT:
            # Point location - use the exact coordinates specified
            point_coords: list = recipe.location.value  # type: ignore
            lon, lat = float(point_coords[0]), float(point_coords[1])
            # Transform from location CRS to output CRS
            origin_x, origin_y = transform_point(lon, lat, recipe.location.crs, recipe.output.crs)
        elif recipe.location.type == LocationType.ADDRESS:
            # Address location - geocode to get the point, then transform
            address_str: str = recipe.location.value  # type: ignore
            lon, lat = await geocode(address_str)
            origin_x, origin_y = transform_point(lon, lat, "EPSG:4326", recipe.output.crs)
        elif recipe.location.type == LocationType.BBOX:
            # Bbox location - use center of bbox
            origin_x = (bbox_output_crs[0] + bbox_output_crs[2]) / 2
            origin_y = (bbox_output_crs[1] + bbox_output_crs[3]) / 2
        elif recipe.location.type == LocationType.POLYGON:
            # Polygon location - use 2D centroid
            from shapely.geometry import Polygon

            poly_coords: list = recipe.location.value  # type: ignore
            polygon = Polygon(poly_coords)
            centroid = polygon.centroid
            # Transform centroid from location CRS to output CRS
            origin_x, origin_y = transform_point(
                centroid.x, centroid.y, recipe.location.crs, recipe.output.crs
            )
        else:
            # Fallback to bbox center
            origin_x = (bbox_output_crs[0] + bbox_output_crs[2]) / 2
            origin_y = (bbox_output_crs[1] + bbox_output_crs[3]) / 2

        # Build metadata dict - exact column order matching Sitedb
        metadata_dict = {
            "address": [None],
            "x": [origin_x],
            "y": [origin_y],
            "radius": [None],
            "bbox_minx": [bbox_output_crs[0]],
            "bbox_miny": [bbox_output_crs[1]],
            "bbox_maxx": [bbox_output_crs[2]],
            "bbox_maxy": [bbox_output_crs[3]],
            "download_date": [datetime.now().isoformat()],
            "crs": [recipe.output.crs],
            "grid_size": [None],  # For raster data, optional
            "bgt_layers": [None],  # Which BGT layers were requested
            "bag3d_lods": [None],  # Which BAG3D LOD levels were requested
        }

        # Add location-specific fields
        if recipe.location.type.value == "address":
            metadata_dict["address"] = [recipe.location.value]
            if recipe.location.radius is not None:
                metadata_dict["radius"] = [recipe.location.radius]
        elif recipe.location.type.value == "point":
            if recipe.location.radius is not None:
                metadata_dict["radius"] = [recipe.location.radius]

        # Extract dataset-specific metadata for traceability
        bgt_layers_list = []
        bag3d_lods_list = []

        for dataset in recipe.datasets:
            service = dataset.service or dataset.provider

            # Track BGT layers
            if service == "bgt" and dataset.layers:
                bgt_layers_list.extend(dataset.layers)

            # Track BAG3D LOD levels
            elif service == "bag3d" and dataset.layers:
                # Extract LOD levels (lod12 -> 1.2, lod13 -> 1.3, lod22 -> 2.2)
                for layer in dataset.layers:
                    if layer.startswith("lod"):
                        # Convert lod12 -> 1.2
                        lod_num = layer[3:]  # "12", "13", "22"
                        if len(lod_num) == 2:
                            lod_formatted = f"{lod_num[0]}.{lod_num[1]}"
                            bag3d_lods_list.append(lod_formatted)

            # Track grid_size if resolution is specified (for raster data)
            if dataset.resolution is not None:
                metadata_dict["grid_size"] = [dataset.resolution]

        # Store BGT layers (or "all" if many layers)
        if bgt_layers_list:
            # Sitedb uses "all" if all BGT layers are included
            if len(bgt_layers_list) > BGT_ALL_LAYERS_THRESHOLD:
                metadata_dict["bgt_layers"] = ["all"]
            else:
                metadata_dict["bgt_layers"] = [",".join(sorted(bgt_layers_list))]

        # Store BAG3D LOD levels
        if bag3d_lods_list:
            metadata_dict["bag3d_lods"] = [",".join(sorted(bag3d_lods_list))]

        # Create metadata GeoDataFrame
        metadata_gdf = gpd.GeoDataFrame(
            metadata_dict, geometry=[Point(origin_x, origin_y)], crs=recipe.output.crs
        )

        layers["_metadata"] = metadata_gdf

    return layers if layers else None


@click.command()
@click.argument("recipe_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.option("--dry-run", is_flag=True, help="Validate without downloading")
def run(recipe_path: Path, verbose: bool, dry_run: bool) -> None:
    """Run a recipe to download spatial data.

    Examples:
        giskit run amsterdam.json
        giskit run --dry-run test.json
        giskit run --verbose utrecht.json
    """
    try:
        # Load recipe
        with console.status("[bold green]Loading recipe..."):
            recipe = Recipe.from_file(recipe_path)

        console.print(f"[bold green]✓[/bold green] Loaded recipe: {recipe.name or 'Unnamed'}")

        if recipe.description:
            console.print(f"  {recipe.description}")

        # Display recipe summary
        console.print(f"\n[bold]Location:[/bold] {recipe.location.type.value}")
        if recipe.location.type.value == "address":
            console.print(f"  Address: {recipe.location.value}")
            console.print(f"  Radius: {recipe.location.radius}m")
        elif recipe.location.type.value == "bbox":
            console.print(f"  BBox: {recipe.location.value}")

        console.print(f"\n[bold]Datasets:[/bold] {len(recipe.datasets)} datasets")
        for i, ds in enumerate(recipe.datasets, 1):
            console.print(f"  {i}. {ds.provider}", end="")
            if ds.service:
                console.print(f" → {ds.service}", end="")
            if ds.layers:
                console.print(f" → {', '.join(ds.layers)}", end="")
            console.print()

        console.print(f"\n[bold]Output:[/bold] {recipe.output.path}")
        console.print(f"  Format: {recipe.output.format.value}")
        console.print(f"  CRS: {recipe.output.crs}")

        if dry_run:
            console.print("\n[yellow]Dry run - no data downloaded[/yellow]")
            return

        # Execute recipe
        console.print("\n[bold]Executing recipe...[/bold]")

        try:
            # Run async download - returns dict of layer_name -> GeoDataFrame
            layers = asyncio.run(_execute_recipe(recipe, recipe_path.parent, console, verbose))

            # Save to output file
            if layers is not None and len(layers) > 0:
                # Resolve output path relative to recipe directory if it's relative
                output_path = recipe.output.path
                if not output_path.is_absolute():
                    output_path = recipe_path.parent / output_path
                output_format = recipe.output.format.value

                with console.status(f"[bold green]Saving to {output_path}..."):
                    if output_format == "gpkg":
                        # Save each layer separately in GeoPackage
                        total_features = 0
                        for layer_name, gdf in layers.items():
                            # Remove internal columns before saving
                            save_gdf = gdf.copy()
                            for col in ["_provider", "_service", "_layer", "_collection"]:
                                if col in save_gdf.columns:
                                    save_gdf = save_gdf.drop(columns=[col])

                            save_gdf.to_file(output_path, driver="GPKG", layer=layer_name)
                            total_features += len(save_gdf)

                        console.print(
                            f"\n[bold green]✓[/bold green] Successfully saved {total_features} features in {len(layers)} layers to {output_path}"
                        )

                        # Auto-export to IFC if configured
                        if recipe.output.ifc_export:
                            console.print(
                                f"\n[bold]Auto-exporting to IFC:[/bold] {recipe.output.ifc_export.path}"
                            )
                            try:
                                from giskit.exporters.ifc import IFCExporter

                                # Create exporter with color overrides
                                exporter = IFCExporter(
                                    ifc_version=recipe.output.ifc_export.ifc_version,
                                    author="GISKit",
                                    organization="A190",
                                    color_overrides=recipe.output.ifc_export.layer_colors,
                                )

                                # Determine site name
                                site_name = recipe.output.ifc_export.site_name
                                if site_name is None and recipe.location.type.value == "address":
                                    if isinstance(recipe.location.value, str):
                                        site_name = recipe.location.value
                                if site_name is None:
                                    site_name = "Site"

                                # Export (without console.status to avoid Rich LiveError)
                                exporter.export(
                                    db_path=output_path,
                                    output_path=recipe.output.ifc_export.path,
                                    layers=None,
                                    normalize_z=recipe.output.ifc_export.normalize_z,
                                    site_name=site_name,
                                )

                                # Show file size
                                if recipe.output.ifc_export.path.exists():
                                    size_mb = recipe.output.ifc_export.path.stat().st_size / (
                                        1024 * 1024
                                    )
                                    console.print(
                                        f"  [bold green]✓[/bold green] IFC export complete: {recipe.output.ifc_export.path} ({size_mb:.1f} MB)"
                                    )

                                # Auto-export to GLB if configured
                                if recipe.output.ifc_export.glb_path:
                                    console.print(
                                        f"\n[bold]Auto-exporting to GLB:[/bold] {recipe.output.ifc_export.glb_path}"
                                    )
                                    try:
                                        from giskit.exporters.glb_exporter import GLBExporter

                                        glb_exporter = GLBExporter()
                                        if not glb_exporter.is_available():
                                            console.print(
                                                "  [yellow]⚠[/yellow] GLB export skipped: IfcConvert not found"
                                            )
                                            console.print(
                                                "    Install with: pip install ifcopenshell"
                                            )
                                        else:
                                            glb_exporter.ifc_to_glb(
                                                ifc_path=recipe.output.ifc_export.path,
                                                glb_path=recipe.output.ifc_export.glb_path,
                                                use_world_coords=recipe.output.ifc_export.glb_use_world_coords,
                                                center_model=recipe.output.ifc_export.glb_center_model,
                                            )

                                            if recipe.output.ifc_export.glb_path.exists():
                                                glb_mb = (
                                                    recipe.output.ifc_export.glb_path.stat().st_size
                                                    / (1024 * 1024)
                                                )
                                                console.print(
                                                    f"  [bold green]✓[/bold green] GLB export complete: {recipe.output.ifc_export.glb_path} ({glb_mb:.1f} MB)"
                                                )
                                    except Exception as glb_error:
                                        console.print(
                                            f"  [red]✗[/red] GLB export failed: {glb_error}"
                                        )
                                        if verbose:
                                            console.print_exception()

                                # Auto-export to OBJ ZIP if configured
                                if recipe.output.ifc_export.obj_zip_path:
                                    console.print(
                                        f"\n[bold]Auto-exporting to OBJ ZIP:[/bold] {recipe.output.ifc_export.obj_zip_path}"
                                    )
                                    try:
                                        from giskit.exporters.obj_zip_exporter import OBJZipExporter

                                        obj_exporter = OBJZipExporter()
                                        if not obj_exporter.is_available():
                                            console.print(
                                                "  [yellow]⚠[/yellow] OBJ export skipped: ifcopenshell not found"
                                            )
                                            console.print(
                                                "    Install with: pip install ifcopenshell"
                                            )
                                        else:
                                            obj_exporter.ifc_to_obj_zip(
                                                ifc_path=recipe.output.ifc_export.path,
                                                output_zip_path=recipe.output.ifc_export.obj_zip_path,
                                                use_world_coords=True,
                                            )

                                            if recipe.output.ifc_export.obj_zip_path.exists():
                                                obj_mb = (
                                                    recipe.output.ifc_export.obj_zip_path.stat().st_size
                                                    / (1024 * 1024)
                                                )
                                                console.print(
                                                    f"  [bold green]✓[/bold green] OBJ ZIP export complete: {recipe.output.ifc_export.obj_zip_path} ({obj_mb:.1f} MB)"
                                                )
                                    except Exception as obj_error:
                                        console.print(
                                            f"  [red]✗[/red] OBJ export failed: {obj_error}"
                                        )
                                        if verbose:
                                            console.print_exception()

                            except ImportError:
                                console.print(
                                    "  [yellow]⚠[/yellow] IFC export skipped: ifcopenshell not installed"
                                )
                                console.print("    Install with: pip install giskit[ifc]")
                            except Exception as ifc_error:
                                console.print(f"  [red]✗[/red] IFC export failed: {ifc_error}")
                                if verbose:
                                    console.print_exception()
                    elif output_format == "geojson":
                        # GeoJSON doesn't support layers - combine all
                        import geopandas as gpd

                        combined = gpd.GeoDataFrame(
                            gpd.pd.concat(layers.values(), ignore_index=True)
                        )
                        combined.to_file(output_path, driver="GeoJSON")
                        console.print(
                            f"\n[bold green]✓[/bold green] Successfully saved {len(combined)} features to {output_path}"
                        )
                    elif output_format == "shp":
                        # Shapefile doesn't support layers - combine all
                        import geopandas as gpd

                        combined = gpd.GeoDataFrame(
                            gpd.pd.concat(layers.values(), ignore_index=True)
                        )
                        combined.to_file(output_path, driver="ESRI Shapefile")
                        console.print(
                            f"\n[bold green]✓[/bold green] Successfully saved {len(combined)} features to {output_path}"
                        )
                    elif output_format == "fgb":
                        # FlatGeobuf doesn't support layers - combine all
                        import geopandas as gpd

                        combined = gpd.GeoDataFrame(
                            gpd.pd.concat(layers.values(), ignore_index=True)
                        )
                        combined.to_file(output_path, driver="FlatGeobuf")
                        console.print(
                            f"\n[bold green]✓[/bold green] Successfully saved {len(combined)} features to {output_path}"
                        )
                    elif output_format == "ifc":
                        # IFC export - need to save to temp GPKG first
                        import tempfile

                        import geopandas as gpd

                        try:
                            from giskit.exporters.ifc import IFCExporter
                        except ImportError:
                            console.print("[bold red]Error:[/bold red] IfcOpenShell not installed")
                            console.print("\nIFC export requires ifcopenshell.")
                            console.print("Install with: [bold]pip install giskit[ifc][/bold]")
                            raise click.Abort()

                        # Save to temporary GPKG
                        with tempfile.NamedTemporaryFile(suffix=".gpkg", delete=False) as tmp:
                            tmp_path = Path(tmp.name)

                        # Delete the temp file so geopandas can create it fresh
                        tmp_path.unlink()

                        try:
                            total_features = 0
                            for layer_name, gdf in layers.items():
                                save_gdf = gdf.copy()
                                for col in ["_provider", "_service", "_layer", "_collection"]:
                                    if col in save_gdf.columns:
                                        save_gdf = save_gdf.drop(columns=[col])
                                gdf.to_file(tmp_path, driver="GPKG", layer=layer_name)
                                total_features += len(gdf)

                            console.print(f"\nConverted {total_features} features to IFC format...")

                            # Determine IFC versions to export
                            ifc_versions: list[str] = []
                            if recipe.output.ifc_export and recipe.output.ifc_export.ifc_versions:
                                ifc_versions = recipe.output.ifc_export.ifc_versions
                            else:
                                ifc_versions = [
                                    recipe.output.ifc_export.ifc_version
                                    if recipe.output.ifc_export
                                    else "IFC4X3_ADD2"
                                ]

                            # Export each IFC version
                            for ifc_version in ifc_versions:
                                # Determine output path for this version
                                if len(ifc_versions) > 1:
                                    # Multiple versions: output_IFC4X3_ADD2.ifc
                                    versioned_path = output_path.with_stem(
                                        f"{output_path.stem}_{ifc_version}"
                                    )
                                else:
                                    versioned_path = output_path

                                console.print(f"  Exporting to {ifc_version}...")

                                exporter = IFCExporter(
                                    ifc_version=ifc_version,
                                    author="GISKit",
                                    organization="A190",
                                    color_overrides=recipe.output.ifc_export.layer_colors
                                    if recipe.output.ifc_export
                                    else None,
                                )

                                exporter.export(
                                    db_path=tmp_path,
                                    output_path=versioned_path,
                                    layers=None,
                                    normalize_z=recipe.output.ifc_export.normalize_z
                                    if recipe.output.ifc_export
                                    else True,
                                    site_name=recipe.output.ifc_export.site_name
                                    if recipe.output.ifc_export
                                    and recipe.output.ifc_export.site_name
                                    else "Site",
                                )

                                console.print(
                                    f"[bold green]✓[/bold green] Exported to {versioned_path}"
                                )

                                if versioned_path.exists():
                                    size_mb = versioned_path.stat().st_size / (1024 * 1024)
                                    console.print(f"  Size: {size_mb:.1f} MB")

                            console.print(
                                f"[bold green]✓[/bold green] Successfully exported {total_features} features"
                            )

                        finally:
                            # Clean up temp file
                            if tmp_path.exists():
                                tmp_path.unlink()

                    elif output_format == "glb":
                        # GLB export - need IFC first
                        import tempfile

                        import geopandas as gpd

                        try:
                            from giskit.exporters.glb_exporter import GLBExporter
                            from giskit.exporters.ifc import IFCExporter
                        except ImportError:
                            console.print(
                                "[bold red]Error:[/bold red] Required dependencies not installed"
                            )
                            console.print("\nGLB export requires ifcopenshell and pygltflib.")
                            console.print("Install with: [bold]pip install giskit[ifc][/bold]")
                            raise click.Abort()

                        # Save to temporary GPKG and IFC
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
                                save_gdf = gdf.copy()
                                for col in ["_provider", "_service", "_layer", "_collection"]:
                                    if col in save_gdf.columns:
                                        save_gdf = save_gdf.drop(columns=[col])
                                gdf.to_file(tmp_gpkg_path, driver="GPKG", layer=layer_name)
                                total_features += len(gdf)

                            console.print(f"\nConverting {total_features} features to IFC...")

                            # Export to IFC
                            ifc_exporter = IFCExporter(
                                ifc_version=recipe.output.ifc_export.ifc_version
                                if recipe.output.ifc_export
                                else "IFC4X3_ADD2",
                                author="GISKit",
                                organization="A190",
                                color_overrides=recipe.output.ifc_export.layer_colors
                                if recipe.output.ifc_export
                                else None,
                            )

                            ifc_exporter.export(
                                db_path=tmp_gpkg_path,
                                output_path=tmp_ifc_path,
                                layers=None,
                                normalize_z=recipe.output.ifc_export.normalize_z
                                if recipe.output.ifc_export
                                else True,
                                site_name=recipe.output.ifc_export.site_name
                                if recipe.output.ifc_export and recipe.output.ifc_export.site_name
                                else "Site",
                            )

                            console.print("Converting IFC to GLB...")

                            # Convert to GLB
                            glb_exporter = GLBExporter()
                            if not glb_exporter.is_available():
                                console.print(
                                    "[yellow]⚠[/yellow] GLB export skipped: IfcConvert not found"
                                )
                                console.print("Install with: pip install ifcopenshell")
                                raise click.Abort()

                            glb_exporter.ifc_to_glb(
                                ifc_path=tmp_ifc_path,
                                glb_path=output_path,
                                use_world_coords=recipe.output.ifc_export.glb_use_world_coords
                                if recipe.output.ifc_export
                                else True,
                                center_model=recipe.output.ifc_export.glb_center_model
                                if recipe.output.ifc_export
                                else False,
                                compress=recipe.output.ifc_export.glb_compress
                                if recipe.output.ifc_export
                                else True,
                            )

                            console.print(
                                f"[bold green]✓[/bold green] Successfully exported {total_features} features to {output_path}"
                            )

                            if output_path.exists():
                                size_mb = output_path.stat().st_size / (1024 * 1024)
                                console.print(f"  Size: {size_mb:.1f} MB")

                        finally:
                            # Clean up temp files
                            if tmp_gpkg_path.exists():
                                tmp_gpkg_path.unlink()
                            if tmp_ifc_path.exists():
                                tmp_ifc_path.unlink()
            else:
                console.print("\n[yellow]No features downloaded[/yellow]")

        except Exception as download_error:
            console.print(f"\n[bold red]Download failed:[/bold red] {download_error}")
            if verbose:
                console.print_exception()
            raise click.Abort()

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        if verbose:
            console.print_exception()
        raise click.Abort()


@click.command()
@click.argument("recipe_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def validate(recipe_path: Path) -> None:
    """Validate a recipe file without running it.

    Examples:
        giskit validate recipe.json
    """
    try:
        with console.status("[bold green]Validating recipe..."):
            recipe = Recipe.from_file(recipe_path)

        console.print("[bold green]✓[/bold green] Recipe is valid")
        console.print(f"  Name: {recipe.name or 'Unnamed'}")
        console.print(f"  Datasets: {len(recipe.datasets)}")
        console.print(f"  Output: {recipe.output.path}")

    except Exception as e:
        console.print("[bold red]✗[/bold red] Recipe validation failed")
        console.print(f"[red]{e}[/red]")
        raise click.Abort()
