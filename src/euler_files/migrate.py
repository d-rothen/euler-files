"""Migration wizard: move caches to a new location and update config."""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from euler_files.config import (
    EulerFilesConfig,
    MigrationRecord,
    load_config,
    save_config,
)
from euler_files.rsync import run_rsync

console = Console(stderr=True)


def run_migrate(
    what: Optional[str] = None,
    to_path: Optional[str] = None,
    dry_run: bool = False,
    keep_old: bool = False,
    yes: bool = False,
    config_path: Optional[Path] = None,
) -> None:
    """Migrate a cache or directory to a new location."""
    config = load_config(config_path)

    if what is None:
        what, to_path = _interactive_select(config)
        if what is None:
            return

    # Resolve what we're migrating
    target_type, old_path, config_field = _resolve_target(config, what)

    if to_path is None:
        to_path = Prompt.ask(f"New location for {what}", console=console)

    new_path = os.path.expandvars(os.path.expanduser(to_path))

    # Validation
    if str(Path(new_path).resolve()) == str(old_path.resolve()):
        raise ValueError(f"Source and destination are the same: {new_path}")

    if not old_path.exists():
        raise FileNotFoundError(f"Source path does not exist: {old_path}")

    # Show plan
    _show_plan(what, str(old_path), new_path, keep_old)

    if dry_run:
        _err("[DRY-RUN] No changes made.")
        return

    # Confirm
    if not yes:
        if not Confirm.ask(
            "Proceed with migration?", default=False, console=console
        ):
            _err("Aborted.")
            return

    # Step 1: rsync data
    _err(f"  [RSYNC] {old_path} -> {new_path}")
    dest = Path(new_path)
    dest.mkdir(parents=True, exist_ok=True)
    run_rsync(source=old_path, target=dest, delete=True)
    _err("  [RSYNC] Done.")

    # Step 1b: Fix venv internal paths if migrating venv_base
    old_path_str = str(old_path)
    if config_field == "venv_base":
        _fixup_venvs(dest, old_path_str, new_path)

    # Step 2: Update config
    _update_config_field(config, target_type, what, new_path)

    # Step 3: Record migration
    config.migrations.append(MigrationRecord(
        old_path=old_path_str,
        new_path=new_path,
        migrated_at=time.time(),
        field_name=config_field,
        var_name=what if target_type == "var" else "",
    ))

    save_config(config, path=config_path)
    _err("  [CONFIG] Updated euler-files config.")

    # Step 4: Optionally remove old directory
    if not keep_old:
        if yes or Confirm.ask(
            f"Delete old directory {old_path_str}?",
            default=True,
            console=console,
        ):
            shutil.rmtree(old_path_str)
            _err(f"  [DELETE] Removed {old_path_str}")
        else:
            _err(f"  [KEEP] Old directory kept at {old_path_str}")

    # Step 5: Print export instructions
    _print_export_instructions(what, target_type, new_path)

    _err("")
    _err("Done.")


def _resolve_target(
    config: EulerFilesConfig, what: str
) -> Tuple[str, Path, str]:
    """Determine what to migrate.

    Returns (target_type, old_path, config_field_name).
    """
    # Check if 'what' is a managed var name
    if what in config.vars:
        old = Path(config.vars[what].source)
        return ("var", old, "source")

    # Check apptainer fields
    if config.apptainer is not None:
        if what == "venv_base":
            raw = config.apptainer.venv_base
            old = Path(os.path.expandvars(os.path.expanduser(raw)))
            return ("apptainer", old, "venv_base")
        if what == "sif_store":
            old = config.apptainer.sif_store_path()
            return ("apptainer", old, "sif_store")

    managed_vars = list(config.vars.keys())
    apptainer_fields = ["venv_base", "sif_store"] if config.apptainer else []
    raise ValueError(
        f"'{what}' is not a managed variable or apptainer field. "
        f"Managed vars: {managed_vars}. "
        f"Apptainer fields: {apptainer_fields}."
    )


def _update_config_field(
    config: EulerFilesConfig, target_type: str, what: str, new_path: str
) -> None:
    """Update the config field to point to the new path."""
    if target_type == "var":
        config.vars[what].source = new_path
    elif target_type == "apptainer":
        if what == "venv_base":
            config.apptainer.venv_base = new_path
        elif what == "sif_store":
            config.apptainer.sif_store = new_path


