"""Congruency checks: detect env-var / config path mismatches after migration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from euler_files.config import EulerFilesConfig


@dataclass
class CongruencyWarning:
    """A single mismatch between env var and config."""

    var_name: str
    env_value: Optional[str]  # Current $VAR value (None if unset)
    config_value: str  # What the config says the source should be
    message: str


def check_congruency(config: EulerFilesConfig) -> List[CongruencyWarning]:
    """Check that env vars match config source paths.

    Returns a list of warnings. Empty list means everything is congruent.
    """
    warnings: List[CongruencyWarning] = []

    # Check each managed var
    for var_name, vc in config.vars.items():
        if not vc.enabled:
            continue
        env_val = os.environ.get(var_name)
        if env_val is None:
            # Env var not set — normal before eval $(euler-files sync) runs.
            continue
        # Resolve both to absolute, normalized form
        try:
            env_path = str(Path(env_val).resolve())
            config_path = str(Path(vc.source).resolve())
        except (OSError, ValueError):
            continue
        if env_path != config_path:
            warnings.append(CongruencyWarning(
                var_name=var_name,
                env_value=env_val,
                config_value=vc.source,
                message=(
                    f"${var_name} points to {env_val} but euler-files config "
                    f"expects {vc.source}. Did you forget to update your "
                    f".bashrc after migrating? Add: export {var_name}={vc.source}"
                ),
            ))

    # Check apptainer venv_base if it references an env var
    if config.apptainer is not None:
        apt = config.apptainer
        if apt.venv_base.startswith("$"):
            raw_var = apt.venv_base.lstrip("$").split("/")[0]
            env_val = os.environ.get(raw_var)
            if env_val is not None:
                expanded = os.path.expandvars(apt.venv_base)
                if not Path(expanded).is_dir():
                    warnings.append(CongruencyWarning(
                        var_name=raw_var,
                        env_value=env_val,
                        config_value=apt.venv_base,
                        message=(
                            f"apptainer.venv_base references ${raw_var} which "
                            f"expands to {expanded}, but that directory does not "
                            f"exist. Did the venvs move?"
                        ),
                    ))

    return warnings


def format_warnings(warnings: List[CongruencyWarning]) -> str:
    """Format congruency warnings for stderr output."""
    if not warnings:
        return ""
    lines = ["[WARN] Congruency check found mismatches:"]
    for w in warnings:
        lines.append(f"  - {w.message}")
    lines.append("")
    return "\n".join(lines)
