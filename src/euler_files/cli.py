"""CLI entry point using click."""

from __future__ import annotations

import sys

import click


@click.group()
@click.version_option(package_name="euler-files")
def main() -> None:
    """euler-files: Manage env-var caches on HPC clusters."""


@main.command()
def init() -> None:
    """Interactive setup wizard."""
    from euler_files.wizard import run_wizard

    run_wizard()


@main.command()
@click.option("--dry-run", is_flag=True, help="Show what would be synced without doing it.")
@click.option("--force", is_flag=True, help="Ignore smart-skip markers and force rsync.")
@click.option("--var", multiple=True, help="Sync only specific var(s). Can be repeated.")
@click.option("--verbose", "-v", is_flag=True, help="Show rsync details on stderr.")
def sync(dry_run: bool, force: bool, var: tuple, verbose: bool) -> None:
    """Sync caches to scratch. Usage: eval $(euler-files sync)"""
    from euler_files.sync import run_sync

    try:
        run_sync(dry_run=dry_run, force=force, only_vars=list(var) or None, verbose=verbose)
    except FileNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)


@main.command()
def status() -> None:
    """Show sync status, sizes, and staleness of managed caches."""
    from euler_files.status import show_status

    try:
        show_status()
    except FileNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)


@main.command()
@click.option("--var", multiple=True, help="Push only specific var(s).")
@click.option("--dry-run", is_flag=True, help="Show what would be pushed.")
def push(var: tuple, dry_run: bool) -> None:
    """Reverse sync: copy scratch caches back to persistent storage."""
    from euler_files.push import run_push

    try:
        run_push(only_vars=list(var) or None, dry_run=dry_run)
    except FileNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)


@main.group()
def apptainer() -> None:
    """Manage Apptainer images from Python venvs."""


@apptainer.command(name="init")
def apptainer_init() -> None:
    """Interactive setup for apptainer image management."""
    from euler_files.apptainer.wizard import run_apptainer_wizard

    run_apptainer_wizard()


@apptainer.command(name="build")
@click.argument("venv_name", required=False)
@click.option("--force", is_flag=True, help="Rebuild even if .sif already exists.")
@click.option("--dry-run", is_flag=True, help="Show what would be done without building.")
def apptainer_build(venv_name: str, force: bool, dry_run: bool) -> None:
    """Build an Apptainer .sif image from a uv venv."""
    from euler_files.apptainer.build import run_build

    try:
        run_build(venv_name=venv_name, force=force, dry_run=dry_run)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)


@apptainer.command(name="sync")
@click.option("--dry-run", is_flag=True, help="Show what would be synced.")
@click.option("--force", is_flag=True, help="Ignore freshness checks.")
@click.option("--image", multiple=True, help="Sync only specific image(s). Can be repeated.")
def apptainer_sync(dry_run: bool, force: bool, image: tuple) -> None:
    """Sync .sif images to scratch."""
    from euler_files.apptainer.sync import run_apptainer_sync

    try:
        run_apptainer_sync(dry_run=dry_run, force=force, only_images=list(image) or None)
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)


@main.command(name="shell-init")
@click.option(
    "--shell",
    type=click.Choice(["bash", "zsh", "fish"]),
    default="bash",
    help="Shell type for the generated function.",
)
def shell_init(shell: str) -> None:
    """Output shell function for easier usage.

    Add to .bashrc: eval "$(euler-files shell-init)"
    """
    from euler_files.shell import generate_shell_init

    click.echo(generate_shell_init(shell))
