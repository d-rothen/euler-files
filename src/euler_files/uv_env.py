"""uv-backed environment helpers."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from euler_files.apptainer.venv import validate_venv
from euler_files.config import load_config

_CUDA_WHEEL_RE = re.compile(
    r"^[A-Za-z0-9_.-]+(?:\[[^]]+\])?==[^;\s]+\+(?P<variant>cpu|cu\d+)(?:\s*;.*)?$"
)


def infer_pytorch_extra_index_urls(requirements: Sequence[str]) -> List[str]:
    """Infer extra index URLs needed for PyTorch CPU/CUDA wheel variants."""
    variants = []
    for requirement in requirements:
        match = _CUDA_WHEEL_RE.match(requirement.strip())
        if match:
            variants.append(match.group("variant"))

    unique_variants = sorted(set(variants))
    if len(unique_variants) > 1:
        raise ValueError(
            "Conflicting PyTorch wheel variants requested: "
            + ", ".join(unique_variants)
        )

    if not unique_variants:
        return []

    return [f"https://download.pytorch.org/whl/{unique_variants[0]}"]


def resolve_venv_base(
    venv_base: Optional[str] = None,
    config_path: Optional[Path] = None,
) -> Path:
    """Resolve the base directory used for named venv operations."""
    if venv_base:
        return _expand_path(venv_base)

    config = _try_load_config(config_path)
    if config is not None and config.apptainer is not None and config.apptainer.venv_base:
        return _expand_path(config.apptainer.venv_base)

    env_venv_dir = os.environ.get("VENV_DIR")
    if env_venv_dir:
        return _expand_path(env_venv_dir)

    raise FileNotFoundError(
        "No venv base configured. Set apptainer.venv_base, pass --venv-base, or export VENV_DIR."
    )


def resolve_uv_cache_dir(
    uv_cache_dir: Optional[str] = None,
    config_path: Optional[Path] = None,
    required: bool = False,
) -> Optional[Path]:
    """Resolve the uv cache directory from explicit input, config, or environment."""
    if uv_cache_dir:
        return _expand_path(uv_cache_dir)

    config = _try_load_config(config_path)
    if config is not None and config.uv_cache_dir:
        return config.uv_cache_path()

    env_uv_cache_dir = os.environ.get("UV_CACHE_DIR")
    if env_uv_cache_dir:
        return _expand_path(env_uv_cache_dir)

    if required:
        raise FileNotFoundError(
            "No uv cache directory configured. Pass --uv-cache-dir, set config.uv_cache_dir, or export UV_CACHE_DIR."
        )
    return None


def ensure_uv_binary(dry_run: bool = False) -> str:
    """Return the uv binary path, allowing a dry-run placeholder."""
    uv_binary = shutil.which("uv")
    if uv_binary is None:
        if dry_run:
            return "uv"
        raise FileNotFoundError("uv not found in PATH.")
    return uv_binary


def merge_extra_index_urls(
    requirements: Sequence[str],
    extra_index_urls: Optional[Sequence[str]] = None,
) -> List[str]:
    """Combine explicit extra indexes with inferred PyTorch wheel indexes."""
    merged: List[str] = []
    for url in list(extra_index_urls or []) + infer_pytorch_extra_index_urls(requirements):
        if url not in merged:
            merged.append(url)
    return merged


def uv_pip_freeze(
    python_path: Path,
    quiet: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Run `uv pip freeze` for a given venv/interpreter path."""
    uv_binary = ensure_uv_binary(dry_run=dry_run)
    cmd = [uv_binary, "pip", "freeze", "--python", str(python_path)]

    if dry_run:
        return {
            "command": cmd,
            "lines": [],
            "text": "",
        }

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"uv pip freeze failed with exit code {result.returncode}")

    if not quiet and result.stderr:
        print(result.stderr, file=sys.stderr, end="")

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return {
        "command": cmd,
        "lines": lines,
        "text": "\n".join(lines),
    }


