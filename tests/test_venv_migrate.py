"""Tests for venv migration helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from euler_files.config import ApptainerConfig, EulerFilesConfig, load_config, save_config
from euler_files.venv_migrate import run_single_venv_migration, run_venv_store_migration


def _create_fake_venv(base: Path, name: str, version: str = "3.11.5") -> Path:
    venv = base / name
    (venv / "bin").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text(f"version_info = {version}\n")
    (venv / "bin" / "python").write_text("#!/usr/bin/env python3\n")
    return venv


def test_single_venv_migration_success(tmp_path: Path) -> None:
    source = _create_fake_venv(tmp_path / "old", "env-a")
    target = tmp_path / "new" / "env-a"
    cache_dir = tmp_path / "uv-cache"

    def freeze_side_effect(path: Path, quiet: bool = False):
        if str(path) == str(source):
            return {
                "command": [],
                "lines": ["numpy==1.0", "torch==2.4.0+cu121"],
                "text": "numpy==1.0\ntorch==2.4.0+cu121",
            }
        return {
            "command": [],
            "lines": ["numpy==1.0", "torch==2.4.0+cu121"],
            "text": "numpy==1.0\ntorch==2.4.0+cu121",
        }

    with patch("euler_files.venv_migrate.uv_pip_freeze", side_effect=freeze_side_effect), patch(
        "euler_files.venv_migrate.ensure_uv_binary", return_value="/usr/bin/uv"
    ), patch("euler_files.venv_migrate.run_uv_command") as mock_run:
        result = run_single_venv_migration(
            source=str(source),
            target=str(target),
            uv_cache_dir=str(cache_dir),
        )

    assert result["status"] == "migrated"
    assert result["python_version_detected"] == "3.11.5"
    assert result["python_version_used"] == "3.11.5"
    assert result["extra_index_urls"] == ["https://download.pytorch.org/whl/cu121"]
    assert result["verification"]["status"] == "matched"
    assert result["errors"] == []
    assert mock_run.call_count == 2


def test_single_venv_migration_verification_failure(tmp_path: Path) -> None:
    source = _create_fake_venv(tmp_path / "old", "env-a")
    target = tmp_path / "new" / "env-a"

    def freeze_side_effect(path: Path, quiet: bool = False):
        if str(path) == str(source):
            return {
                "command": [],
                "lines": ["numpy==1.0", "pandas==2.0"],
                "text": "numpy==1.0\npandas==2.0",
            }
        return {
            "command": [],
            "lines": ["numpy==1.0"],
            "text": "numpy==1.0",
        }

    with patch("euler_files.venv_migrate.uv_pip_freeze", side_effect=freeze_side_effect), patch(
        "euler_files.venv_migrate.ensure_uv_binary", return_value="/usr/bin/uv"
    ), patch("euler_files.venv_migrate.run_uv_command"):
        result = run_single_venv_migration(
            source=str(source),
            target=str(target),
        )

    assert result["status"] == "verification-failed"
    assert result["errors"] == ["Verification failed: target requirements differ from source."]
    assert result["verification"]["missing"] == ["pandas==2.0"]


def test_store_migration_updates_config(tmp_path: Path) -> None:
    old_venv_base = tmp_path / "venvs-old"
    _create_fake_venv(old_venv_base, "env-a")
    _create_fake_venv(old_venv_base, "env-b")
    new_venv_base = tmp_path / "venvs-new"
    old_uv_cache = tmp_path / "uv-cache-old"
    old_uv_cache.mkdir()
    (old_uv_cache / "wheels").mkdir()
    new_uv_cache = tmp_path / "uv-cache-new"

    config = EulerFilesConfig(
        scratch_base=str(tmp_path / "scratch"),
        uv_cache_dir=str(old_uv_cache),
        vars={},
        apptainer=ApptainerConfig(
            venv_base=str(old_venv_base),
            sif_store=str(tmp_path / "sif"),
            scratch_sif_dir=str(tmp_path / "scratch-sif"),
        ),
    )
    config_path = tmp_path / "config.json"
    save_config(config, path=config_path)

    def migrate_side_effect(**kwargs):
        return {
            "command": "venv-migrate",
            "status": "migrated",
            "source": kwargs["source"],
            "target": kwargs["target"],
            "errors": [],
            "verification": {"status": "matched"},
        }

    with patch("euler_files.venv_migrate.run_single_venv_migration", side_effect=migrate_side_effect), patch(
        "euler_files.venv_migrate.run_rsync"
    ):
        result = run_venv_store_migration(
            old_venv_base=str(old_venv_base),
            new_venv_base=str(new_venv_base),
            old_uv_cache_dir=str(old_uv_cache),
            new_uv_cache_dir=str(new_uv_cache),
            config_path=config_path,
        )

    loaded = load_config(path=config_path)
    assert result["status"] == "migrated"
    assert result["cache_copy"]["status"] == "copied"
    assert len(result["environments"]) == 2
    assert loaded.uv_cache_dir == str(new_uv_cache)
    assert loaded.apptainer.venv_base == str(new_venv_base)
    assert [m.field_name for m in loaded.migrations] == ["uv_cache_dir", "venv_base"]
