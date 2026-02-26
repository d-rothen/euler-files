"""Core sync algorithm: parallel rsync with locking and smart-skip."""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

from euler_files.config import EulerFilesConfig, VarConfig, load_config
from euler_files.lock import acquire_lock
from euler_files.markers import should_skip, write_marker
from euler_files.rsync import run_rsync


def run_sync(
    dry_run: bool = False,
    force: bool = False,
    only_vars: Optional[List[str]] = None,
    verbose: bool = False,
    config_path: Optional[Path] = None,
) -> None:
    """Main sync entry point.

    Syncs caches from persistent storage to scratch, then prints
    export statements to stdout for eval $(euler-files sync).
    """
    config = load_config(config_path)

    from euler_files.congruency import check_congruency, format_warnings
    cong_warnings = check_congruency(config)
    if cong_warnings:
        _err(format_warnings(cong_warnings))

    _ensure_scratch_exists(config)

    # Filter to enabled vars, optionally subset
    vars_to_sync = {
        name: vc
        for name, vc in config.vars.items()
        if vc.enabled and (only_vars is None or name in only_vars)
    }

    if not vars_to_sync:
        _err("No variables to sync.")
        return

    _err(f"euler-files: syncing {len(vars_to_sync)} variable(s) to {config.scratch_base}")
    _err("")

    results: Dict[str, Path] = {}
    errors: List[str] = []

    with ThreadPoolExecutor(max_workers=config.parallel_jobs) as pool:
        futures = {
            pool.submit(
                _sync_one_var,
                config,
                name,
                vc,
                dry_run,
                force,
                verbose,
            ): name
            for name, vc in vars_to_sync.items()
        }

        for future in as_completed(futures):
            name = futures[future]
            try:
                scratch_path = future.result()
                results[name] = scratch_path
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                _err(f"  [ERROR] Failed to sync {name}: {exc}")

    # Summary: show what will be exported
    _err("")
    _err("Environment variables:")
    for name in sorted(results):
        scratch_path = results[name]
        old_val = os.environ.get(name)
        if old_val:
            _err(f"  {name}")
            _err(f"    was: {old_val}")
            _err(f"    now: {scratch_path}")
        else:
            _err(f"  {name}")
            _err(f"    set: {scratch_path}")

    _err("")

    # Output export statements to stdout (this is what eval captures)
    for name in sorted(results):
        scratch_path = results[name]
        print(f"export {name}={_shell_quote(str(scratch_path))}")

    if errors:
        _err(f"{len(errors)} variable(s) failed to sync.")
        sys.exit(1)
    else:
        _err("Done. All variables synced successfully.")


def _sync_one_var(
    config: EulerFilesConfig,
    var_name: str,
    var_config: VarConfig,
    dry_run: bool,
    force: bool,
    verbose: bool,
) -> Path:
    """Sync a single env var's cache. Returns the scratch path."""
    source = Path(var_config.source)
    target = config.scratch_dir_for(var_name)

    if not source.exists():
        _err(f"  [WARN] {var_name}: source {source} does not exist, skipping rsync")
        target.mkdir(parents=True, exist_ok=True)
        return target

    # Smart skip check
    if not force and should_skip(config, var_name, source):
        _err(f"  [SKIP] {var_name}: already up-to-date")
        return target

    if dry_run:
        _err(f"  [DRY-RUN] {var_name}: would sync {source} -> {target}")
        return target

    # Acquire flock (per-var lock file)
    lock_path = config.lock_path_for(var_name)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with acquire_lock(lock_path, timeout=config.lock_timeout_seconds):
        _err(f"  [SYNC] {var_name}: {source} -> {target}")
        target.mkdir(parents=True, exist_ok=True)

        run_rsync(
            source=source,
            target=target,
            extra_args=config.rsync_extra_args,
            verbose=verbose,
        )

        write_marker(config, var_name, source)

    return target


def _err(msg: str) -> None:
    """Print to stderr (never pollute stdout)."""
    print(msg, file=sys.stderr)


def _shell_quote(s: str) -> str:
    """Quote a string for safe shell usage."""
    if all(c.isalnum() or c in "/-_." for c in s):
        return s
    return "'" + s.replace("'", "'\\''") + "'"


def _ensure_scratch_exists(config: EulerFilesConfig) -> None:
    """Ensure the scratch base cache directory exists."""
    base = Path(config.scratch_base) / config.cache_root
    base.mkdir(parents=True, exist_ok=True)
