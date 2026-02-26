"""Prune workflow: remove venvs, .sif images, or both."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from euler_files.config import load_config, save_config

console = Console(stderr=True)


class PruneMode:
    BOTH = "both"
    VENV_ONLY = "venv"
    SIF_ONLY = "sif"


def run_prune(
    image_name: Optional[str] = None,
    mode: Optional[str] = None,
    dry_run: bool = False,
    yes: bool = False,
    config_path: Optional[Path] = None,
) -> None:
    """Prune venvs, .sif images, or both."""
    config = load_config(config_path)

    if config.apptainer is None:
        raise FileNotFoundError(
            "Apptainer not configured. Run 'euler-files apptainer init' first."
        )

    apt = config.apptainer
    venv_base = Path(os.path.expandvars(os.path.expanduser(apt.venv_base)))
    sif_store = apt.sif_store_path()
    scratch_sif = apt.scratch_sif_path()

    # Select which image(s) to prune
    if image_name is None:
        image_name = _interactive_select(apt, venv_base, sif_store)
        if image_name is None:
            return

    # Select prune mode
    if mode is None:
        mode = _interactive_mode(image_name, venv_base, sif_store)
        if mode is None:
            return

    # Resolve what exists
    venv_path = venv_base / image_name
    sif_path = sif_store / f"{image_name}.sif"
    def_path = sif_store / f"{image_name}.def"
    scratch_sif_file = scratch_sif / f"{image_name}.sif"

    # Show what will be deleted
    targets: List[tuple[str, Path, str]] = []

    if mode in (PruneMode.BOTH, PruneMode.VENV_ONLY):
        if venv_path.exists():
            size = _get_size_display(venv_path)
            targets.append(("venv", venv_path, size))
        else:
            _err(f"  [SKIP] Venv not found: {venv_path}")

    if mode in (PruneMode.BOTH, PruneMode.SIF_ONLY):
        if sif_path.exists():
            size = _file_size_display(sif_path)
            targets.append(("sif", sif_path, size))
        else:
            _err(f"  [SKIP] SIF not found: {sif_path}")

        if def_path.exists():
            targets.append(("def", def_path, _file_size_display(def_path)))

        if scratch_sif_file.exists():
            size = _file_size_display(scratch_sif_file)
            targets.append(("scratch sif", scratch_sif_file, size))

    if not targets:
        _err("Nothing to prune.")
        return

    # Display summary
    console.print()
    table = Table(title=f"Prune '{image_name}'", border_style="red")
    table.add_column("Type", style="bold")
    table.add_column("Path")
    table.add_column("Size", justify="right")

    for kind, path, size in targets:
        table.add_row(kind, str(path), size)

    console.print(table)
    console.print()

    if dry_run:
        _err("[DRY-RUN] Would delete the above. Nothing was removed.")
        return

    # Confirm
    if not yes:
        if not Confirm.ask(
            "[red]Delete these files?[/red] This cannot be undone",
            default=False,
            console=console,
        ):
            _err("Aborted.")
            return

    # Execute deletions
    for kind, path, size in targets:
        try:
            if path.is_dir():
                shutil.rmtree(path)
                _err(f"  [DELETED] {kind}: {path}")
            elif path.is_file():
                path.unlink()
                _err(f"  [DELETED] {kind}: {path}")
        except OSError as exc:
            _err(f"  [ERROR] Failed to delete {path}: {exc}")

    # Update config: remove image entry if sif was deleted
    if mode in (PruneMode.BOTH, PruneMode.SIF_ONLY):
        if image_name in apt.images:
            del apt.images[image_name]
            save_config(config, path=config_path)
            _err(f"  [CONFIG] Removed '{image_name}' from config")

    _err("")
    _err("Done.")


def _interactive_select(apt, venv_base: Path, sif_store: Path) -> Optional[str]:
    """Show available images/venvs and let user pick one."""
    # Collect all known names: from config + from filesystem
    known: dict[str, dict[str, str]] = {}

    # From config
    for name, img in apt.images.items():
        known[name] = {
            "sif": "yes" if (sif_store / img.sif_filename).exists() else "missing",
            "venv": "yes" if (venv_base / name).exists() else "missing",
        }

    # From filesystem (venvs not in config)
    if venv_base.is_dir():
        for child in sorted(venv_base.iterdir()):
            if child.is_dir() and (child / "pyvenv.cfg").exists():
                if child.name not in known:
                    sif_exists = (sif_store / f"{child.name}.sif").exists()
                    known[child.name] = {
                        "sif": "yes" if sif_exists else "no",
                        "venv": "yes",
                    }

    if not known:
        _err("No images or venvs found to prune.")
        return None

    console.print()
    table = Table(title="Available for Pruning", border_style="red")
    table.add_column("#", style="dim", justify="right")
    table.add_column("Name", style="bold")
    table.add_column("Venv")
    table.add_column("SIF")

    names = sorted(known.keys())
    for i, name in enumerate(names, 1):
        info = known[name]
        venv_str = f"[green]{info['venv']}[/green]" if info["venv"] == "yes" else f"[dim]{info['venv']}[/dim]"
        sif_str = f"[green]{info['sif']}[/green]" if info["sif"] == "yes" else f"[dim]{info['sif']}[/dim]"
        table.add_row(str(i), name, venv_str, sif_str)

    console.print(table)
    console.print()

    choice = Prompt.ask("Select an environment to prune (number or name)", console=console)

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(names):
            return names[idx]
    except ValueError:
        pass

    if choice in known:
        return choice

    _err(f"Unknown environment: {choice}")
    return None


def _interactive_mode(image_name: str, venv_base: Path, sif_store: Path) -> Optional[str]:
    """Ask user what to delete."""
    venv_exists = (venv_base / image_name).is_dir()
    sif_exists = (sif_store / f"{image_name}.sif").exists()

    options: List[tuple[str, str, str]] = []

    if venv_exists and sif_exists:
        options.append((PruneMode.BOTH, "both", "Delete venv and .sif image"))
        options.append((PruneMode.VENV_ONLY, "venv", "Delete venv only (keep .sif)"))
        options.append((PruneMode.SIF_ONLY, "sif", "Delete .sif only (keep venv)"))
    elif venv_exists:
        options.append((PruneMode.VENV_ONLY, "venv", "Delete venv"))
    elif sif_exists:
        options.append((PruneMode.SIF_ONLY, "sif", "Delete .sif image"))
    else:
        _err(f"Nothing found for '{image_name}'.")
        return None

    console.print()
    console.print(f"[bold]What to remove for '{image_name}'?[/bold]")
    for i, (mode, label, desc) in enumerate(options, 1):
        console.print(f"  [bold]{i}[/bold]) [cyan]{label}[/cyan] — {desc}")

    console.print()
    choice = Prompt.ask(
        "Select mode (number or name)",
        default=options[0][1],
        console=console,
    )

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(options):
            return options[idx][0]
    except ValueError:
        pass

    for mode, label, _ in options:
        if choice == label:
            return mode

    _err(f"Unknown mode: {choice}")
    return None


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


def _file_size_display(path: Path) -> str:
    """Get human-readable file size."""
    try:
        size = path.stat().st_size
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
    except OSError:
        pass
    return "?"


def _err(msg: str) -> None:
    """Print to stderr."""
    print(msg, file=sys.stderr)
