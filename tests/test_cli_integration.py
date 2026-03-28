"""CLI integration tests using CliRunner."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from euler_files.cli import main
from euler_files.config import EulerFilesConfig, VarConfig, load_config, save_config


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
    with patch("euler_files.config.CONFIG_PATH", cli_config), patch(
        "euler_files.rsync.subprocess.run"
    ) as mock_rsync:
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


def test_sync_json_output(cli_config: Path) -> None:
    runner = CliRunner()
    with patch("euler_files.config.CONFIG_PATH", cli_config), patch(
        "euler_files.rsync.subprocess.run"
    ) as mock_rsync:
        mock_rsync.return_value = MagicMock(returncode=0)
        result = runner.invoke(main, ["sync", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "sync"
    assert "HF_HOME" in payload["exports"]


def test_init_from_input_json(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = tmp_path / "euler-files.json"
    payload = {
        "scratch_base": str(tmp_path / "scratch"),
        "vars": {
            "HF_HOME": {
                "source": str(tmp_path / "source"),
            }
        },
    }

    with patch("euler_files.config.CONFIG_PATH", config_path):
        result = runner.invoke(
            main,
            ["init", "--input-json", "-", "--json"],
            input=json.dumps(payload),
        )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["ok"] is True
    assert output["status"] == "saved"
    saved = load_config(path=config_path)
    assert saved.scratch_base == str(tmp_path / "scratch")
    assert saved.vars["HF_HOME"].source == str(tmp_path / "source")


def test_venv_install_json_output(tmp_path: Path) -> None:
    runner = CliRunner()
    venv_dir = tmp_path / "venvs"

    with patch.dict("os.environ", {"VENV_DIR": str(venv_dir)}, clear=False), patch(
        "euler_files.uv_env.shutil.which", return_value="/usr/bin/uv"
    ), patch(
        "euler_files.uv_env.subprocess.run", return_value=MagicMock(returncode=0)
    ):
        result = runner.invoke(
            main,
            [
                "venv",
                "install",
                "ml-env",
                "torch==2.4.0+cu121",
                "transformers",
                "--json",
            ],
        )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["env_name"] == "ml-env"
    assert payload["extra_index_urls"] == ["https://download.pytorch.org/whl/cu121"]


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