def run_venv_install(
    env_name: str,
    packages: Sequence[str],
    python: Optional[str] = None,
    venv_base: Optional[str] = None,
    dry_run: bool = False,
    config_path: Optional[Path] = None,
    quiet: bool = False,
    index_url: Optional[str] = None,
    extra_index_urls: Optional[Sequence[str]] = None,
    uv_cache_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or reuse a uv venv, then install packages into it."""
    if not env_name.strip():
        raise ValueError("Environment name is required.")
    if not packages:
        raise ValueError("At least one package requirement is required.")

    uv_binary = ensure_uv_binary(dry_run=dry_run)
    resolved_base = resolve_venv_base(venv_base=venv_base, config_path=config_path)
    resolved_base.mkdir(parents=True, exist_ok=True)
    resolved_uv_cache = resolve_uv_cache_dir(
        uv_cache_dir=uv_cache_dir,
        config_path=config_path,
        required=False,
    )

    venv_path = resolved_base / env_name
    create_cmd = build_uv_venv_command(uv_binary, venv_path, python=python)
    merged_extra_index_urls = merge_extra_index_urls(packages, extra_index_urls=extra_index_urls)
    install_cmd = build_uv_install_command(
        uv_binary,
        venv_path,
        packages=list(packages),
        index_url=index_url,
        extra_index_urls=merged_extra_index_urls,
    )

    env = build_uv_env(resolved_uv_cache)

    created = False
    if venv_path.exists():
        validate_venv(venv_path)
    else:
        created = True
        if not dry_run:
            run_uv_command(create_cmd, "uv venv", quiet=quiet, env=env)

    if not dry_run:
        run_uv_command(install_cmd, "uv pip install", quiet=quiet, env=env)

    return {
        "command": "venv-install",
        "env_name": env_name,
        "venv_path": str(venv_path),
        "venv_base": str(resolved_base),
        "created": created,
        "packages": list(packages),
        "python": python,
        "index_url": index_url,
        "extra_index_urls": merged_extra_index_urls,
        "uv_cache_dir": str(resolved_uv_cache) if resolved_uv_cache is not None else None,
        "dry_run": dry_run,
        "commands": [
            " ".join(create_cmd),
            " ".join(install_cmd),
        ],
    }


def build_uv_venv_command(
    uv_binary: str,
    venv_path: Path,
    python: Optional[str] = None,
) -> List[str]:
    """Build a uv venv command."""
    cmd = [uv_binary, "venv", str(venv_path)]
    if python:
        cmd.extend(["--python", python])
    return cmd


def build_uv_install_command(
    uv_binary: str,
    python_path: Path,
    packages: Sequence[str],
    requirements_file: Optional[Path] = None,
    index_url: Optional[str] = None,
    extra_index_urls: Optional[Sequence[str]] = None,
) -> List[str]:
    """Build a uv pip install command."""
    cmd = [uv_binary, "pip", "install", "--python", str(python_path)]
    if index_url:
        cmd.extend(["--index-url", index_url])
    for url in extra_index_urls or []:
        cmd.extend(["--extra-index-url", url])
    if requirements_file is not None:
        cmd.extend(["-r", str(requirements_file)])
    cmd.extend(list(packages))
    return cmd


def build_uv_env(uv_cache_dir: Optional[Path]) -> Optional[Dict[str, str]]:
    """Build a subprocess environment for uv commands."""
    if uv_cache_dir is None:
        return None
    env = os.environ.copy()
    env["UV_CACHE_DIR"] = str(uv_cache_dir)
    return env


def run_uv_command(
    cmd: List[str],
    label: str,
    quiet: bool,
    env: Optional[Dict[str, str]] = None,
) -> None:
    """Run a uv command, streaming output to stderr unless quiet."""
    result = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL if quiet else sys.stderr,
        stderr=subprocess.DEVNULL if quiet else sys.stderr,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed with exit code {result.returncode}")


def _expand_path(value: str) -> Path:
    """Expand shell-style path syntax into a Path."""
    return Path(os.path.expandvars(os.path.expanduser(value)))


def _try_load_config(config_path: Optional[Path]):
    """Best-effort config loading for helper defaults."""
    try:
        return load_config(config_path)
    except FileNotFoundError:
        return None
