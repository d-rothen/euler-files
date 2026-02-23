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

    return EulerFilesConfig(
        version=raw["version"],
        scratch_base=scratch_base,
        cache_root=raw.get("cache_root", ".cache/euler-files"),
        vars=vars_dict,
        rsync_extra_args=raw.get("rsync_extra_args", []),
        parallel_jobs=raw.get("parallel_jobs", 4),
        lock_timeout_seconds=raw.get("lock_timeout_seconds", 300),
        skip_if_fresh_seconds=raw.get("skip_if_fresh_seconds", 3600),
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
    p.write_text(json.dumps(raw, indent=2) + "\n")
