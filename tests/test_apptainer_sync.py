"""Tests for apptainer sync workflow."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from euler_files.config import (
    ApptainerConfig,
    ApptainerImageConfig,
    EulerFilesConfig,
    save_config,
)
from euler_files.apptainer.sync import run_apptainer_sync


def _make_config(
    tmp_path: Path,
    images: dict[str, ApptainerImageConfig] | None = None,
) -> Path:
    sif_store = tmp_path / "sif-store"
    sif_store.mkdir(exist_ok=True)
    scratch_sif = tmp_path / "scratch" / "sif"

    config = EulerFilesConfig(
        scratch_base=str(tmp_path / "scratch"),
        vars={},
        lock_timeout_seconds=5,
        apptainer=ApptainerConfig(
            venv_base=str(tmp_path / "venvs"),
            sif_store=str(sif_store),
            scratch_sif_dir=str(scratch_sif),
            images=images or {},
        ),
    )
    config_path = tmp_path / "config.json"
    save_config(config, path=config_path)
    return config_path


class TestRunApptainerSync:
    def test_no_apptainer_config(self, tmp_path: Path) -> None:
        config = EulerFilesConfig(scratch_base=str(tmp_path), vars={})
        config_path = tmp_path / "config.json"
        save_config(config, path=config_path)

        with pytest.raises(FileNotFoundError, match="apptainer init"):
            run_apptainer_sync(config_path=config_path)

    def test_no_images(self, tmp_path: Path) -> None:
        config_path = _make_config(tmp_path)
        # Should not raise, just prints "no images"
        run_apptainer_sync(config_path=config_path)

    @patch("euler_files.apptainer.sync.rsync_file")
    def test_sync_image(self, mock_rsync: MagicMock, tmp_path: Path) -> None:
        config_path = _make_config(tmp_path, images={
            "my-env": ApptainerImageConfig(
                venv_name="my-env",
                python_version="3.11.5",
                sif_filename="my-env.sif",
                built_at=time.time(),
            ),
        })

        sif_store = tmp_path / "sif-store"
        (sif_store / "my-env.sif").write_bytes(b"sif-content")

        run_apptainer_sync(config_path=config_path)

        mock_rsync.assert_called_once()
        call_kwargs = mock_rsync.call_args
        assert call_kwargs.kwargs["source"] == sif_store / "my-env.sif"

    @patch("euler_files.apptainer.sync.rsync_file")
    def test_skip_up_to_date(self, mock_rsync: MagicMock, tmp_path: Path) -> None:
        config_path = _make_config(tmp_path, images={
            "my-env": ApptainerImageConfig(
                venv_name="my-env",
                python_version="3.11.5",
                sif_filename="my-env.sif",
                built_at=time.time(),
            ),
        })

        sif_store = tmp_path / "sif-store"
        (sif_store / "my-env.sif").write_bytes(b"sif-content")

        # Create target with same or newer mtime
        scratch_sif = tmp_path / "scratch" / "sif"
        scratch_sif.mkdir(parents=True)
        target = scratch_sif / "my-env.sif"
        target.write_bytes(b"sif-content")

        # Make target mtime >= source mtime
        source_mtime = (sif_store / "my-env.sif").stat().st_mtime
        os.utime(str(target), (source_mtime + 1, source_mtime + 1))

        run_apptainer_sync(config_path=config_path)

        mock_rsync.assert_not_called()

    @patch("euler_files.apptainer.sync.rsync_file")
    def test_force_overrides_skip(self, mock_rsync: MagicMock, tmp_path: Path) -> None:
        config_path = _make_config(tmp_path, images={
            "my-env": ApptainerImageConfig(
                venv_name="my-env",
                python_version="3.11.5",
                sif_filename="my-env.sif",
                built_at=time.time(),
            ),
        })

        sif_store = tmp_path / "sif-store"
        (sif_store / "my-env.sif").write_bytes(b"sif-content")

        # Create up-to-date target
        scratch_sif = tmp_path / "scratch" / "sif"
        scratch_sif.mkdir(parents=True)
        target = scratch_sif / "my-env.sif"
        target.write_bytes(b"sif-content")
        source_mtime = (sif_store / "my-env.sif").stat().st_mtime
        os.utime(str(target), (source_mtime + 1, source_mtime + 1))

        run_apptainer_sync(force=True, config_path=config_path)

        mock_rsync.assert_called_once()

    @patch("euler_files.apptainer.sync.rsync_file")
    def test_dry_run(self, mock_rsync: MagicMock, tmp_path: Path) -> None:
        config_path = _make_config(tmp_path, images={
            "my-env": ApptainerImageConfig(
                venv_name="my-env",
                python_version="3.11.5",
                sif_filename="my-env.sif",
                built_at=time.time(),
            ),
        })

        sif_store = tmp_path / "sif-store"
        (sif_store / "my-env.sif").write_bytes(b"content")

        run_apptainer_sync(dry_run=True, config_path=config_path)

        mock_rsync.assert_not_called()

    @patch("euler_files.apptainer.sync.rsync_file")
    def test_filter_by_image(self, mock_rsync: MagicMock, tmp_path: Path) -> None:
        config_path = _make_config(tmp_path, images={
            "env-a": ApptainerImageConfig(
                venv_name="env-a",
                python_version="3.11.5",
                sif_filename="env-a.sif",
                built_at=time.time(),
            ),
            "env-b": ApptainerImageConfig(
                venv_name="env-b",
                python_version="3.12.0",
                sif_filename="env-b.sif",
                built_at=time.time(),
            ),
        })

        sif_store = tmp_path / "sif-store"
        (sif_store / "env-a.sif").write_bytes(b"a")
        (sif_store / "env-b.sif").write_bytes(b"b")

        run_apptainer_sync(only_images=["env-a"], config_path=config_path)

        assert mock_rsync.call_count == 1
        call_kwargs = mock_rsync.call_args
        assert "env-a.sif" in str(call_kwargs.kwargs["source"])

    @patch("euler_files.apptainer.sync.rsync_file")
    def test_skip_missing_source(self, mock_rsync: MagicMock, tmp_path: Path) -> None:
        config_path = _make_config(tmp_path, images={
            "missing": ApptainerImageConfig(
                venv_name="missing",
                python_version="3.11.5",
                sif_filename="missing.sif",
                built_at=time.time(),
            ),
        })

        run_apptainer_sync(config_path=config_path)

        mock_rsync.assert_not_called()

    @patch("euler_files.apptainer.sync.rsync_file")
    def test_disabled_image_skipped(self, mock_rsync: MagicMock, tmp_path: Path) -> None:
        config_path = _make_config(tmp_path, images={
            "disabled": ApptainerImageConfig(
                venv_name="disabled",
                python_version="3.11.5",
                sif_filename="disabled.sif",
                built_at=time.time(),
                enabled=False,
            ),
        })

        sif_store = tmp_path / "sif-store"
        (sif_store / "disabled.sif").write_bytes(b"content")

        run_apptainer_sync(config_path=config_path)

        mock_rsync.assert_not_called()
