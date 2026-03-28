"""Reverse sync: copy scratch caches back to persistent storage."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from euler_files.config import load_config
from euler_files.lock import acquire_lock
from euler_files.markers import write_marker
from euler_files.rsync import run_rsync


def run_push(
    only_vars: Optional[List[str]] = None,
    dry_run: bool = False,
    quiet: bool = False,
) -> Dict[str, Any]:
    """Push scratch caches back to persistent storage.

    This is for persisting models downloaded during a job back to the
    network volume. Does NOT output export statements.
    """
    config = load_config()

    from euler_files.congruency import check_congruency, format_warnings
    cong_warnings = check_congruency(config)
    if cong_warnings:
        _err(format_warnings(cong_warnings), quiet=quiet)

    vars_to_push = {
        name: vc
        for name, vc in config.vars.items()
        if vc.enabled and (only_vars is None or name in only_vars)
    }

    if not vars_to_push:
        _err("No variables to push.", quiet=quiet)
        return {
            "command": "push",
            "dry_run": dry_run,
            "only_vars": only_vars or [],
            "results": [],
            "errors": [],
        }

    errors: List[str] = []
    results: List[Dict[str, Any]] = []

    for name, vc in vars_to_push.items():
        source = Path(vc.source)
        scratch = config.scratch_dir_for(name)

        if not scratch.exists():
            _err(f"[SKIP] {name}: scratch dir {scratch} does not exist", quiet=quiet)
            results.append({
                "name": name,
                "status": "scratch-missing",
                "source": str(source),
                "scratch": str(scratch),
            })
            continue

        if dry_run:
            _err(f"[DRY-RUN] Would push {scratch} -> {source}", quiet=quiet)
            results.append({
                "name": name,
                "status": "dry-run",
                "source": str(source),
                "scratch": str(scratch),
            })
            continue

        lock_path = config.lock_path_for(name)
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with acquire_lock(lock_path, timeout=config.lock_timeout_seconds):
                _err(f"[PUSH] {name}: {scratch} -> {source}", quiet=quiet)
                source.mkdir(parents=True, exist_ok=True)

                run_rsync(
                    source=scratch,
                    target=source,
                    extra_args=config.rsync_extra_args,
                )

                # Update marker so subsequent syncs know we're fresh
                write_marker(config, name, source)

            _err(f"[DONE] {name}", quiet=quiet)
            results.append({
                "name": name,
                "status": "pushed",
                "source": str(source),
                "scratch": str(scratch),
            })
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            _err(f"[ERROR] Failed to push {name}: {exc}", quiet=quiet)

    if errors:
        _err(f"\n{len(errors)} variable(s) failed to push.", quiet=quiet)

    return {
        "command": "push",
        "dry_run": dry_run,
        "only_vars": only_vars or [],
        "results": results,
        "errors": errors,
    }


def _err(msg: str, quiet: bool = False) -> None:
    if not quiet:
        print(msg, file=sys.stderr)
