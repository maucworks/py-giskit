"""Export commands for GISKit CLI."""

from pathlib import Path
from typing import Optional

import click
from rich.console import Console

console = Console()


@click.group()
def export():
    """Export data to different formats."""
    pass


@export.command()
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("output_path", type=click.Path(path_type=Path))
@click.option(
    "--version",
    "-v",
    "ifc_version",
    default="IFC4X3_ADD2",
    help="IFC schema version (IFC4X3_ADD2, IFC4, IFC2X3)",
)
@click.option("--site-name", "-s", default="Site", help="Name for the IFC site")
@click.option(
    "--absolute-z",
    is_flag=True,
    help="Keep absolute NAP elevations (default: normalize to ground)",
)
@click.option(
    "--ref-x", type=float, help="Reference point X coordinate (auto-detect if not specified)"
)
@click.option(
    "--ref-y", type=float, help="Reference point Y coordinate (auto-detect if not specified)"
)
def ifc(
    input_path: Path,
    output_path: Path,
    ifc_version: str,
    site_name: str,
    absolute_z: bool,
    ref_x: Optional[float],
    ref_y: Optional[float],
) -> None:
    """Export GeoPackage to IFC format.

    IFC Georeferencing:
        - Site is always placed at (0,0,0) per IFC best practices
        - IfcMapConversion (IFC4+) provides proper georeferencing to RD (EPSG:28992)
        - BIM tools like Blender/Bonsai can use IfcMapConversion to position model

    Examples:
        giskit export ifc input.gpkg output.ifc
        giskit export ifc --version IFC4 input.gpkg output.ifc
        giskit export ifc --site-name "Amsterdam Dam" input.gpkg output.ifc
        giskit export ifc --absolute-z input.gpkg output.ifc
    """
    try:
        from giskit.exporters.ifc import IFCExporter
    except ImportError:
        console.print("[bold red]Error:[/bold red] IfcOpenShell not installed")
        console.print("\nIFC export requires ifcopenshell.")
        console.print("\nInstall using pip:")
        console.print("  [bold]pip install giskit[ifc][/bold]")
        console.print("\nOr separately:")
        console.print("  [bold]pip install ifcopenshell[/bold]")
        raise click.Abort()

    normalize_z = not absolute_z

    try:
        console.print(f"[bold green]Exporting to IFC:[/bold green] {output_path}")
        console.print(f"  Input: {input_path}")
        console.print(f"  IFC Version: {ifc_version}")
        console.print(f"  Site Name: {site_name}")
        console.print("  Site Placement: (0, 0, 0) + IfcMapConversion to RD")
        console.print(f"  Z-Normalization: {'enabled' if normalize_z else 'disabled'}")
        console.print()

        exporter = IFCExporter(ifc_version=ifc_version, author="GISKit", organization="A190")

        with console.status("[bold green]Exporting layers..."):
            exporter.export(
                db_path=input_path,
                output_path=output_path,
                layers=None,
                normalize_z=normalize_z,
                site_name=site_name,
                ref_x=ref_x,
                ref_y=ref_y,
            )

        console.print("\n[bold green]✓[/bold green] Export complete!")
        console.print(f"  Output: {output_path}")

        if output_path.exists():
            size_mb = output_path.stat().st_size / (1024 * 1024)
            console.print(f"  Size: {size_mb:.1f} MB")

    except Exception as e:
        console.print(f"[bold red]✗[/bold red] Export failed: {e}")
        raise click.Abort()


