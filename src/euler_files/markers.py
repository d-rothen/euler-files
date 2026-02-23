"""Smart-skip marker file management.

After a successful sync, we write a JSON marker with the sync timestamp
and the source directory's mtime. On subsequent syncs, we skip rsync if
the marker is fresh and the source hasn't changed.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from euler_files.config import EulerFilesConfig


def should_skip(config: EulerFilesConfig, var_name: str, source: Path) -> bool:
    """Check if we can skip rsync for this var.

    Returns True if:
    1. A marker file exists
    2. The marker is within skip_if_fresh_seconds
    3. The source dir's top-level mtime hasn't increased since the marker
    """
    marker_path = config.marker_path_for(var_name)

    if not marker_path.exists():
        return False

    try:
        marker_data = json.loads(marker_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False

    marker_time = marker_data.get("synced_at", 0)
    marker_source_mtime = marker_data.get("source_mtime", 0)

    # Is the marker too old?
    age = time.time() - marker_time
    if age > config.skip_if_fresh_seconds:
        return False

    # Has the source changed?
    try:
        current_source_mtime = _get_dir_mtime(source)
    except OSError:
        return False

    if current_source_mtime > marker_source_mtime:
        return False

    return True


def write_marker(config: EulerFilesConfig, var_name: str, source: Path) -> None:
    """Write a marker file after successful sync."""
    marker_path = config.marker_path_for(var_name)
    marker_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        source_mtime = _get_dir_mtime(source)
    except OSError:
        source_mtime = 0

    data = {
        "synced_at": time.time(),
        "source_mtime": source_mtime,
        "var_name": var_name,
        "source": str(source),
    }
    marker_path.write_text(json.dumps(data))


def _get_dir_mtime(path: Path) -> float:
    """Get a composite mtime for a directory (depth 0 + depth 1).

    Checks the directory itself and all immediate children. Returns the
    maximum mtime found. This catches new files/dirs added and top-level
    modifications. Deep changes are caught by rsync itself.
    """
    max_mtime = path.stat().st_mtime
    try:
        for child in path.iterdir():
            child_mtime = child.stat().st_mtime
            if child_mtime > max_mtime:
                max_mtime = child_mtime
    except PermissionError:
        pass
    return max_mtime
