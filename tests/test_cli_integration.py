"""CLI integration tests using CliRunner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from euler_files.cli import main
from euler_files.config import EulerFilesConfig, VarConfig, save_config


@pytest.fixture
def cli_config(tmp_path: Path, tmp_scratch: Path, tmp_source: Path) -> Path:
    config = EulerFilesConfig(
        scratch_base=str(tmp_scratch),
        vars={"HF_HOME": VarConfig(source=str(tmp_source))},
        parallel_jobs=1,
        lock_timeout_seconds=5,
        skip_if_fresh_seconds=3600,
    )
    config_path = tmp_path / "euler-files.json"
    save_config(config, path=config_path)
    return config_path


def test_version() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_sync_no_config() -> None:
    runner = CliRunner()
    with patch("euler_files.config.CONFIG_PATH", Path("/nonexistent/config.json")):
        result = runner.invoke(main, ["sync"])
    assert result.exit_code == 2
    assert "euler-files init" in result.output


def test_sync_with_config(cli_config: Path) -> None:
    runner = CliRunner()
    with (
        patch("euler_files.config.CONFIG_PATH", cli_config),
        patch("euler_files.rsync.subprocess.run") as mock_rsync,
    ):
        mock_rsync.return_value = MagicMock(returncode=0)
        result = runner.invoke(main, ["sync"])

    assert result.exit_code == 0
    assert "export HF_HOME=" in result.output


def test_sync_dry_run(cli_config: Path) -> None:
    runner = CliRunner()
    with patch("euler_files.config.CONFIG_PATH", cli_config):
        result = runner.invoke(main, ["sync", "--dry-run"])

    assert result.exit_code == 0
    assert "export HF_HOME=" in result.output


def test_shell_init_bash() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["shell-init"])
    assert result.exit_code == 0
    assert "ef()" in result.output
    assert "eval" in result.output


def test_shell_init_fish() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["shell-init", "--shell", "fish"])
    assert result.exit_code == 0
    assert "function ef" in result.output


def test_status_no_config() -> None:
    runner = CliRunner()
    with patch("euler_files.config.CONFIG_PATH", Path("/nonexistent/config.json")):
        result = runner.invoke(main, ["status"])
    assert result.exit_code == 2


def test_push_no_config() -> None:
    runner = CliRunner()
    with patch("euler_files.config.CONFIG_PATH", Path("/nonexistent/config.json")):
        result = runner.invoke(main, ["push"])
    assert result.exit_code == 2