@export.command()
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("output_path", type=click.Path(path_type=Path))
@click.option("--world-coords/--local-coords", default=True, help="Use world coordinates")
@click.option("--uvs/--no-uvs", default=True, help="Generate UV coordinates")
@click.option("--center/--no-center", default=False, help="Center model at origin")
def glb(
    input_path: Path,
    output_path: Path,
    world_coords: bool,
    uvs: bool,
    center: bool,
) -> None:
    """Convert IFC to GLB format.

    Converts any IFC file to GLB (glTF binary) format for 3D visualization
    in web browsers and other viewers.

    By default:
        - Uses world coordinates (preserves geo-location)
        - Generates UV coordinates for textures
        - Does not center the model

    Examples:
        giskit export glb input.ifc output.glb
        giskit export glb --center input.ifc output.glb
        giskit export glb --local-coords input.ifc output.glb
        giskit export glb --no-uvs input.ifc output.glb
        giskit export glb --center --local-coords input.ifc output.glb
    """
    try:
        from giskit.exporters.glb_exporter import GLBExporter
    except ImportError:
        console.print("[bold red]Error:[/bold red] Required dependencies not installed")
        console.print("\nGLB export requires ifcopenshell and pygltflib.")
        console.print("\nInstall using pip:")
        console.print("  [bold]pip install giskit[ifc][/bold]")
        console.print("\nOr separately:")
        console.print("  [bold]pip install ifcopenshell pygltflib[/bold]")
        raise click.Abort()

    try:
        exporter = GLBExporter()

        if not exporter.is_available():
            console.print("[bold red]Error:[/bold red] GLB export dependencies not available")
            console.print(exporter.get_install_instructions())
            raise click.Abort()

        console.print(f"[bold green]Converting IFC to GLB:[/bold green] {output_path}")
        console.print(f"  Input: {input_path}")
        console.print(f"  World Coords: {'Yes' if world_coords else 'No (local)'}")
        console.print(f"  Generate UVs: {'Yes' if uvs else 'No'}")
        console.print(f"  Center Model: {'Yes' if center else 'No'}")
        console.print()

        exporter.ifc_to_glb(
            ifc_path=input_path,
            glb_path=output_path,
            use_world_coords=world_coords,
            generate_uvs=uvs,
            center_model=center,
        )

        console.print("\n[bold green]✓[/bold green] Conversion complete!")
        console.print(f"  Output: {output_path}")

        if output_path.exists():
            size_mb = output_path.stat().st_size / (1024 * 1024)
            console.print(f"  Size: {size_mb:.1f} MB")

    except Exception as e:
        console.print(f"[bold red]✗[/bold red] Conversion failed: {e}")
        raise click.Abort()


@export.command()
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("output_path", type=click.Path(path_type=Path))
@click.option("--world-coords/--local-coords", default=True, help="Use world coordinates")
def obj(
    input_path: Path,
    output_path: Path,
    world_coords: bool,
) -> None:
    """Convert IFC to OBJ ZIP format.

    Converts IFC file to a ZIP containing OBJ+MTL files per layer.
    Each layer becomes a separate OBJ file with its own materials.
    Includes a manifest.json with layer metadata.

    Examples:
        giskit export obj input.ifc output.zip
        giskit export obj --local-coords input.ifc output.zip
    """
    try:
        from giskit.exporters.obj_zip_exporter import OBJZipExporter
    except ImportError:
        console.print("[bold red]Error:[/bold red] Required dependencies not installed")
        console.print("\nOBJ export requires ifcopenshell.")
        console.print("\nInstall using pip:")
        console.print("  [bold]pip install giskit[ifc][/bold]")
        raise click.Abort()

    # Auto .zip suffix
    if output_path.suffix.lower() != ".zip":
        output_path = output_path.with_suffix(".zip")

    try:
        exporter = OBJZipExporter()

        if not exporter.is_available():
            console.print("[bold red]Error:[/bold red] OBJ export dependencies not available")
            console.print("Install with: pip install ifcopenshell")
            raise click.Abort()

        console.print(f"[bold green]Converting IFC to OBJ ZIP:[/bold green] {output_path}")
        console.print(f"  Input: {input_path}")
        console.print(f"  World Coords: {'Yes' if world_coords else 'No (local)'}")
        console.print()

        exporter.ifc_to_obj_zip(
            ifc_path=input_path,
            output_zip_path=output_path,
            use_world_coords=world_coords,
        )

        console.print("\n[bold green]✓[/bold green] Conversion complete!")
        console.print(f"  Output: {output_path}")

        if output_path.exists():
            size_mb = output_path.stat().st_size / (1024 * 1024)
            console.print(f"  Size: {size_mb:.1f} MB")

    except Exception as e:
        console.print(f"[bold red]✗[/bold red] Conversion failed: {e}")
        raise click.Abort()
