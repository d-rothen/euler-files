"""Sync apptainer .sif images from persistent storage to scratch."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

from euler_files.config import load_config
from euler_files.lock import acquire_lock
from euler_files.rsync import rsync_file


def run_apptainer_sync(
    dry_run: bool = False,
    force: bool = False,
    only_images: Optional[List[str]] = None,
    config_path: Optional[Path] = None,
) -> None:
    """Sync .sif images from persistent storage to scratch."""
    config = load_config(config_path)

    if config.apptainer is None:
        raise FileNotFoundError(
            "Apptainer not configured. Run 'euler-files apptainer init' first."
        )

    apt = config.apptainer
    sif_store = apt.sif_store_path()
    scratch_dir = apt.scratch_sif_path()

    # Filter images
    images = {
        name: img
        for name, img in apt.images.items()
        if img.enabled and (only_images is None or name in only_images)
    }

    if not images:
        _err("No apptainer images to sync.")
        return

    _err(f"euler-files: syncing {len(images)} apptainer image(s)")
    _err("")

    scratch_dir_expanded = Path(os.path.expandvars(str(scratch_dir)))
    scratch_dir_expanded.mkdir(parents=True, exist_ok=True)

    errors: List[str] = []

    for name, img in images.items():
        source = sif_store / img.sif_filename
        target = scratch_dir_expanded / img.sif_filename

        if not source.exists():
            _err(f"  [WARN] {name}: {source} does not exist, skipping")
            continue

        # Smart skip: compare mtimes
        if not force and target.exists():
            source_mtime = source.stat().st_mtime
            target_mtime = target.stat().st_mtime
            if target_mtime >= source_mtime:
                _err(f"  [SKIP] {name}: already up-to-date")
                continue

        if dry_run:
            _err(f"  [DRY-RUN] {name}: would sync {source} -> {target}")
            continue

        # Acquire per-image lock
        lock_path = scratch_dir_expanded / f".{name}.sif.lock"
        try:
            with acquire_lock(lock_path, timeout=config.lock_timeout_seconds):
                _err(f"  [SYNC] {name}: {source} -> {target}")
                rsync_file(source=source, target=target)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            _err(f"  [ERROR] Failed to sync {name}: {exc}")

    _err("")
    if errors:
        _err(f"{len(errors)} image(s) failed to sync.")
        sys.exit(1)
    else:
        _err("Done. All images synced successfully.")


def _err(msg: str) -> None:
    """Print to stderr."""
    print(msg, file=sys.stderr)
