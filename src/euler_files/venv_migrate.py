"""Utilities for rebuilding uv-managed venvs into new locations."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from euler_files.apptainer.venv import detect_python_version, list_venvs, validate_venv
from euler_files.config import MigrationRecord, load_config, save_config
from euler_files.rsync import run_rsync
from euler_files.uv_env import (
    build_uv_env,
    build_uv_install_command,
    build_uv_venv_command,
    ensure_uv_binary,
    merge_extra_index_urls,
    resolve_uv_cache_dir,
    resolve_venv_base,
    run_uv_command,
    uv_pip_freeze,
)

console = Console(stderr=True)


def run_single_venv_migration(
    source: Optional[str] = None,
    target: Optional[str] = None,
    python: Optional[str] = None,
    uv_cache_dir: Optional[str] = None,
    index_url: Optional[str] = None,
    extra_index_urls: Optional[Sequence[str]] = None,
    dry_run: bool = False,
    verify: bool = True,
    overwrite_target: bool = False,
    delete_source: bool = False,
    allow_copy: bool = False,
    quiet: bool = False,
    config_path: Optional[Path] = None,
    interactive: bool = True,
) -> Dict[str, Any]:
    """Rebuild one venv at a new target location using uv."""
    source_path, target_path = _resolve_single_paths(
        source,
        target,
        config_path,
        quiet,
        interactive=interactive,
    )

    if source_path == target_path:
        raise ValueError("Source and target venv paths must differ.")

    validate_venv(source_path)

    if target_path.exists() and not overwrite_target:
        raise ValueError(f"Target already exists: {target_path}. Use --overwrite-target.")

    detected_python = detect_python_version(source_path)
    freeze_info = uv_pip_freeze(source_path, quiet=quiet)
    requirements = freeze_info["lines"]
    warnings = detect_requirement_warnings(requirements)

    resolved_uv_cache = resolve_uv_cache_dir(
        uv_cache_dir=uv_cache_dir,
        config_path=config_path,
        required=False,
    )
    if resolved_uv_cache is not None:
        _check_same_filesystem(resolved_uv_cache, target_path, allow_copy=allow_copy)

    uv_binary = ensure_uv_binary(dry_run=dry_run)
    python_candidates = _python_candidates(detected_python, python)
    merged_extra_index_urls = merge_extra_index_urls(
        requirements,
        extra_index_urls=extra_index_urls,
    )

    create_command_candidates = [
        build_uv_venv_command(uv_binary, target_path, python=candidate)
        for candidate in python_candidates
    ]

    install_cmd_preview = build_uv_install_command(
        uv_binary,
        target_path,
        packages=[],
        requirements_file=Path("<requirements.txt>"),
        index_url=index_url,
        extra_index_urls=merged_extra_index_urls,
    )
    env_preview = build_uv_env(resolved_uv_cache)

    if dry_run:
        return {
            "command": "venv-migrate",
            "status": "dry-run",
            "source": str(source_path),
            "target": str(target_path),
            "python_version_detected": detected_python,
            "python_version_candidates": python_candidates,
            "python_version_used": python_candidates[0],
            "requirements_count": len(requirements),
            "warnings": warnings,
            "index_url": index_url,
            "extra_index_urls": merged_extra_index_urls,
            "uv_cache_dir": str(resolved_uv_cache) if resolved_uv_cache is not None else None,
            "commands": [" ".join(cmd) for cmd in create_command_candidates] + [" ".join(install_cmd_preview)],
            "env": env_preview or {},
            "verification": {
                "enabled": verify,
                "status": "planned" if verify else "skipped",
                "missing": [],
                "extra": [],
            },
            "deleted_source": False,
            "errors": [],
        }

    if target_path.exists():
        _remove_path(target_path)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    if resolved_uv_cache is not None:
        resolved_uv_cache.mkdir(parents=True, exist_ok=True)

    env = build_uv_env(resolved_uv_cache)
    create_info = _create_target_venv(
        target_path=target_path,
        python_candidates=python_candidates,
        uv_binary=uv_binary,
        env=env,
        quiet=quiet,
    )
    python_used = create_info["python_used"]

    install_result = _install_requirements(
        target_path=target_path,
        requirements=requirements,
        uv_binary=uv_binary,
        env=env,
        quiet=quiet,
        index_url=index_url,
        extra_index_urls=merged_extra_index_urls,
    )

    verification = {
        "enabled": verify,
        "status": "skipped",
        "missing": [],
        "extra": [],
    }
    errors: List[str] = []

    if verify:
        verification = verify_venv_migration(
            source_requirements=requirements,
            target_path=target_path,
            quiet=quiet,
        )
        if verification["status"] != "matched":
            errors.append("Verification failed: target requirements differ from source.")

    deleted_source = False
    if delete_source and not errors:
        _remove_path(source_path)
        deleted_source = True

    return {
        "command": "venv-migrate",
        "status": "migrated" if not errors else "verification-failed",
        "source": str(source_path),
        "target": str(target_path),
        "python_version_detected": detected_python,
        "python_version_candidates": python_candidates,
        "python_version_used": python_used,
        "requirements_count": len(requirements),
        "warnings": warnings,
        "index_url": index_url,
        "extra_index_urls": merged_extra_index_urls,
        "uv_cache_dir": str(resolved_uv_cache) if resolved_uv_cache is not None else None,
        "commands": create_info["commands"] + [install_result["command"]],
        "verification": verification,
        "deleted_source": deleted_source,
        "errors": errors,
    }


def run_venv_store_migration(
    old_venv_base: Optional[str] = None,
    new_venv_base: Optional[str] = None,
    old_uv_cache_dir: Optional[str] = None,
    new_uv_cache_dir: Optional[str] = None,
    env_names: Optional[Sequence[str]] = None,
    exclude_env_names: Optional[Sequence[str]] = None,
    index_url: Optional[str] = None,
    extra_index_urls: Optional[Sequence[str]] = None,
    dry_run: bool = False,
    verify: bool = True,
    continue_on_error: bool = False,
    overwrite_targets: bool = False,
    delete_old: bool = False,
    update_config: bool = True,
    allow_copy: bool = False,
    skip_cache_copy: bool = False,
    quiet: bool = False,
    config_path: Optional[Path] = None,
    interactive: bool = True,
) -> Dict[str, Any]:
    """Migrate a uv cache dir and all venvs under a venv base."""
    resolved_old_venv_base, resolved_new_venv_base, resolved_old_uv_cache, resolved_new_uv_cache = (
        _resolve_store_paths(
            old_venv_base,
            new_venv_base,
            old_uv_cache_dir,
            new_uv_cache_dir,
            config_path,
            quiet,
            interactive=interactive,
        )
    )

    if resolved_old_venv_base == resolved_new_venv_base:
        raise ValueError("Old and new venv base paths must differ.")
    if resolved_old_uv_cache == resolved_new_uv_cache:
        raise ValueError("Old and new uv cache paths must differ.")

    if not resolved_old_venv_base.is_dir():
        raise FileNotFoundError(f"Old venv base does not exist: {resolved_old_venv_base}")

    _check_same_filesystem(resolved_new_uv_cache, resolved_new_venv_base, allow_copy=allow_copy)

    selected_venvs = _select_venvs_for_store_migration(
        resolved_old_venv_base,
        env_names=env_names,
        exclude_env_names=exclude_env_names,
    )
    if not selected_venvs:
        raise ValueError(f"No venvs found to migrate in {resolved_old_venv_base}")

    shell_exports = {
        "VENV_DIR": str(resolved_new_venv_base),
        "UV_CACHE_DIR": str(resolved_new_uv_cache),
    }

    cache_copy = _copy_uv_cache(
        source=resolved_old_uv_cache,
        target=resolved_new_uv_cache,
        dry_run=dry_run,
        skip_cache_copy=skip_cache_copy,
        quiet=quiet,
    )

    results = []
    errors: List[str] = []

    for venv_info in selected_venvs:
        target_path = resolved_new_venv_base / venv_info.name
        result = run_single_venv_migration(
            source=str(venv_info.path),
            target=str(target_path),
            python=None,
            uv_cache_dir=str(resolved_new_uv_cache),
            index_url=index_url,
            extra_index_urls=extra_index_urls,
            dry_run=dry_run,
            verify=verify,
            overwrite_target=overwrite_targets,
            delete_source=False,
            allow_copy=allow_copy,
            quiet=quiet,
            config_path=config_path,
            interactive=False,
        )
        results.append(result)
        if result["errors"]:
            errors.extend(["{0}: {1}".format(venv_info.name, error) for error in result["errors"]])
            if not continue_on_error:
                break

    deleted_old = False
    config_updates: List[Dict[str, str]] = []

    if update_config and not errors and not dry_run:
        config_updates = _update_store_config(
            old_venv_base=resolved_old_venv_base,
            new_venv_base=resolved_new_venv_base,
            old_uv_cache_dir=resolved_old_uv_cache,
            new_uv_cache_dir=resolved_new_uv_cache,
            config_path=config_path,
        )

    if delete_old and not errors and not dry_run:
        if resolved_old_uv_cache.exists():
            _remove_path(resolved_old_uv_cache)
        _remove_path(resolved_old_venv_base)
        deleted_old = True

    status = "migrated"
    if dry_run:
        status = "dry-run"
    elif errors and results:
        status = "partial" if continue_on_error else "failed"
    elif errors:
        status = "failed"

    return {
        "command": "venv-migrate-store",
        "status": status,
        "old_venv_base": str(resolved_old_venv_base),
        "new_venv_base": str(resolved_new_venv_base),
        "old_uv_cache_dir": str(resolved_old_uv_cache),
        "new_uv_cache_dir": str(resolved_new_uv_cache),
        "cache_copy": cache_copy,
        "environments": results,
        "shell_exports": shell_exports,
        "config_updates": config_updates,
        "deleted_old": deleted_old,
        "warnings": cache_copy.get("warnings", []),
        "errors": errors,
    }


def verify_venv_migration(
    source_requirements: Sequence[str],
    target_path: Path,
    quiet: bool = False,
) -> Dict[str, Any]:
    """Compare source and target freeze output after migration."""
    target_freeze = uv_pip_freeze(target_path, quiet=quiet)
    source_set = _normalize_requirements(source_requirements)
    target_set = _normalize_requirements(target_freeze["lines"])
    missing = sorted(source_set - target_set)
    extra = sorted(target_set - source_set)
    status = "matched" if not missing and not extra else "mismatch"
    return {
        "enabled": True,
        "status": status,
        "missing": missing,
        "extra": extra,
    }


def detect_requirement_warnings(requirements: Sequence[str]) -> List[str]:
    """Report freeze lines that may not reinstall deterministically elsewhere."""
    warnings: List[str] = []
    for line in requirements:
        if line.startswith("-e "):
            warnings.append(f"Editable requirement may not reinstall deterministically: {line}")
        elif " @ file://" in line or line.startswith("file://"):
            warnings.append(f"Local file requirement may not exist on the target system: {line}")
        elif " @ git+" in line or " @ hg+" in line or " @ svn+" in line:
            warnings.append(f"VCS requirement may require network access or credentials: {line}")
        elif line.startswith("/") or line.startswith("./") or line.startswith("../"):
            warnings.append(f"Local path requirement may not exist on the target system: {line}")
    return warnings


def _resolve_single_paths(
    source: Optional[str],
    target: Optional[str],
    config_path: Optional[Path],
    quiet: bool,
    interactive: bool,
) -> Tuple[Path, Path]:
    """Resolve source and target paths, optionally prompting interactively."""
    resolved_source = Path(os.path.expandvars(os.path.expanduser(source))) if source else None
    resolved_target = Path(os.path.expandvars(os.path.expanduser(target))) if target else None

    if resolved_source is not None and resolved_target is not None:
        return resolved_source, resolved_target

    if not interactive:
        missing = []
        if resolved_source is None:
            missing.append("source")
        if resolved_target is None:
            missing.append("target")
        raise ValueError(
            "Missing required arguments for non-interactive migration: {0}".format(
                ", ".join(missing)
            )
        )

    if resolved_source is None:
        resolved_source = _interactive_source_venv(config_path, quiet)
    if resolved_target is None:
        answer = Prompt.ask("Target venv path", console=console)
        resolved_target = Path(os.path.expandvars(os.path.expanduser(answer)))
    return resolved_source, resolved_target


def _interactive_source_venv(config_path: Optional[Path], quiet: bool) -> Path:
    """Interactively select a source venv path."""
    try:
        venv_base = resolve_venv_base(config_path=config_path)
    except FileNotFoundError:
        answer = Prompt.ask("Source venv path", console=console)
        return Path(os.path.expandvars(os.path.expanduser(answer)))

    venvs = list_venvs(venv_base)
    if not venvs:
        answer = Prompt.ask("Source venv path", console=console)
        return Path(os.path.expandvars(os.path.expanduser(answer)))

    if not quiet:
        table = Table(title="Available Venvs", border_style="blue")
        table.add_column("#", justify="right")
        table.add_column("Name", style="bold")
        table.add_column("Python")
        table.add_column("Path")
        for idx, venv in enumerate(venvs, 1):
            table.add_row(str(idx), venv.name, venv.python_version, str(venv.path))
        console.print()
        console.print(table)
        console.print()

    choice = Prompt.ask("Select source venv (number or path)", console=console)
    try:
        index = int(choice) - 1
        if 0 <= index < len(venvs):
            return venvs[index].path
    except ValueError:
        pass
    candidate = Path(os.path.expandvars(os.path.expanduser(choice)))
    if candidate.exists():
        return candidate
    raise ValueError(f"Unknown source venv selection: {choice}")


def _resolve_store_paths(
    old_venv_base: Optional[str],
    new_venv_base: Optional[str],
    old_uv_cache_dir: Optional[str],
    new_uv_cache_dir: Optional[str],
    config_path: Optional[Path],
    quiet: bool,
    interactive: bool,
) -> Tuple[Path, Path, Path, Path]:
    """Resolve bulk migration paths, prompting if needed."""
    if old_venv_base:
        resolved_old_venv_base = Path(os.path.expandvars(os.path.expanduser(old_venv_base)))
    else:
        try:
            resolved_old_venv_base = resolve_venv_base(config_path=config_path)
        except FileNotFoundError:
            if not interactive:
                raise
            answer = Prompt.ask("Current venv base", console=console)
            resolved_old_venv_base = Path(os.path.expandvars(os.path.expanduser(answer)))

    old_uv_cache = resolve_uv_cache_dir(
        uv_cache_dir=old_uv_cache_dir,
        config_path=config_path,
        required=False,
    )
    if old_uv_cache is None:
        if not interactive:
            raise FileNotFoundError("Old uv cache directory is required.")
        answer = Prompt.ask("Current UV_CACHE_DIR", console=console)
        old_uv_cache = Path(os.path.expandvars(os.path.expanduser(answer)))

    if new_venv_base is None:
        if not interactive:
            raise ValueError("new_venv_base is required for non-interactive store migration.")
        answer = Prompt.ask("New venv base", console=console)
        new_venv_base = answer
    if new_uv_cache_dir is None:
        if not interactive:
            raise ValueError("new_uv_cache_dir is required for non-interactive store migration.")
        answer = Prompt.ask("New UV_CACHE_DIR", console=console)
        new_uv_cache_dir = answer

    return (
        resolved_old_venv_base,
        Path(os.path.expandvars(os.path.expanduser(new_venv_base))),
        old_uv_cache,
        Path(os.path.expandvars(os.path.expanduser(new_uv_cache_dir))),
    )


def _select_venvs_for_store_migration(
    old_venv_base: Path,
    env_names: Optional[Sequence[str]],
    exclude_env_names: Optional[Sequence[str]],
) -> List[Any]:
    """Filter discovered venvs for bulk migration."""
    envs = list_venvs(old_venv_base)
    include = set(env_names or [])
    exclude = set(exclude_env_names or [])
    selected = []
    for venv in envs:
        if include and venv.name not in include:
            continue
        if venv.name in exclude:
            continue
        selected.append(venv)
    return selected


def _copy_uv_cache(
    source: Path,
    target: Path,
    dry_run: bool,
    skip_cache_copy: bool,
    quiet: bool,
) -> Dict[str, Any]:
    """Copy the uv cache tree to the new location."""
    warnings: List[str] = []
    if skip_cache_copy:
        return {
            "status": "skipped",
            "source": str(source),
            "target": str(target),
            "warnings": warnings,
        }

    if not source.exists():
        warnings.append(f"Old uv cache directory does not exist: {source}")
        return {
            "status": "source-missing",
            "source": str(source),
            "target": str(target),
            "warnings": warnings,
        }

    if dry_run:
        return {
            "status": "dry-run",
            "source": str(source),
            "target": str(target),
            "warnings": warnings,
        }

    target.mkdir(parents=True, exist_ok=True)
    run_rsync(source=source, target=target)
    return {
        "status": "copied",
        "source": str(source),
        "target": str(target),
        "warnings": warnings,
    }


def _update_store_config(
    old_venv_base: Path,
    new_venv_base: Path,
    old_uv_cache_dir: Path,
    new_uv_cache_dir: Path,
    config_path: Optional[Path],
) -> List[Dict[str, str]]:
    """Update config paths after a successful bulk migration."""
    try:
        config = load_config(config_path)
    except FileNotFoundError:
        return []

    updates: List[Dict[str, str]] = []
    now = time.time()

    if str(config.uv_cache_path()) != str(new_uv_cache_dir):
        old_value = str(config.uv_cache_path()) if config.uv_cache_dir else str(old_uv_cache_dir)
        config.uv_cache_dir = str(new_uv_cache_dir)
        config.migrations.append(
            MigrationRecord(
                old_path=old_value,
                new_path=str(new_uv_cache_dir),
                migrated_at=now,
                field_name="uv_cache_dir",
            )
        )
        updates.append({"field": "uv_cache_dir", "value": str(new_uv_cache_dir)})

    if config.apptainer is not None:
        current_venv_base = Path(os.path.expandvars(os.path.expanduser(config.apptainer.venv_base)))
        if str(current_venv_base) == str(old_venv_base):
            config.apptainer.venv_base = str(new_venv_base)
            config.migrations.append(
                MigrationRecord(
                    old_path=str(old_venv_base),
                    new_path=str(new_venv_base),
                    migrated_at=now,
                    field_name="venv_base",
                )
            )
            updates.append({"field": "venv_base", "value": str(new_venv_base)})

    if updates:
        save_config(config, path=config_path)
    return updates


def _create_target_venv(
    target_path: Path,
    python_candidates: Sequence[str],
    uv_binary: str,
    env: Optional[Dict[str, str]],
    quiet: bool,
) -> Dict[str, Any]:
    """Try Python candidates until uv venv creation succeeds."""
    commands = []
    errors: List[str] = []
    for candidate in python_candidates:
        cmd = build_uv_venv_command(uv_binary, target_path, python=candidate)
        commands.append(" ".join(cmd))
        try:
            run_uv_command(cmd, "uv venv", quiet=quiet, env=env)
            return {
                "python_used": candidate,
                "commands": commands,
            }
        except RuntimeError as exc:
            errors.append(str(exc))
            if target_path.exists():
                _remove_path(target_path)
    raise RuntimeError(
        "Unable to create target venv with Python candidates {0}: {1}".format(
            list(python_candidates),
            "; ".join(errors),
        )
    )


def _install_requirements(
    target_path: Path,
    requirements: Sequence[str],
    uv_binary: str,
    env: Optional[Dict[str, str]],
    quiet: bool,
    index_url: Optional[str],
    extra_index_urls: Sequence[str],
) -> Dict[str, Any]:
    """Install a frozen requirements set into the target venv."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
        handle.write("\n".join(requirements) + "\n")
        requirements_path = Path(handle.name)

    try:
        cmd = build_uv_install_command(
            uv_binary,
            target_path,
            packages=[],
            requirements_file=requirements_path,
            index_url=index_url,
            extra_index_urls=extra_index_urls,
        )
        run_uv_command(cmd, "uv pip install", quiet=quiet, env=env)
        return {
            "command": " ".join(cmd),
            "requirements_file": str(requirements_path),
        }
    finally:
        if requirements_path.exists():
            requirements_path.unlink()


def _python_candidates(detected_python: str, override_python: Optional[str]) -> List[str]:
    """Build Python version candidates for venv creation."""
    if override_python:
        return [override_python]

    candidates = [detected_python]
    major_minor = ".".join(detected_python.split(".")[:2])
    if major_minor and major_minor not in candidates:
        candidates.append(major_minor)
    return candidates


def _normalize_requirements(requirements: Sequence[str]) -> Set[str]:
    """Normalize freeze output for set comparison."""
    return {line.strip() for line in requirements if line.strip()}


def _check_same_filesystem(cache_path: Path, target_path: Path, allow_copy: bool) -> None:
    """Require cache and target to share a filesystem unless copy mode is allowed."""
    cache_device = _device_for_path(cache_path)
    target_device = _device_for_path(target_path)
    if cache_device != target_device and not allow_copy:
        raise ValueError(
            "UV cache and target venv directory are on different filesystems. "
            "Use --allow-copy to proceed without hardlink optimization."
        )


def _device_for_path(path: Path) -> int:
    """Return the device id for a path or its nearest existing parent."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return probe.stat().st_dev


def _remove_path(path: Path) -> None:
    """Remove a file or directory tree."""
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()
