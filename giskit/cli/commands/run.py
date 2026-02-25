"""Run and validate recipe commands."""

import asyncio
import logging
from pathlib import Path

import click
from rich.console import Console

from giskit.core.output import OutputManager
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
        console.print("\n[bold]Downloaded Layers:[/bold]")
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
            # Save to output file using OutputManager
            if layers is not None and len(layers) > 0:
                output_manager = OutputManager(recipe, recipe_path.parent)

                # Define progress callback for console output
                def output_progress(message: str, level: str) -> None:
                    if level == "success":
                        console.print(f"[bold green]✓[/bold green] {message}")
                    elif level == "error":
                        console.print(f"[red]✗[/red] {message}")
                    elif level == "warning":
                        console.print(f"[yellow]⚠[/yellow] {message}")
                    else:  # info
                        console.print(f"  {message}")

                try:
                    output_manager.save_layers(layers, output_progress)
                except ImportError as e:
                    console.print(f"[red]✗[/red] Export failed: {e}")
                    if verbose:
                        console.print_exception()
                    raise click.Abort()
                except Exception as e:
                    console.print(f"[red]✗[/red] Failed to save output: {e}")
                    if verbose:
                        console.print_exception()
                    raise click.Abort()
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
