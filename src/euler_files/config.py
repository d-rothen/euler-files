"""Configuration dataclasses and JSON serialization."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

CONFIG_PATH = Path.home() / ".euler-files.json"
CONFIG_VERSION = 1


@dataclass
class VarConfig:
    """Configuration for a single managed environment variable."""

    source: str  # Absolute path to persistent location
    enabled: bool = True


@dataclass
class ApptainerImageConfig:
    """Configuration for a single managed apptainer image."""

    venv_name: str
    python_version: str  # e.g. "3.11.5"
    sif_filename: str  # e.g. "my-env.sif"
    built_at: float = 0.0  # Unix timestamp of last build
    enabled: bool = True


@dataclass
class ApptainerConfig:
    """Configuration for apptainer image management."""

    venv_base: str = ""  # e.g. "$VENV_DIR" or "/home/user/venvs"
    sif_store: str = ""  # persistent .sif storage
    scratch_sif_dir: str = ""  # scratch target for synced .sif files
    base_image: str = "python:{version}-slim"  # Docker base image template
    container_venv_path: str = "/opt/venv"  # canonical path inside container
    build_args: List[str] = field(default_factory=lambda: ["--fakeroot"])
    images: Dict[str, ApptainerImageConfig] = field(default_factory=dict)

    def sif_store_path(self) -> Path:
        """Return the expanded persistent sif store path."""
        return Path(os.path.expandvars(os.path.expanduser(self.sif_store)))

    def scratch_sif_path(self) -> Path:
        """Return the expanded scratch sif directory path."""
        return Path(os.path.expandvars(os.path.expanduser(self.scratch_sif_dir)))


@dataclass
class EulerFilesConfig:
    """Top-level configuration."""

    version: int = CONFIG_VERSION
    scratch_base: str = ""
    cache_root: str = ".cache/euler-files"
    vars: Dict[str, VarConfig] = field(default_factory=dict)
    rsync_extra_args: List[str] = field(default_factory=list)
    parallel_jobs: int = 4
    lock_timeout_seconds: int = 300
    skip_if_fresh_seconds: int = 3600
    apptainer: Optional[ApptainerConfig] = None

    def scratch_dir_for(self, var_name: str) -> Path:
        """Return the scratch target directory for a given env var."""
        return Path(self.scratch_base) / self.cache_root / var_name

    def marker_path_for(self, var_name: str) -> Path:
        """Return the marker file path for a given env var."""
        return Path(self.scratch_base) / self.cache_root / f".{var_name}.synced"

    def lock_path_for(self, var_name: str) -> Path:
        """Return the lock file path for a given env var."""
        return Path(self.scratch_base) / self.cache_root / f".{var_name}.lock"


def load_config(path: Optional[Path] = None) -> EulerFilesConfig:
    """Load config from JSON file."""
    p = path or CONFIG_PATH
    if not p.exists():
        raise FileNotFoundError(f"Config not found at {p}. Run 'euler-files init' first.")

    raw = json.loads(p.read_text())

    if raw.get("version", 0) != CONFIG_VERSION:
        raise ValueError(
            f"Config version mismatch. Expected {CONFIG_VERSION}, "
            f"got {raw.get('version')}. Re-run 'euler-files init'."
        )

    vars_dict = {k: VarConfig(**v) for k, v in raw.get("vars", {}).items()}

    # Expand $SCRATCH and other env vars in scratch_base
    scratch_base = os.path.expandvars(raw.get("scratch_base", ""))
    if not scratch_base or scratch_base == raw.get("scratch_base", ""):
        # expandvars didn't change it — might be a literal path, that's fine
        pass

    # Deserialize apptainer config if present
    apptainer = None
    raw_apt = raw.get("apptainer")
    if raw_apt is not None:
        images = {
            k: ApptainerImageConfig(**v)
            for k, v in raw_apt.get("images", {}).items()
        }
        apptainer = ApptainerConfig(
            venv_base=raw_apt.get("venv_base", ""),
            sif_store=raw_apt.get("sif_store", ""),
            scratch_sif_dir=raw_apt.get("scratch_sif_dir", ""),
            base_image=raw_apt.get("base_image", "python:{version}-slim"),
            container_venv_path=raw_apt.get("container_venv_path", "/opt/venv"),
            build_args=raw_apt.get("build_args", ["--fakeroot"]),
            images=images,
        )

    return EulerFilesConfig(
        version=raw["version"],
        scratch_base=scratch_base,
        cache_root=raw.get("cache_root", ".cache/euler-files"),
        vars=vars_dict,
        rsync_extra_args=raw.get("rsync_extra_args", []),
        parallel_jobs=raw.get("parallel_jobs", 4),
        lock_timeout_seconds=raw.get("lock_timeout_seconds", 300),
        skip_if_fresh_seconds=raw.get("skip_if_fresh_seconds", 3600),
        apptainer=apptainer,
    )


def save_config(config: EulerFilesConfig, path: Optional[Path] = None) -> None:
    """Save config to JSON file."""
    p = path or CONFIG_PATH
    raw = {
        "version": config.version,
        "scratch_base": config.scratch_base,
        "cache_root": config.cache_root,
        "vars": {k: {"source": v.source, "enabled": v.enabled} for k, v in config.vars.items()},
        "rsync_extra_args": config.rsync_extra_args,
        "parallel_jobs": config.parallel_jobs,
        "lock_timeout_seconds": config.lock_timeout_seconds,
        "skip_if_fresh_seconds": config.skip_if_fresh_seconds,
    }

    if config.apptainer is not None:
        apt = config.apptainer
        raw["apptainer"] = {
            "venv_base": apt.venv_base,
            "sif_store": apt.sif_store,
            "scratch_sif_dir": apt.scratch_sif_dir,
            "base_image": apt.base_image,
            "container_venv_path": apt.container_venv_path,
            "build_args": apt.build_args,
            "images": {
                k: {
                    "venv_name": v.venv_name,
                    "python_version": v.python_version,
                    "sif_filename": v.sif_filename,
                    "built_at": v.built_at,
                    "enabled": v.enabled,
                }
                for k, v in apt.images.items()
            },
        }

    p.write_text(json.dumps(raw, indent=2) + "\n")
