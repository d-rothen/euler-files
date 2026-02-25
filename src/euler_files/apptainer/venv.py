"""Venv introspection utilities for discovering and parsing uv/stdlib venvs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass
class VenvInfo:
    """Information about a discovered Python venv."""

    name: str
    path: Path
    python_version: str  # Full version like "3.11.5"
    python_major_minor: str  # "3.11"


def parse_pyvenv_cfg(venv_path: Path) -> Dict[str, str]:
    """Parse pyvenv.cfg into a dict of key-value pairs.

    Format: 'key = value' per line.
    """
    cfg_path = venv_path / "pyvenv.cfg"
    if not cfg_path.exists():
        raise ValueError(f"No pyvenv.cfg found at {cfg_path}")

    result: Dict[str, str] = {}
    for line in cfg_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


def detect_python_version(venv_path: Path) -> str:
    """Detect Python version from a venv's pyvenv.cfg.

    Checks 'version_info' (uv), 'version' (stdlib venv), and
    'python' key as fallbacks.
    """
    cfg = parse_pyvenv_cfg(venv_path)

    # uv writes version_info
    version = cfg.get("version_info", "")
    if version:
        return version

    # stdlib venv writes version
    version = cfg.get("version", "")
    if version:
        return version

    raise ValueError(
        f"Could not detect Python version from {venv_path / 'pyvenv.cfg'}. "
        f"Available keys: {list(cfg.keys())}"
    )


def validate_venv(venv_path: Path) -> None:
    """Validate that a path is a genuine Python venv."""
    if not venv_path.is_dir():
        raise ValueError(f"Not a directory: {venv_path}")

    cfg_path = venv_path / "pyvenv.cfg"
    if not cfg_path.exists():
        raise ValueError(f"Not a Python venv (no pyvenv.cfg): {venv_path}")

    bin_dir = venv_path / "bin"
    if not bin_dir.is_dir():
        raise ValueError(f"Not a Python venv (no bin/ directory): {venv_path}")


def list_venvs(venv_base: Path) -> List[VenvInfo]:
    """Discover all venvs under the base directory.

    Looks for immediate subdirectories containing pyvenv.cfg.
    """
    if not venv_base.is_dir():
        return []

    venvs: List[VenvInfo] = []
    for child in sorted(venv_base.iterdir()):
        if not child.is_dir():
            continue
        cfg_path = child / "pyvenv.cfg"
        if not cfg_path.exists():
            continue

        try:
            version = detect_python_version(child)
            major_minor = ".".join(version.split(".")[:2])
            venvs.append(VenvInfo(
                name=child.name,
                path=child,
                python_version=version,
                python_major_minor=major_minor,
            ))
        except ValueError:
            continue

    return venvs
