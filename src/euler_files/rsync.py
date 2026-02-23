"""rsync subprocess wrapper."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import List, Optional


class RsyncError(RuntimeError):
    """Raised when rsync exits with a non-zero code."""

    pass


def run_rsync(
    source: Path,
    target: Path,
    extra_args: Optional[List[str]] = None,
    verbose: bool = False,
    delete: bool = False,
) -> None:
    """Run rsync to sync source to target.

    Trailing slash on source is critical: copies contents of source
    into target, not source itself as a subdirectory.

    rsync output is suppressed; only warnings/errors are printed to stderr.
    """
    cmd = [
        "rsync",
        "-a",  # archive mode (preserves permissions, timestamps, etc.)
        "--info=progress2",  # overall progress (not per-file)
        "--info=name0",  # suppress individual file names
        "--human-readable",
    ]

    if delete:
        cmd.append("--delete")

    if extra_args:
        cmd.extend(extra_args)

    if verbose:
        cmd.append("--verbose")

    # Trailing slash = copy contents, not the directory itself
    cmd.append(str(source).rstrip("/") + "/")
    cmd.append(str(target).rstrip("/") + "/")

    result = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if result.returncode != 0:
        # 23 = partial transfer, 24 = source files vanished — usually harmless
        if result.returncode in (23, 24):
            print(
                f"[WARN] rsync exited with code {result.returncode} "
                "(partial transfer / vanished files). Continuing.",
                file=sys.stderr,
            )
        else:
            raise RsyncError(f"rsync failed with exit code {result.returncode}")
