"""Tests for apptainer build workflow."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from euler_files.config import (
    ApptainerConfig,
    ApptainerImageConfig,
    EulerFilesConfig,
    VarConfig,
    load_config,
    save_config,
)
from euler_files.apptainer.build import run_build


def _make_config(tmp_path: Path, venv_base: Path) -> Path:
    """Create a config with apptainer section and return config path."""
    sif_store = tmp_path / "sif-store"
    sif_store.mkdir()

    config = EulerFilesConfig(
        scratch_base=str(tmp_path / "scratch"),
        vars={},
        apptainer=ApptainerConfig(
            venv_base=str(venv_base),
            sif_store=str(sif_store),
            scratch_sif_dir=str(tmp_path / "scratch" / "sif"),
            build_args=["--fakeroot"],
        ),
    )
    config_path = tmp_path / "config.json"
    save_config(config, path=config_path)
    return config_path


def _make_venv(base: Path, name: str) -> Path:
    """Create a mock venv."""
    venv = base / name
    venv.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("version_info = 3.11.5\nhome = /usr/bin\n")
    (venv / "bin").mkdir()
    (venv / "bin" / "python").write_text("#!/usr/bin/env python3\n")
    return venv


class TestRunBuild:
    def test_no_apptainer_config(self, tmp_path: Path) -> None:
        config = EulerFilesConfig(scratch_base=str(tmp_path), vars={})
        config_path = tmp_path / "config.json"
        save_config(config, path=config_path)

        with pytest.raises(FileNotFoundError, match="apptainer init"):
            run_build(venv_name="test", config_path=config_path)

    def test_invalid_venv(self, tmp_path: Path) -> None:
        venv_base = tmp_path / "venvs"
        venv_base.mkdir()
        config_path = _make_config(tmp_path, venv_base)

        with pytest.raises(ValueError, match="Not a directory"):
            run_build(venv_name="nonexistent", config_path=config_path)

    @patch("euler_files.apptainer.build.subprocess.run")
    def test_dry_run(self, mock_run: MagicMock, tmp_path: Path) -> None:
        venv_base = tmp_path / "venvs"
        _make_venv(venv_base, "my-env")
        config_path = _make_config(tmp_path, venv_base)

        run_build(venv_name="my-env", dry_run=True, config_path=config_path)

        mock_run.assert_not_called()

    @patch("euler_files.apptainer.build.subprocess.run")
    def test_successful_build(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(returncode=0)

        venv_base = tmp_path / "venvs"
        _make_venv(venv_base, "my-env")
        config_path = _make_config(tmp_path, venv_base)

        run_build(venv_name="my-env", config_path=config_path)

        # Verify apptainer build was called
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "apptainer"
        assert cmd[1] == "build"
        assert "--fakeroot" in cmd
        assert any(c.endswith("my-env.sif") for c in cmd)
        assert any(c.endswith("my-env.def") for c in cmd)

        # Verify config was updated with image
        loaded = load_config(path=config_path)
        assert "my-env" in loaded.apptainer.images
        img = loaded.apptainer.images["my-env"]
        assert img.python_version == "3.11.5"
        assert img.sif_filename == "my-env.sif"
        assert img.built_at > 0

    @patch("euler_files.apptainer.build.subprocess.run")
    def test_skip_existing_sif(self, mock_run: MagicMock, tmp_path: Path) -> None:
        venv_base = tmp_path / "venvs"
        _make_venv(venv_base, "my-env")
        config_path = _make_config(tmp_path, venv_base)

        # Create existing .sif
        sif_store = tmp_path / "sif-store"
        (sif_store / "my-env.sif").write_bytes(b"existing")

        run_build(venv_name="my-env", config_path=config_path)

        mock_run.assert_not_called()

    @patch("euler_files.apptainer.build.subprocess.run")
    def test_force_rebuilds_existing(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(returncode=0)

        venv_base = tmp_path / "venvs"
        _make_venv(venv_base, "my-env")
        config_path = _make_config(tmp_path, venv_base)

        # Create existing .sif
        sif_store = tmp_path / "sif-store"
        (sif_store / "my-env.sif").write_bytes(b"existing")

        run_build(venv_name="my-env", force=True, config_path=config_path)

        mock_run.assert_called_once()

    @patch("euler_files.apptainer.build.subprocess.run")
    def test_build_failure(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(returncode=1)

        venv_base = tmp_path / "venvs"
        _make_venv(venv_base, "my-env")
        config_path = _make_config(tmp_path, venv_base)

        with pytest.raises(RuntimeError, match="exit code 1"):
            run_build(venv_name="my-env", config_path=config_path)

    @patch("euler_files.apptainer.build.subprocess.run")
    def test_def_file_written(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(returncode=0)

        venv_base = tmp_path / "venvs"
        _make_venv(venv_base, "my-env")
        config_path = _make_config(tmp_path, venv_base)

        run_build(venv_name="my-env", config_path=config_path)

        def_path = tmp_path / "sif-store" / "my-env.def"
        assert def_path.exists()
        content = def_path.read_text()
        assert "Bootstrap: docker" in content
        assert "python:3.11-slim" in content
