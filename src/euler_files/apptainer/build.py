"""Build workflow: package a uv venv into an Apptainer .sif image."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from euler_files.config import (
    ApptainerImageConfig,
    load_config,
    save_config,
)
from euler_files.apptainer.deffile import generate_def_file
from euler_files.apptainer.venv import VenvInfo, detect_python_version, list_venvs, validate_venv

console = Console(stderr=True)


def run_build(
    venv_name: Optional[str] = None,
    force: bool = False,
    dry_run: bool = False,
    config_path: Optional[Path] = None,
) -> None:
    """Build an Apptainer .sif image from a uv venv."""
    config = load_config(config_path)

    if config.apptainer is None:
        raise FileNotFoundError(
            "Apptainer not configured. Run 'euler-files apptainer init' first."
        )

    apt = config.apptainer
    venv_base = Path(os.path.expandvars(os.path.expanduser(apt.venv_base)))

    # Resolve which venv to build
    if venv_name is None:
        venv_name = _interactive_select(venv_base, apt)
        if venv_name is None:
            return

    venv_path = venv_base / venv_name
    validate_venv(venv_path)
    python_version = detect_python_version(venv_path)

    _err(f"euler-files: building apptainer image for '{venv_name}'")
    _err(f"  venv: {venv_path}")
    _err(f"  python: {python_version}")

    # Determine output paths
    sif_store = apt.sif_store_path()
    sif_store.mkdir(parents=True, exist_ok=True)

    sif_filename = f"{venv_name}.sif"
    sif_path = sif_store / sif_filename
    def_path = sif_store / f"{venv_name}.def"
    tar_path = sif_store / f"{venv_name}.tar"

    # Check existing .sif
    if sif_path.exists() and not force:
        _err(f"  [SKIP] {sif_path} already exists. Use --force to rebuild.")
        return

    if dry_run:
        # Generate def content with placeholder tar path for display
        def_content = generate_def_file(
            venv_name=venv_name,
            tar_path=str(tar_path),
            python_version=python_version,
            container_venv_path=apt.container_venv_path,
            base_image_template=apt.base_image,
        )
        _err(f"\n  [DRY-RUN] Would tar: {venv_path} -> {tar_path}")
        _err(f"  [DRY-RUN] Would write definition file to: {def_path}")
        _err(f"  [DRY-RUN] Would build: {sif_path}")
        _err(f"\n  Definition file contents:")
        _err("  " + "\n  ".join(def_content.splitlines()))
        cmd = ["apptainer", "build", *apt.build_args, str(sif_path), str(def_path)]
        _err(f"\n  Command: {' '.join(cmd)}")
        return

    # Step 1: Pre-pack the venv into a tarball
    # This is dramatically faster on shared HPC filesystems than letting
    # apptainer's %files copy thousands of individual files. tar reads
    # sequentially (one open, one stream) while %files does per-file
    # stat+open+read — tens of thousands of metadata operations.
    _err(f"  [TAR] Packing venv into tarball...")
    _err(f"    {venv_path} -> {tar_path}")
    _create_tarball(venv_path, tar_path)
    _err(f"  [TAR] Done ({_file_size_display(tar_path)})")

    try:
        # Step 2: Generate definition file (references the tarball)
        def_content = generate_def_file(
            venv_name=venv_name,
            tar_path=str(tar_path),
            python_version=python_version,
            container_venv_path=apt.container_venv_path,
            base_image_template=apt.base_image,
        )
        def_path.write_text(def_content)
        _err(f"  definition: {def_path}")

        # Step 3: Build the image
        cmd = ["apptainer", "build", *apt.build_args, str(sif_path), str(def_path)]
        _err(f"  command: {' '.join(cmd)}")
        _err("")

        try:
            result = subprocess.run(
                cmd,
                stdout=sys.stderr,
                stderr=sys.stderr,
            )
        except FileNotFoundError:
            raise FileNotFoundError(
                "apptainer not found. Try loading it first: module load apptainer"
            )

        if result.returncode != 0:
            raise RuntimeError(f"apptainer build failed with exit code {result.returncode}")
    finally:
        # Step 4: Clean up the tarball (can be very large)
        if tar_path.exists():
            _err(f"  [CLEANUP] Removing tarball {tar_path}")
            tar_path.unlink()

    # Update config with image metadata
    apt.images[venv_name] = ApptainerImageConfig(
        venv_name=venv_name,
        python_version=python_version,
        sif_filename=sif_filename,
        built_at=time.time(),
    )
    save_config(config, path=config_path)

    _err("")
    _err(f"  [OK] Built {sif_path}")
    _err("  Run 'euler-files apptainer sync' to copy to scratch.")


def _create_tarball(venv_path: Path, tar_path: Path) -> None:
    """Create a tarball from a venv directory.

    Uses tar directly (not Python's tarfile) because it handles
    symlinks, permissions, and large directories more reliably,
    and streams output sequentially which is critical for performance
    on shared filesystems.
    """
    # tar -cf output.tar -C /parent/dir venv_name
    # This puts venv_name/ at the top level of the archive
    cmd = [
        "tar", "cf", str(tar_path),
        "-C", str(venv_path.parent),
        venv_path.name,
    ]
    result = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"tar failed with exit code {result.returncode}: {result.stderr.strip()}"
        )


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


def _interactive_select(venv_base: Path, apt) -> Optional[str]:
    """Interactively select a venv to build."""
    venvs = list_venvs(venv_base)
    if not venvs:
        _err(f"No venvs found in {venv_base}")
        return None

    console.print()
    table = Table(title="Available Venvs", border_style="blue")
    table.add_column("#", style="dim", justify="right")
    table.add_column("Name", style="bold")
    table.add_column("Python")
    table.add_column("Built?")

    for i, venv in enumerate(venvs, 1):
        built = "[green]yes[/green]" if venv.name in apt.images else "[dim]no[/dim]"
        table.add_row(str(i), venv.name, venv.python_version, built)

    console.print(table)
    console.print()

    choice = Prompt.ask(
        "Select a venv (number or name)",
        console=console,
    )

    # Try as number first
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(venvs):
            return venvs[idx].name
    except ValueError:
        pass

    # Try as name
    for venv in venvs:
        if venv.name == choice:
            return venv.name

    _err(f"Unknown venv: {choice}")
    return None


def _err(msg: str) -> None:
    """Print to stderr."""
    print(msg, file=sys.stderr)
