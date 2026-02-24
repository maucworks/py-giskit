"""Run and validate recipe commands."""

import asyncio
import logging
from pathlib import Path

import click
from rich.console import Console

from giskit.core.recipe import Recipe
from giskit.core.runner import RecipeRunner

console = Console()


async def _execute_recipe(recipe: Recipe, recipe_dir: Path, console: Console, verbose: bool):
    """Execute a recipe asynchronously using RecipeRunner.

    Args:
        recipe: Recipe to execute
        recipe_dir: Directory containing the recipe file (for resolving relative paths)
        console: Rich console for output
        verbose: Verbose logging

    Returns:
        Dictionary mapping layer names to GeoDataFrames
    """
    # Create runner
    runner = RecipeRunner(recipe, recipe_dir)

    # Define progress callback for console output
    current_status = None

    def progress_callback(message: str, progress: float) -> None:
        nonlocal current_status
        # Update or create status display
        if current_status:
            current_status.stop()

        if progress < 1.0:
            current_status = console.status(f"[bold green]{message}")
            current_status.start()
        else:
            current_status = None

    # Execute recipe
    layers = await runner.execute(progress_callback if not verbose else None)

    # Print verbose output if requested
    if verbose and layers:
        console.print(f"\n[bold]Downloaded Layers:[/bold]")
        for layer_name, gdf in layers.items():
            console.print(f"  {layer_name}: {len(gdf)} features")

    return layers


@click.command()
@click.argument("recipe_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.option("--dry-run", is_flag=True, help="Validate without downloading")
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    default="WARNING",
    help="Set logging level (default: WARNING)",
)
def run(recipe_path: Path, verbose: bool, dry_run: bool, log_level: str) -> None:
    """Run a recipe to download spatial data.

    Examples:
        giskit run amsterdam.json
        giskit run --dry-run test.json
        giskit run --verbose utrecht.json
        giskit run --log-level INFO amsterdam.json
    """
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(levelname)s: %(message)s",
    )

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
