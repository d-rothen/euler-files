"""Status command: show sync status, sizes, and staleness."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.table import Table

from euler_files.config import load_config

console = Console()


def collect_status(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Collect sync status for all managed variables."""
    config = load_config(config_path)

    from euler_files.congruency import check_congruency, format_warnings
    cong_warnings = check_congruency(config)
    warnings: List[str] = []
    if cong_warnings:
        warnings.append(format_warnings(cong_warnings))

    variables = []
    for name, vc in config.vars.items():
        if not vc.enabled:
            continue

        source_path = Path(vc.source)
        scratch_path = config.scratch_dir_for(name)
        marker_path = config.marker_path_for(name)

        # Sizes
        source_size = _get_size(source_path)
        scratch_size = _get_size(scratch_path)

        # Last synced from marker
        last_synced = "never"
        stale = True
        if marker_path.exists():
            try:
                marker_data = json.loads(marker_path.read_text())
                synced_at = marker_data.get("synced_at", 0)
                age = time.time() - synced_at
                last_synced = _format_age(age)
                stale = age > config.skip_if_fresh_seconds
            except (json.JSONDecodeError, OSError):
                last_synced = "corrupt"

        # Status
        if stale:
            status = "stale"
        else:
            status = "fresh"

        if not source_path.exists():
            status = "source-missing"
        elif not scratch_path.exists():
            status = "not-synced"

        variables.append({
            "name": name,
            "source": str(source_path),
            "scratch": str(scratch_path),
            "source_size": source_size,
            "scratch_size": scratch_size,
            "last_synced": last_synced,
            "status": status,
        })

    # Summary
    scratch_base = Path(config.scratch_base) / config.cache_root
    total = _get_size(scratch_base)

    return {
        "command": "status",
        "warnings": warnings,
        "variables": variables,
        "total_scratch_usage": total,
    }


def show_status(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Display sync status for all managed variables."""
    data = collect_status(config_path=config_path)
    if data["warnings"]:
        for warning in data["warnings"]:
            console.print(f"[yellow]{warning}[/yellow]")

    table = Table(title="euler-files status", border_style="blue")
    table.add_column("Variable", style="bold")
    table.add_column("Source Size", justify="right")
    table.add_column("Scratch Size", justify="right")
    table.add_column("Last Synced", justify="right")
    table.add_column("Status")

    for item in data["variables"]:
        status = item["status"]
        if status == "fresh":
            status_str = "[green]fresh[/green]"
        elif status in ("stale", "source-missing"):
            status_str = f"[yellow]{status.replace('-', ' ')}[/yellow]"
        else:
            status_str = f"[red]{status.replace('-', ' ')}[/red]"

        table.add_row(
            item["name"],
            item["source_size"],
            item["scratch_size"],
            item["last_synced"],
            status_str,
        )

    console.print(table)
    console.print(f"\nTotal scratch usage: [bold]{data['total_scratch_usage']}[/bold]")
    return data


def _get_size(path: Path) -> str:
    """Get human-readable size of a directory."""
    if not path.exists():
        return "-"
    try:
        result = subprocess.run(
            ["du", "-sh", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return result.stdout.split()[0]
    except (subprocess.TimeoutExpired, FileNotFoundError, IndexError):
        pass
    return "?"


def _format_age(seconds: float) -> str:
    """Format an age in seconds as a human-readable string."""
    if seconds < 60:
        return f"{int(seconds)}s ago"
    elif seconds < 3600:
        return f"{int(seconds / 60)}m ago"
    elif seconds < 86400:
        return f"{int(seconds / 3600)}h ago"
    else:
        return f"{int(seconds / 86400)}d ago"
