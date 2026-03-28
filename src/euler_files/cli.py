"""CLI entry point using click."""

from __future__ import annotations

import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

import click

import euler_files.config as config_module
from euler_files.config import (
    CONFIG_VERSION,
    apptainer_config_from_dict,
    config_from_dict,
    config_to_dict,
    load_config,
    save_config,
)
from euler_files.jsonio import dump_json, load_json_input
from euler_files import __version__


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """euler-files: Manage env-var caches on HPC clusters."""


@main.command()
@click.option("--input-json", type=str, help="Read config from JSON file or '-' for stdin.")
@click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON.")
def init(input_json: Optional[str], json_output: bool) -> None:
    """Interactive setup wizard."""
    from euler_files.wizard import run_wizard

    try:
        if input_json:
            payload = load_json_input(input_json)
            payload = payload.get("config", payload)
            payload.setdefault("version", CONFIG_VERSION)
            config = config_from_dict(payload)
            save_config(config)
        else:
            config = run_wizard()

        result = {
            "command": "init",
            "status": "saved" if config is not None else "aborted",
            "config_path": str(config_module.CONFIG_PATH),
        }
        if config is not None:
            result["config"] = config_to_dict(config)
        _finish(result, json_output=json_output)
    except (FileNotFoundError, ValueError) as exc:
        _fail(exc, json_output=json_output, exit_code=2)


@main.command()
@click.option("--dry-run", is_flag=True, help="Show what would be synced without doing it.")
@click.option("--force", is_flag=True, help="Ignore smart-skip markers and force rsync.")
@click.option("--var", multiple=True, help="Sync only specific var(s). Can be repeated.")
@click.option("--verbose", "-v", is_flag=True, help="Show rsync details on stderr.")
@click.option("--input-json", type=str, help="Read command arguments from JSON file or '-' for stdin.")
@click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON.")
def sync(
    dry_run: bool,
    force: bool,
    var: Tuple[str, ...],
    verbose: bool,
    input_json: Optional[str],
    json_output: bool,
) -> None:
    """Sync caches to scratch. Usage: eval $(euler-files sync)"""
    from euler_files.sync import run_sync

    try:
        payload = load_json_input(input_json)
        only_vars = _resolve_list(var, payload, "vars", "only_vars")
        dry_run = dry_run or bool(payload.get("dry_run", False))
        force = force or bool(payload.get("force", False))
        verbose = verbose or bool(payload.get("verbose", False))
        result = run_sync(
            dry_run=dry_run,
            force=force,
            only_vars=only_vars or None,
            verbose=verbose,
            json_output=json_output,
        )
        _finish(result, json_output=json_output)
    except (FileNotFoundError, ValueError) as exc:
        _fail(exc, json_output=json_output, exit_code=2)


@main.command()
@click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON.")
def status(json_output: bool) -> None:
    """Show sync status, sizes, and staleness of managed caches."""
    from euler_files.status import collect_status, show_status

    try:
        if json_output:
            result = collect_status()
            _finish(result, json_output=True)
        else:
            show_status()
    except (FileNotFoundError, ValueError) as exc:
        _fail(exc, json_output=json_output, exit_code=2)


@main.command()
@click.option("--var", multiple=True, help="Push only specific var(s).")
@click.option("--dry-run", is_flag=True, help="Show what would be pushed.")
@click.option("--input-json", type=str, help="Read command arguments from JSON file or '-' for stdin.")
@click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON.")
def push(var: Tuple[str, ...], dry_run: bool, input_json: Optional[str], json_output: bool) -> None:
    """Reverse sync: copy scratch caches back to persistent storage."""
    from euler_files.push import run_push

    try:
        payload = load_json_input(input_json)
        only_vars = _resolve_list(var, payload, "vars", "only_vars")
        dry_run = dry_run or bool(payload.get("dry_run", False))
        result = run_push(
            only_vars=only_vars or None,
            dry_run=dry_run,
            quiet=json_output,
        )
        _finish(result, json_output=json_output)
    except (FileNotFoundError, ValueError) as exc:
        _fail(exc, json_output=json_output, exit_code=2)


