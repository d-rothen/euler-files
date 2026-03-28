"""uv-backed environment installation helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
import re

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


def run_venv_install(
    env_name: str,
    packages: Sequence[str],
    python: Optional[str] = None,
    venv_base: Optional[str] = None,
    dry_run: bool = False,
    config_path: Optional[Path] = None,
    quiet: bool = False,
) -> Dict[str, Any]:
    """Create or reuse a uv venv, then install packages into it."""
    if not env_name.strip():
        raise ValueError("Environment name is required.")
    if not packages:
        raise ValueError("At least one package requirement is required.")

    uv_binary = shutil.which("uv")
    if uv_binary is None:
        if dry_run:
            uv_binary = "uv"
        else:
            raise FileNotFoundError("uv not found in PATH.")

    resolved_base = _resolve_venv_base(venv_base=venv_base, config_path=config_path)
    resolved_base.mkdir(parents=True, exist_ok=True)

    venv_path = resolved_base / env_name
    create_cmd = [uv_binary, "venv", str(venv_path)]
    if python:
        create_cmd.extend(["--python", python])

    extra_index_urls = infer_pytorch_extra_index_urls(packages)
    install_cmd = [uv_binary, "pip", "install", "--python", str(venv_path)]
    for url in extra_index_urls:
        install_cmd.extend(["--extra-index-url", url])
    install_cmd.extend(packages)

    created = False
    if venv_path.exists():
        validate_venv(venv_path)
    else:
        created = True
        if not dry_run:
            _run(create_cmd, "uv venv", quiet=quiet)

    if not dry_run:
        _run(install_cmd, "uv pip install", quiet=quiet)

    return {
        "command": "venv-install",
        "env_name": env_name,
        "venv_path": str(venv_path),
        "venv_base": str(resolved_base),
        "created": created,
        "packages": list(packages),
        "python": python,
        "extra_index_urls": extra_index_urls,
        "dry_run": dry_run,
        "commands": [
            " ".join(create_cmd),
            " ".join(install_cmd),
        ],
    }


def _resolve_venv_base(venv_base: Optional[str], config_path: Optional[Path]) -> Path:
    """Resolve the base directory used for named venv installation."""
    if venv_base:
        return Path(os.path.expandvars(os.path.expanduser(venv_base)))

    config = None
    try:
        config = load_config(config_path)
    except FileNotFoundError:
        config = None

    if config is not None and config.apptainer is not None and config.apptainer.venv_base:
        raw = config.apptainer.venv_base
        return Path(os.path.expandvars(os.path.expanduser(raw)))

    env_venv_dir = os.environ.get("VENV_DIR")
    if env_venv_dir:
        return Path(env_venv_dir).expanduser()

    raise FileNotFoundError(
        "No venv base configured. Set apptainer.venv_base, pass --venv-base, or export VENV_DIR."
    )


def _run(cmd: List[str], label: str, quiet: bool) -> None:
    """Run a uv command, streaming output to stderr."""
    result = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL if quiet else sys.stderr,
        stderr=subprocess.DEVNULL if quiet else sys.stderr,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed with exit code {result.returncode}")