def _interactive_select(
    config: EulerFilesConfig,
) -> Tuple[Optional[str], Optional[str]]:
    """Interactive migration target selection.

    Returns (what, to_path) or (None, None) if aborted.
    """
    console.print()
    console.print(
        Panel.fit(
            "[bold blue]euler-files[/bold blue] migration wizard\n\n"
            "Move a cache directory to a new location\n"
            "and update euler-files config accordingly.",
            border_style="blue",
            padding=(1, 2),
        )
    )
    console.print()

    choices: List[Tuple[str, str, str]] = []  # (name, current_path, type)

    table = Table(title="Migratable Items", border_style="blue")
    table.add_column("#", style="dim", justify="right")
    table.add_column("Name", style="bold")
    table.add_column("Current Path")
    table.add_column("Type")

    idx = 1
    for name, vc in config.vars.items():
        if vc.enabled:
            table.add_row(str(idx), name, vc.source, "env var")
            choices.append((name, vc.source, "var"))
            idx += 1

    if config.apptainer is not None:
        apt = config.apptainer
        for field_name, raw_val in [
            ("venv_base", apt.venv_base),
            ("sif_store", apt.sif_store),
        ]:
            expanded = os.path.expandvars(os.path.expanduser(raw_val))
            display = f"{raw_val} ({expanded})" if raw_val != expanded else raw_val
            table.add_row(str(idx), field_name, display, "apptainer")
            choices.append((field_name, expanded, "apptainer"))
            idx += 1

    if not choices:
        _err("No migratable items found in config.")
        return None, None

    console.print(table)
    console.print()

    choice_str = Prompt.ask(
        "Select item to migrate (number or name)", console=console
    )

    # Resolve choice
    selected_name = None
    try:
        choice_idx = int(choice_str) - 1
        if 0 <= choice_idx < len(choices):
            selected_name = choices[choice_idx][0]
    except ValueError:
        pass

    if selected_name is None:
        for name, _, _ in choices:
            if choice_str == name:
                selected_name = name
                break

    if selected_name is None:
        _err(f"Unknown selection: {choice_str}")
        return None, None

    console.print()
    to_path = Prompt.ask(f"New location for {selected_name}", console=console)

    return selected_name, to_path


def _show_plan(what: str, old_path: str, new_path: str, keep_old: bool) -> None:
    """Display migration plan."""
    console.print()
    table = Table(title=f"Migration Plan: {what}", border_style="yellow")
    table.add_column("Step", style="bold")
    table.add_column("Details")

    table.add_row("Source", old_path)
    table.add_row("Destination", new_path)
    table.add_row("Copy method", "rsync -a --delete")
    table.add_row(
        "Old directory",
        "keep (--no-delete)" if keep_old else "delete after copy",
    )
    table.add_row("Config update", f"Update '{what}' source path")

    console.print(table)
    console.print()


def _print_export_instructions(
    what: str, target_type: str, new_path: str
) -> None:
    """Print shell export lines the user needs to add to .bashrc."""
    _err("")
    if target_type == "var":
        console.print(Panel(
            f"[bold]Update your shell profile (.bashrc / .zshrc):[/bold]\n\n"
            f"  [green]export {what}={new_path}[/green]\n\n"
            f"Then reload: [green]source ~/.bashrc[/green]",
            title="Action Required",
            border_style="yellow",
            padding=(1, 2),
        ))
    elif target_type == "apptainer":
        if what == "venv_base":
            console.print(Panel(
                f"[bold]Update your shell profile (.bashrc / .zshrc):[/bold]\n\n"
                f"  [green]export VENV_DIR={new_path}[/green]\n\n"
                f"Then reload: [green]source ~/.bashrc[/green]",
                title="Action Required",
                border_style="yellow",
                padding=(1, 2),
            ))
        else:
            console.print(Panel(
                f"[bold]Migration complete.[/bold]\n\n"
                f"Config updated for {what}. No shell changes needed.",
                title="Done",
                border_style="green",
                padding=(1, 2),
            ))


def _fixup_venvs(new_base: Path, old_base_str: str, new_base_str: str) -> None:
    """Fix internal paths in all venvs after migrating venv_base.

    Venvs contain hardcoded paths in:
    - bin/activate: VIRTUAL_ENV="/old/path/venvs/myenv"
    - bin/* shebangs: #!/old/path/venvs/myenv/bin/python
    These must be rewritten to the new location or python/pip won't work.
    """
    if not new_base.is_dir():
        return

    for child in sorted(new_base.iterdir()):
        if not child.is_dir():
            continue
        # Only process directories that look like venvs
        if not (child / "pyvenv.cfg").exists():
            continue

        venv_name = child.name
        old_venv = f"{old_base_str.rstrip('/')}/{venv_name}"
        new_venv = f"{new_base_str.rstrip('/')}/{venv_name}"

        fixed = 0

        # Fix bin/activate VIRTUAL_ENV= line
        activate = child / "bin" / "activate"
        if activate.is_file():
            try:
                text = activate.read_text()
                new_text = text.replace(old_venv, new_venv)
                if new_text != text:
                    activate.write_text(new_text)
                    fixed += 1
            except OSError:
                pass

        # Fix shebangs in all bin/ scripts
        bin_dir = child / "bin"
        if bin_dir.is_dir():
            for script in bin_dir.iterdir():
                if not script.is_file() or script.name == "activate":
                    continue
                try:
                    raw = script.read_bytes()
                    # Only process text files with shebangs
                    if not raw.startswith(b"#!"):
                        continue
                    text = raw.decode("utf-8", errors="replace")
                    first_line, _, rest = text.partition("\n")
                    new_first = first_line.replace(old_venv, new_venv)
                    if new_first != first_line:
                        script.write_text(new_first + "\n" + rest)
                        fixed += 1
                except OSError:
                    pass

        if fixed:
            _err(f"  [FIXUP] {venv_name}: rewrote {fixed} path(s)")


def _err(msg: str) -> None:
    """Print to stderr."""
    print(msg, file=sys.stderr)