@main.group()
def apptainer() -> None:
    """Manage Apptainer images from Python venvs."""


@apptainer.command(name="init")
@click.option("--input-json", type=str, help="Read config from JSON file or '-' for stdin.")
@click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON.")
def apptainer_init(input_json: Optional[str], json_output: bool) -> None:
    """Interactive setup for apptainer image management."""
    from euler_files.apptainer.wizard import run_apptainer_wizard

    try:
        if input_json:
            payload = load_json_input(input_json)
            payload = payload.get("apptainer", payload)
            config = load_config()
            config.apptainer = apptainer_config_from_dict(payload)
            save_config(config)
            apptainer_config = config.apptainer
        else:
            apptainer_config = run_apptainer_wizard()

        result = {
            "command": "apptainer-init",
            "status": "saved" if apptainer_config is not None else "aborted",
            "config_path": str(config_module.CONFIG_PATH),
        }
        if apptainer_config is not None:
            result["apptainer"] = config_to_dict(load_config()).get("apptainer")
        _finish(result, json_output=json_output)
    except (FileNotFoundError, ValueError) as exc:
        _fail(exc, json_output=json_output, exit_code=2)


@apptainer.command(name="build")
@click.argument("venv_name", required=False)
@click.option("--force", is_flag=True, help="Rebuild even if .sif already exists.")
@click.option("--dry-run", is_flag=True, help="Show what would be done without building.")
@click.option("--input-json", type=str, help="Read command arguments from JSON file or '-' for stdin.")
@click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON.")
def apptainer_build(
    venv_name: Optional[str],
    force: bool,
    dry_run: bool,
    input_json: Optional[str],
    json_output: bool,
) -> None:
    """Build an Apptainer .sif image from a uv venv."""
    from euler_files.apptainer.build import run_build

    try:
        payload = load_json_input(input_json)
        venv_name = _resolve_value(venv_name, payload, "venv_name")
        force = force or bool(payload.get("force", False))
        dry_run = dry_run or bool(payload.get("dry_run", False))
        result = run_build(
            venv_name=venv_name,
            force=force,
            dry_run=dry_run,
            quiet=json_output,
        )
        _finish(result, json_output=json_output)
    except (FileNotFoundError, ValueError) as exc:
        _fail(exc, json_output=json_output, exit_code=2)
    except RuntimeError as exc:
        _fail(exc, json_output=json_output, exit_code=1)


@apptainer.command(name="prune")
@click.argument("image_name", required=False)
@click.option(
    "--mode",
    type=click.Choice(["both", "venv", "sif"]),
    default=None,
    help="What to remove: both, venv only, or sif only.",
)
@click.option("--dry-run", is_flag=True, help="Show what would be deleted.")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@click.option("--input-json", type=str, help="Read command arguments from JSON file or '-' for stdin.")
@click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON.")
def apptainer_prune(
    image_name: Optional[str],
    mode: Optional[str],
    dry_run: bool,
    yes: bool,
    input_json: Optional[str],
    json_output: bool,
) -> None:
    """Remove venvs, .sif images, or both."""
    from euler_files.apptainer.prune import run_prune

    try:
        payload = load_json_input(input_json)
        image_name = _resolve_value(image_name, payload, "image_name", "venv_name")
        mode = _resolve_value(mode, payload, "mode")
        dry_run = dry_run or bool(payload.get("dry_run", False))
        yes = yes or bool(payload.get("yes", False))
        result = run_prune(
            image_name=image_name,
            mode=mode,
            dry_run=dry_run,
            yes=yes,
            quiet=json_output,
        )
        _finish(result, json_output=json_output)
    except (FileNotFoundError, ValueError) as exc:
        _fail(exc, json_output=json_output, exit_code=2)


