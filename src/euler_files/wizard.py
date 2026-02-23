"""Interactive setup wizard using rich."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from euler_files.config import (
    CONFIG_PATH,
    EulerFilesConfig,
    VarConfig,
    load_config,
    save_config,
)
from euler_files.constants import PRESET_DESCRIPTIONS, PRESETS

console = Console(stderr=True)


def run_wizard() -> None:
    """Run the interactive setup wizard."""
    console.print()
    console.print(
        Panel.fit(
            "[bold blue]euler-files[/bold blue] setup wizard\n\n"
            "Manage env-var caches on HPC clusters by syncing\n"
            "from slow persistent storage to fast scratch.",
            border_style="blue",
            padding=(1, 2),
        )
    )
    console.print()

    # Step 1: Detect scratch
    scratch_base = _detect_scratch()

    # Step 2: Check existing config
    existing = _check_existing_config()
    if existing is not None:
        console.print(f"[yellow]Existing config found at {CONFIG_PATH}[/yellow]")
        if not Confirm.ask("Overwrite existing configuration?", default=False, console=console):
            console.print("[dim]Aborted.[/dim]")
            return

    # Step 3: Select env vars
    selected_vars = _select_vars()

    # Step 4: Configure each var (resolve source paths)
    vars_config = _configure_vars(selected_vars)

    # Step 5: Check for overlapping paths
    _warn_overlaps(vars_config)

    # Step 6: Advanced settings
    parallel_jobs, lock_timeout, skip_fresh = _advanced_settings()

    # Step 7: Build config and show summary
    config = EulerFilesConfig(
        scratch_base=scratch_base,
        vars=vars_config,
        parallel_jobs=parallel_jobs,
        lock_timeout_seconds=lock_timeout,
        skip_if_fresh_seconds=skip_fresh,
    )
    _show_summary(config)

    # Step 8: Save
    console.print()
    if Confirm.ask("Save configuration?", default=True, console=console):
        save_config(config)
        console.print(f"\n[green]Config saved to {CONFIG_PATH}[/green]")
        _show_next_steps()
    else:
        console.print("[dim]Aborted.[/dim]")


def _detect_scratch() -> str:
    """Detect or prompt for scratch base directory."""
    scratch_env = os.environ.get("SCRATCH")

    if scratch_env:
        console.print(f"  [green]$SCRATCH[/green] = {scratch_env}")
        if Confirm.ask(
            f"Use {scratch_env} as scratch base?", default=True, console=console
        ):
            return "$SCRATCH"  # Store the env var reference, not the resolved path

    # No $SCRATCH or user declined — prompt for a path
    console.print("  [yellow]$SCRATCH is not set.[/yellow]")
    while True:
        path = Prompt.ask(
            "Enter scratch directory path",
            console=console,
        )
        expanded = os.path.expandvars(os.path.expanduser(path))
        if Path(expanded).is_dir():
            return path
        console.print(f"  [red]Directory {expanded} does not exist.[/red]")
        if Confirm.ask("Use it anyway?", default=False, console=console):
            return path


def _check_existing_config() -> Optional[EulerFilesConfig]:
    """Check if config already exists."""
    try:
        return load_config()
    except (FileNotFoundError, ValueError):
        return None


def _select_vars() -> List[str]:
    """Let user select which env vars to manage."""
    console.print()
    console.print("[bold]Select caches to manage:[/bold]")
    console.print("[dim]These env vars will be synced from persistent to scratch.[/dim]")
    console.print()

    selected: List[str] = []

    # Show presets
    for name, rel_path in PRESETS.items():
        desc = PRESET_DESCRIPTIONS.get(name, "")
        abs_path = Path.home() / rel_path
        env_val = os.environ.get(name)

        # Determine current source path
        if env_val:
            display_path = env_val
        elif abs_path.exists():
            display_path = str(abs_path)
        else:
            display_path = f"~/{rel_path} [dim](not found)[/dim]"

        # Get size if path exists
        size_str = ""
        check_path = env_val or str(abs_path)
        if Path(check_path).exists():
            size_str = _get_size_display(Path(check_path))

        label = f"  [bold]{name}[/bold]  {display_path}"
        if size_str:
            label += f"  [cyan]({size_str})[/cyan]"
        if desc:
            label += f"\n    [dim]{desc}[/dim]"

        console.print(label)
        if Confirm.ask(f"    Include {name}?", default=(name in ("HF_HOME", "TORCH_HOME")), console=console):
            selected.append(name)
        console.print()

    # Custom vars
    while True:
        console.print()
        if not Confirm.ask("Add a custom environment variable?", default=False, console=console):
            break
        name = Prompt.ask("  Env var name (e.g. MY_MODELS_DIR)", console=console).strip()
        if not name:
            continue
        if not name.replace("_", "").isalnum():
            console.print("  [red]Invalid variable name.[/red]")
            continue
        selected.append(name)

    if not selected:
        console.print("[red]No variables selected. At least one is required.[/red]")
        return _select_vars()

    return selected


def _configure_vars(selected: List[str]) -> Dict[str, VarConfig]:
    """Resolve the source path for each selected var."""
    vars_config: Dict[str, VarConfig] = {}

    for name in selected:
        # Try to auto-detect source
        env_val = os.environ.get(name)
        default_rel = PRESETS.get(name)
        default_abs = str(Path.home() / default_rel) if default_rel else None

        if env_val and Path(env_val).exists():
            source = env_val
        elif default_abs and Path(default_abs).exists():
            source = default_abs
        elif env_val:
            source = env_val  # Set but path doesn't exist yet
        elif default_abs:
            source = default_abs
        else:
            # Custom var — must prompt
            source = Prompt.ask(
                f"  Source path for {name}",
                console=console,
            )
            source = os.path.expandvars(os.path.expanduser(source))

        vars_config[name] = VarConfig(source=source)

    return vars_config


def _warn_overlaps(vars_config: Dict[str, VarConfig]) -> None:
    """Warn if any source path is a subdirectory of another."""
    items = list(vars_config.items())
    for i, (name_a, vc_a) in enumerate(items):
        for name_b, vc_b in items[i + 1 :]:
            path_a = Path(vc_a.source).resolve()
            path_b = Path(vc_b.source).resolve()
            try:
                path_b.relative_to(path_a)
                console.print(
                    f"\n  [yellow]Warning:[/yellow] {name_b} ({vc_b.source}) "
                    f"is inside {name_a} ({vc_a.source}).\n"
                    f"  Syncing both will duplicate data. Consider managing only {name_a}."
                )
            except ValueError:
                pass
            try:
                path_a.relative_to(path_b)
                console.print(
                    f"\n  [yellow]Warning:[/yellow] {name_a} ({vc_a.source}) "
                    f"is inside {name_b} ({vc_b.source}).\n"
                    f"  Syncing both will duplicate data. Consider managing only {name_b}."
                )
            except ValueError:
                pass


def _advanced_settings() -> Tuple[int, int, int]:
    """Prompt for advanced settings (with defaults)."""
    console.print()
    if not Confirm.ask("Configure advanced settings?", default=False, console=console):
        return 4, 300, 3600

    console.print()
    parallel = IntPrompt.ask("  Parallel sync jobs", default=4, console=console)
    lock_timeout = IntPrompt.ask("  Lock timeout (seconds)", default=300, console=console)
    skip_fresh = IntPrompt.ask(
        "  Skip-if-fresh threshold (seconds)", default=3600, console=console
    )
    return parallel, lock_timeout, skip_fresh


def _show_summary(config: EulerFilesConfig) -> None:
    """Display a summary table of the configuration."""
    console.print()
    table = Table(title="Configuration Summary", border_style="blue")
    table.add_column("Variable", style="bold")
    table.add_column("Source")
    table.add_column("Scratch Target")
    table.add_column("Size", justify="right")

    for name, vc in config.vars.items():
        source_path = Path(vc.source)
        target = str(config.scratch_dir_for(name))
        # Show unexpanded scratch path for display
        display_target = target.replace(
            os.path.expandvars(config.scratch_base), config.scratch_base
        )
        size = _get_size_display(source_path) if source_path.exists() else "[dim]n/a[/dim]"
        table.add_row(name, vc.source, display_target, size)

    console.print(table)


def _show_next_steps() -> None:
    """Print usage instructions."""
    console.print()
    console.print(Panel(
        "[bold]Next steps:[/bold]\n\n"
        "1. In your sbatch scripts, add:\n"
        '   [green]eval "$(euler-files sync)"[/green]\n\n'
        "2. For interactive shells, add to ~/.bashrc:\n"
        '   [green]eval "$(euler-files shell-init)"[/green]\n'
        "   Then just type: [green]ef[/green]\n\n"
        "3. Check status anytime:\n"
        "   [green]euler-files status[/green]\n\n"
        "4. After a job downloads new models to scratch:\n"
        "   [green]euler-files push[/green]",
        title="Getting Started",
        border_style="green",
        padding=(1, 2),
    ))


def _get_size_display(path: Path) -> str:
    """Get human-readable size of a directory."""
    try:
        result = subprocess.run(
            ["du", "-sh", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.split()[0]
    except (subprocess.TimeoutExpired, FileNotFoundError, IndexError):
        pass
    return "?"
