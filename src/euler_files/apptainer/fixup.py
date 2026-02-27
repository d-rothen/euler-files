"""Fix venv internal paths after a directory move.

When a venv is moved to a new location, its bin/activate script and
shebangs in bin/* scripts still reference the old path. This module
rewrites them to match the venv's actual location on disk.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List, Optional

from euler_files.apptainer.venv import list_venvs


def fixup_venv(venv_path: Path, dry_run: bool = False) -> int:
    """Fix internal paths in a single venv to match its actual location.

    Reads the current VIRTUAL_ENV from bin/activate to determine the old
    path, then rewrites activate and all shebangs in bin/ to use the
    venv's actual path on disk.

    Returns the number of files fixed.
    """
    actual_path = str(venv_path)
    bin_dir = venv_path / "bin"
    activate = bin_dir / "activate"

    if not activate.is_file():
        return 0

    # Detect old path from the activate script
    old_path = _detect_old_path(activate)
    if old_path is None or old_path == actual_path:
        return 0  # Already correct or can't detect

    fixed = 0

    # Fix bin/activate — replace all occurrences of old path
    try:
        text = activate.read_text()
        new_text = text.replace(old_path, actual_path)
        if new_text != text:
            if not dry_run:
                activate.write_text(new_text)
            fixed += 1
    except OSError:
        pass

    # Fix shebangs in all other bin/ scripts
    if bin_dir.is_dir():
        for script in sorted(bin_dir.iterdir()):
            if not script.is_file() or script.name == "activate":
                continue
            try:
                raw = script.read_bytes()
                if not raw.startswith(b"#!"):
                    continue
                text = raw.decode("utf-8", errors="replace")
                first_line, _, rest = text.partition("\n")
                new_first = first_line.replace(old_path, actual_path)
                if new_first != first_line:
                    if not dry_run:
                        script.write_text(new_first + "\n" + rest)
                    fixed += 1
            except OSError:
                pass

    return fixed


def run_fixup(
    venv_name: Optional[str] = None,
    dry_run: bool = False,
    config_path: Optional[Path] = None,
) -> None:
    """Fix venv paths for one or all venvs under venv_base."""
    import os
    from euler_files.config import load_config

    config = load_config(config_path)

    if config.apptainer is None:
        raise FileNotFoundError(
            "Apptainer not configured. Run 'euler-files apptainer init' first."
        )

    apt = config.apptainer
    venv_base = Path(os.path.expandvars(os.path.expanduser(apt.venv_base)))

    if not venv_base.is_dir():
        raise FileNotFoundError(f"Venv base directory does not exist: {venv_base}")

    if venv_name:
        # Fix a single venv
        venv_path = venv_base / venv_name
        if not venv_path.is_dir():
            raise ValueError(f"Venv not found: {venv_path}")
        fixed = fixup_venv(venv_path, dry_run=dry_run)
        if fixed:
            prefix = "[DRY-RUN] " if dry_run else ""
            _err(f"  {prefix}[FIXUP] {venv_name}: {'would rewrite' if dry_run else 'rewrote'} {fixed} file(s)")
        else:
            _err(f"  {venv_name}: paths already correct, nothing to fix")
    else:
        # Fix all venvs
        total = 0
        for child in sorted(venv_base.iterdir()):
            if not child.is_dir() or not (child / "pyvenv.cfg").exists():
                continue
            fixed = fixup_venv(child, dry_run=dry_run)
            if fixed:
                prefix = "[DRY-RUN] " if dry_run else ""
                _err(f"  {prefix}[FIXUP] {child.name}: {'would rewrite' if dry_run else 'rewrote'} {fixed} file(s)")
                total += fixed

        if total == 0:
            _err("  All venvs have correct paths. Nothing to fix.")
        else:
            _err(f"\n  Fixed {total} file(s) total.")


def _detect_old_path(activate_path: Path) -> Optional[str]:
    """Extract the VIRTUAL_ENV value from an activate script."""
    try:
        text = activate_path.read_text()
    except OSError:
        return None

    # Match: VIRTUAL_ENV="/some/path" or VIRTUAL_ENV='/some/path' or VIRTUAL_ENV=/some/path
    match = re.search(r'VIRTUAL_ENV=["\']?([^"\';\n]+)["\']?', text)
    if match:
        return match.group(1).rstrip()
    return None


def _err(msg: str) -> None:
    """Print to stderr."""
    print(msg, file=sys.stderr)