@apptainer.command(name="fixup")
@click.argument("venv_name", required=False)
@click.option("--dry-run", is_flag=True, help="Show what would be fixed without changing files.")
@click.option("--input-json", type=str, help="Read command arguments from JSON file or '-' for stdin.")
@click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON.")
def apptainer_fixup(
    venv_name: Optional[str],
    dry_run: bool,
    input_json: Optional[str],
    json_output: bool,
) -> None:
    """Fix venv internal paths after moving venv_base.

    Rewrites bin/activate and shebangs to match the venv's actual location.
    Fixes one venv if VENV_NAME is given, otherwise fixes all.
    """
    from euler_files.apptainer.fixup import run_fixup

    try:
        payload = load_json_input(input_json)
        venv_name = _resolve_value(venv_name, payload, "venv_name")
        dry_run = dry_run or bool(payload.get("dry_run", False))
        result = run_fixup(venv_name=venv_name, dry_run=dry_run, quiet=json_output)
        _finish(result, json_output=json_output)
    except (FileNotFoundError, ValueError) as exc:
        _fail(exc, json_output=json_output, exit_code=2)


@apptainer.command(name="sync")
@click.option("--dry-run", is_flag=True, help="Show what would be synced.")
@click.option("--force", is_flag=True, help="Ignore freshness checks.")
@click.option("--image", multiple=True, help="Sync only specific image(s). Can be repeated.")
@click.option("--input-json", type=str, help="Read command arguments from JSON file or '-' for stdin.")
@click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON.")
def apptainer_sync(
    dry_run: bool,
    force: bool,
    image: Tuple[str, ...],
    input_json: Optional[str],
    json_output: bool,
) -> None:
    """Sync .sif images to scratch."""
    from euler_files.apptainer.sync import run_apptainer_sync

    try:
        payload = load_json_input(input_json)
        only_images = _resolve_list(image, payload, "images", "only_images")
        dry_run = dry_run or bool(payload.get("dry_run", False))
        force = force or bool(payload.get("force", False))
        result = run_apptainer_sync(
            dry_run=dry_run,
            force=force,
            only_images=only_images or None,
            quiet=json_output,
        )
        _finish(result, json_output=json_output)
    except (FileNotFoundError, ValueError) as exc:
        _fail(exc, json_output=json_output, exit_code=2)


@main.group()
def venv() -> None:
    """Manage uv environments under the configured venv base."""


@venv.command(name="install")
@click.argument("env_name", required=False)
@click.argument("packages", nargs=-1)
@click.option("--python", "python_version", help="Python version or interpreter for uv venv.")
@click.option("--venv-base", help="Override the configured venv base directory.")
@click.option("--dry-run", is_flag=True, help="Show the uv commands without running them.")
@click.option("--input-json", type=str, help="Read command arguments from JSON file or '-' for stdin.")
@click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON.")
def venv_install(
    env_name: Optional[str],
    packages: Tuple[str, ...],
    python_version: Optional[str],
    venv_base: Optional[str],
    dry_run: bool,
    input_json: Optional[str],
    json_output: bool,
) -> None:
    """Create or reuse a named uv environment and install packages into it."""
    from euler_files.uv_env import run_venv_install

    try:
        payload = load_json_input(input_json)
        env_name = _resolve_value(env_name, payload, "env_name")
        resolved_packages = _resolve_list(packages, payload, "packages", "requirements")
        python_version = _resolve_value(python_version, payload, "python")
        venv_base = _resolve_value(venv_base, payload, "venv_base")
        dry_run = dry_run or bool(payload.get("dry_run", False))
        result = run_venv_install(
            env_name=env_name or "",
            packages=resolved_packages,
            python=python_version,
            venv_base=venv_base,
            dry_run=dry_run,
            quiet=json_output,
        )
        _finish(result, json_output=json_output)
    except (FileNotFoundError, ValueError) as exc:
        _fail(exc, json_output=json_output, exit_code=2)
    except RuntimeError as exc:
        _fail(exc, json_output=json_output, exit_code=1)


