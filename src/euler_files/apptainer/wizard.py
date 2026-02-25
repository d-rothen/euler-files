"""Interactive setup wizard for apptainer image management."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from euler_files.config import (
    CONFIG_PATH,
    ApptainerConfig,
    EulerFilesConfig,
    load_config,
    save_config,
)
from euler_files.apptainer.venv import list_venvs

console = Console(stderr=True)


def run_apptainer_wizard() -> None:
    """Run the interactive apptainer setup wizard."""
    console.print()
    console.print(
        Panel.fit(
            "[bold blue]euler-files[/bold blue] apptainer setup\n\n"
            "Package Python venvs into Apptainer .sif images\n"
            "for fast loading on shared filesystems.",
            border_style="blue",
            padding=(1, 2),
        )
    )
    console.print()

    # Step 1: Load existing config (need scratch_base)
    config = _load_existing_config()
    if config is None:
        return

    # Step 2: Check apptainer availability
    _check_apptainer()

    # Step 3: Check existing apptainer config
    if config.apptainer is not None:
        console.print("[yellow]Existing apptainer config found.[/yellow]")
        if not Confirm.ask("Overwrite apptainer configuration?", default=False, console=console):
            console.print("[dim]Aborted.[/dim]")
            return

    # Step 4: Configure venv base directory
    venv_base = _configure_venv_base()

    # Step 5: Configure SIF persistent storage
    sif_store = _configure_sif_store()

    # Step 6: Configure scratch SIF directory
    scratch_sif_dir = _configure_scratch_sif_dir(config.scratch_base)

    # Step 7: Advanced settings
    base_image, container_venv_path, build_args = _advanced_settings()

    # Step 8: Show discovered venvs
    _show_discovered_venvs(venv_base)

    # Step 9: Build config and show summary
    apptainer_config = ApptainerConfig(
        venv_base=venv_base,
        sif_store=sif_store,
        scratch_sif_dir=scratch_sif_dir,
        base_image=base_image,
        container_venv_path=container_venv_path,
        build_args=build_args,
    )
    _show_summary(apptainer_config)

    # Step 10: Save
    console.print()
    if Confirm.ask("Save configuration?", default=True, console=console):
        config.apptainer = apptainer_config
        save_config(config)
        console.print(f"\n[green]Apptainer config saved to {CONFIG_PATH}[/green]")
        _show_next_steps()
    else:
        console.print("[dim]Aborted.[/dim]")


def _load_existing_config() -> Optional[EulerFilesConfig]:
    """Load existing euler-files config. Returns None if not found."""
    try:
        return load_config()
    except FileNotFoundError:
        console.print(
            "[red]No euler-files config found.[/red]\n"
            "Run [green]euler-files init[/green] first to set up scratch base."
        )
        return None
    except ValueError as exc:
        console.print(f"[red]Config error: {exc}[/red]")
        return None


def _check_apptainer() -> None:
    """Check if apptainer is available and warn if not."""
    if shutil.which("apptainer") is None:
        console.print(
            "[yellow]Warning: 'apptainer' not found in PATH.[/yellow]\n"
            "  You may need to load it first, e.g.: [green]module load apptainer[/green]\n"
            "  Configuration will proceed, but builds will fail without it.\n"
        )


def _configure_venv_base() -> str:
    """Prompt for venv base directory."""
    console.print("[bold]Venv base directory[/bold]")
    console.print("[dim]Where your uv venvs are stored (e.g. $VENV_DIR or ~/venvs).[/dim]")
    console.print()

    venv_dir_env = os.environ.get("VENV_DIR")
    if venv_dir_env:
        console.print(f"  [green]$VENV_DIR[/green] = {venv_dir_env}")
        if Confirm.ask(f"Use {venv_dir_env} as venv base?", default=True, console=console):
            return "$VENV_DIR"

    while True:
        path = Prompt.ask("Enter venv base directory", console=console)
        expanded = os.path.expandvars(os.path.expanduser(path))
        if Path(expanded).is_dir():
            venvs = list_venvs(Path(expanded))
            if venvs:
                console.print(f"  Found {len(venvs)} venv(s).")
            else:
                console.print("  [yellow]No venvs found in this directory.[/yellow]")
                if not Confirm.ask("Use it anyway?", default=False, console=console):
                    continue
            return path
        console.print(f"  [red]Directory {expanded} does not exist.[/red]")
        if Confirm.ask("Use it anyway?", default=False, console=console):
            return path


def _configure_sif_store() -> str:
    """Prompt for persistent SIF storage directory."""
    console.print()
    console.print("[bold]SIF persistent storage[/bold]")
    console.print("[dim]Where built .sif files will be stored permanently.[/dim]")
    console.print()

    default = str(Path.home() / ".cache" / "euler-files" / "sif")
    path = Prompt.ask("SIF storage directory", default=default, console=console)
    expanded = os.path.expandvars(os.path.expanduser(path))
    Path(expanded).mkdir(parents=True, exist_ok=True)
    return path


def _configure_scratch_sif_dir(scratch_base: str) -> str:
    """Prompt for scratch SIF directory."""
    console.print()
    console.print("[bold]Scratch SIF directory[/bold]")
    console.print("[dim]Where .sif files will be synced to on scratch for fast access.[/dim]")
    console.print()

    default = f"{scratch_base}/.cache/euler-files/sif"
    path = Prompt.ask("Scratch SIF directory", default=default, console=console)
    return path


def _advanced_settings() -> tuple[str, str, list[str]]:
    """Prompt for advanced apptainer settings."""
    console.print()
    if not Confirm.ask("Configure advanced settings?", default=False, console=console):
        return "python:{version}-slim", "/opt/venv", ["--fakeroot"]

    console.print()
    base_image = Prompt.ask(
        "  Base image template ({version} = Python major.minor)",
        default="python:{version}-slim",
        console=console,
    )
    container_venv_path = Prompt.ask(
        "  Venv path inside container",
        default="/opt/venv",
        console=console,
    )

    build_args_str = Prompt.ask(
        "  Extra apptainer build flags (space-separated)",
        default="--fakeroot",
        console=console,
    )
    build_args = build_args_str.split()

    return base_image, container_venv_path, build_args


def _show_discovered_venvs(venv_base: str) -> None:
    """Show a table of discovered venvs."""
    expanded = Path(os.path.expandvars(os.path.expanduser(venv_base)))
    venvs = list_venvs(expanded)

    if not venvs:
        console.print("\n[dim]No venvs found yet. Build images after creating venvs.[/dim]")
        return

    console.print()
    table = Table(title="Discovered Venvs", border_style="blue")
    table.add_column("Name", style="bold")
    table.add_column("Python")
    table.add_column("Size", justify="right")

    for venv in venvs:
        size = _get_size_display(venv.path)
        table.add_row(venv.name, venv.python_version, size)

    console.print(table)


def _show_summary(config: ApptainerConfig) -> None:
    """Display a summary of the apptainer configuration."""
    console.print()
    table = Table(title="Apptainer Configuration", border_style="blue")
    table.add_column("Setting", style="bold")
    table.add_column("Value")

    table.add_row("Venv base", config.venv_base)
    table.add_row("SIF storage", config.sif_store)
    table.add_row("Scratch SIF dir", config.scratch_sif_dir)
    table.add_row("Base image", config.base_image)
    table.add_row("Container venv path", config.container_venv_path)
    table.add_row("Build args", " ".join(config.build_args))

    console.print(table)


def _show_next_steps() -> None:
    """Print usage instructions for apptainer commands."""
    console.print()
    console.print(Panel(
        "[bold]Next steps:[/bold]\n\n"
        "1. Build an image from a venv:\n"
        "   [green]euler-files apptainer build my-venv[/green]\n\n"
        "2. Or pick interactively:\n"
        "   [green]euler-files apptainer build[/green]\n\n"
        "3. Sync images to scratch (in sbatch scripts):\n"
        "   [green]euler-files apptainer sync[/green]\n\n"
        "4. Use in a job:\n"
        "   [green]apptainer exec $SCRATCH/.cache/euler-files/sif/my-venv.sif python train.py[/green]",
        title="Apptainer",
        border_style="green",
        padding=(1, 2),
    ))


def _get_size_display(path: Path) -> str:
    """Get human-readable size of a directory."""
    try:
        result = subprocess.run(
            ["du", "-sh", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.split()[0]
    except (subprocess.TimeoutExpired, FileNotFoundError, IndexError):
        pass
    return "?"
