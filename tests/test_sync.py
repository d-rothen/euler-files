"""Tests for sync module."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from euler_files.config import EulerFilesConfig, VarConfig, save_config


@pytest.fixture
def two_var_config(tmp_path: Path, tmp_scratch: Path, tmp_source: Path) -> Path:
    """Config with two vars."""
    source2 = tmp_path / "home" / ".cache" / "torch"
    source2.mkdir(parents=True)
    (source2 / "model.pt").write_bytes(b"y" * 500)

    config = EulerFilesConfig(
        scratch_base=str(tmp_scratch),
        vars={
            "HF_HOME": VarConfig(source=str(tmp_source)),
            "TORCH_HOME": VarConfig(source=str(source2)),
        },
        parallel_jobs=1,
        lock_timeout_seconds=5,
        skip_if_fresh_seconds=3600,
    )
    config_path = tmp_path / "euler-files.json"
    save_config(config, path=config_path)
    return config_path


def test_sync_outputs_exports(sample_config: Path, capsys: pytest.CaptureFixture) -> None:
    """Sync should print export statements to stdout."""
    from euler_files.sync import run_sync

    with patch("euler_files.rsync.subprocess.run") as mock_rsync:
        mock_rsync.return_value = MagicMock(returncode=0)
        run_sync(config_path=sample_config)

    captured = capsys.readouterr()
    assert "export HF_HOME=" in captured.out
    # Progress goes to stderr
    assert "[SYNC]" in captured.err or "[SKIP]" in captured.err


def test_sync_stdout_valid_shell(
    two_var_config: Path, capsys: pytest.CaptureFixture
) -> None:
    """All stdout lines must be valid export statements."""
    from euler_files.sync import run_sync

    with patch("euler_files.rsync.subprocess.run") as mock_rsync:
        mock_rsync.return_value = MagicMock(returncode=0)
        run_sync(config_path=two_var_config)

    captured = capsys.readouterr()
    lines = [l for l in captured.out.strip().split("\n") if l]
    assert len(lines) == 2
    for line in lines:
        assert line.startswith("export "), f"Non-export line on stdout: {line}"


def test_sync_creates_scratch_dirs(
    sample_config: Path, tmp_scratch: Path, capsys: pytest.CaptureFixture
) -> None:
    """Sync should create the target directories."""
    from euler_files.sync import run_sync

    with patch("euler_files.rsync.subprocess.run") as mock_rsync:
        mock_rsync.return_value = MagicMock(returncode=0)
        run_sync(config_path=sample_config)

    target = tmp_scratch / ".cache" / "euler-files" / "HF_HOME"
    assert target.is_dir()


def test_sync_dry_run(sample_config: Path, capsys: pytest.CaptureFixture) -> None:
    """Dry run should not call rsync."""
    from euler_files.sync import run_sync

    with patch("euler_files.rsync.subprocess.run") as mock_rsync:
        run_sync(config_path=sample_config, dry_run=True)

    mock_rsync.assert_not_called()
    captured = capsys.readouterr()
    assert "export HF_HOME=" in captured.out
    assert "[DRY-RUN]" in captured.err


def test_sync_var_filter(
    two_var_config: Path, capsys: pytest.CaptureFixture
) -> None:
    """--var should filter which vars are synced."""
    from euler_files.sync import run_sync

    with patch("euler_files.rsync.subprocess.run") as mock_rsync:
        mock_rsync.return_value = MagicMock(returncode=0)
        run_sync(config_path=two_var_config, only_vars=["HF_HOME"])

    captured = capsys.readouterr()
    assert "export HF_HOME=" in captured.out
    assert "TORCH_HOME" not in captured.out


def test_sync_missing_source(
    tmp_path: Path, tmp_scratch: Path, capsys: pytest.CaptureFixture
) -> None:
    """Missing source should warn but still emit export."""
    from euler_files.sync import run_sync

    config = EulerFilesConfig(
        scratch_base=str(tmp_scratch),
        vars={"X": VarConfig(source="/nonexistent/path")},
        parallel_jobs=1,
    )
    config_path = tmp_path / "config.json"
    save_config(config, path=config_path)

    run_sync(config_path=config_path)
    captured = capsys.readouterr()
    assert "export X=" in captured.out
    assert "[WARN]" in captured.err


def test_sync_smart_skip(
    sample_config: Path, tmp_scratch: Path, capsys: pytest.CaptureFixture
) -> None:
    """Second sync should skip if marker is fresh."""
    from euler_files.sync import run_sync

    with patch("euler_files.rsync.subprocess.run") as mock_rsync:
        mock_rsync.return_value = MagicMock(returncode=0)
        # First sync
        run_sync(config_path=sample_config)
        capsys.readouterr()  # clear

        # Second sync — should skip
        run_sync(config_path=sample_config)

    captured = capsys.readouterr()
    assert "[SKIP]" in captured.err
    assert "export HF_HOME=" in captured.out


def test_sync_force_ignores_skip(
    sample_config: Path, capsys: pytest.CaptureFixture
) -> None:
    """--force should rsync even when marker is fresh."""
    from euler_files.sync import run_sync

    with patch("euler_files.rsync.subprocess.run") as mock_rsync:
        mock_rsync.return_value = MagicMock(returncode=0)
        # First sync
        run_sync(config_path=sample_config)
        capsys.readouterr()

        # Second sync with force
        run_sync(config_path=sample_config, force=True)

    captured = capsys.readouterr()
    assert "[SYNC]" in captured.err
    assert "[SKIP]" not in captured.err