@main.command()
@click.argument("what", required=False)
@click.option("--to", "to_path", required=False, help="New location.")
@click.option("--dry-run", is_flag=True, help="Show what would be done.")
@click.option("--no-delete", is_flag=True, help="Keep old directory after migration.")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@click.option("--input-json", type=str, help="Read command arguments from JSON file or '-' for stdin.")
@click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON.")
def migrate(
    what: Optional[str],
    to_path: Optional[str],
    dry_run: bool,
    no_delete: bool,
    yes: bool,
    input_json: Optional[str],
    json_output: bool,
) -> None:
    """Migrate a cache or directory to a new location.

    WHAT is a variable name (e.g. HF_HOME) or config field (e.g. venv_base, sif_store).
    If omitted, runs an interactive wizard.
    """
    from euler_files.migrate import run_migrate

    try:
        payload = load_json_input(input_json)
        what = _resolve_value(what, payload, "what")
        to_path = _resolve_value(to_path, payload, "to", "to_path", "new_path")
        dry_run = dry_run or bool(payload.get("dry_run", False))
        keep_old = no_delete or bool(payload.get("no_delete", payload.get("keep_old", False)))
        yes = yes or bool(payload.get("yes", False))
        result = run_migrate(
            what=what,
            to_path=to_path,
            dry_run=dry_run,
            keep_old=keep_old,
            yes=yes,
            quiet=json_output,
        )
        _finish(result, json_output=json_output)
    except (FileNotFoundError, ValueError) as exc:
        _fail(exc, json_output=json_output, exit_code=2)
    except RuntimeError as exc:
        _fail(exc, json_output=json_output, exit_code=1)


@main.command(name="shell-init")
@click.option(
    "--shell",
    type=click.Choice(["bash", "zsh", "fish"]),
    default=None,
    help="Shell type for the generated function.",
)
@click.option("--input-json", type=str, help="Read command arguments from JSON file or '-' for stdin.")
@click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON.")
def shell_init(shell: Optional[str], input_json: Optional[str], json_output: bool) -> None:
    """Output shell function for easier usage.

    Add to .bashrc: eval "$(euler-files shell-init)"
    """
    from euler_files.shell import generate_shell_init

    try:
        payload = load_json_input(input_json)
        shell = _resolve_value(shell, payload, "shell") or "bash"
        script = generate_shell_init(shell)

        if json_output:
            _finish(
                {
                    "command": "shell-init",
                    "shell": shell,
                    "script": script,
                },
                json_output=True,
            )
            return

        click.echo(script)
    except (FileNotFoundError, ValueError) as exc:
        _fail(exc, json_output=json_output, exit_code=2)


def _resolve_value(current: Optional[str], payload: Dict[str, Any], *keys: str) -> Optional[str]:
    """Prefer explicit CLI values, then fall back to JSON keys."""
    if current:
        return current
    for key in keys:
        value = payload.get(key)
        if value:
            return str(value)
    return current


def _resolve_list(values: Iterable[str], payload: Dict[str, Any], *keys: str) -> List[str]:
    """Prefer explicit CLI lists, then fall back to JSON array fields."""
    resolved = list(values)
    if resolved:
        return resolved
    for key in keys:
        value = payload.get(key)
        if value:
            return [str(item) for item in value]
    return []


def _finish(result: Optional[Dict[str, Any]], json_output: bool) -> None:
    """Emit JSON when requested and exit non-zero for structured command errors."""
    result = result or {}
    errors = result.get("errors") if isinstance(result, dict) else None
    if json_output:
        payload = {"ok": not bool(errors)}
        payload.update(result)
        click.echo(dump_json(payload), nl=False)
    if errors:
        sys.exit(1)


def _fail(exc: Exception, json_output: bool, exit_code: int) -> None:
    """Emit a consistent CLI error response."""
    if json_output:
        click.echo(
            dump_json(
                {
                    "ok": False,
                    "error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                }
            ),
            nl=False,
        )
    else:
        click.echo(f"Error: {exc}", err=True)
    sys.exit(exit_code)
