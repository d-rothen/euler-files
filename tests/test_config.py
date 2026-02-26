"""Tests for config module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from euler_files.config import (
    CONFIG_VERSION,
    EulerFilesConfig,
    MigrationRecord,
    VarConfig,
    load_config,
    save_config,
)


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    config = EulerFilesConfig(
        scratch_base="/scratch/user",
        vars={
            "HF_HOME": VarConfig(source="/home/user/.cache/hf"),
            "TORCH_HOME": VarConfig(source="/home/user/.cache/torch", enabled=False),
        },
        parallel_jobs=2,
        lock_timeout_seconds=60,
        skip_if_fresh_seconds=1800,
    )
    config_path = tmp_path / "config.json"
    save_config(config, path=config_path)

    loaded = load_config(path=config_path)
    assert loaded.scratch_base == "/scratch/user"
    assert len(loaded.vars) == 2
    assert loaded.vars["HF_HOME"].source == "/home/user/.cache/hf"
    assert loaded.vars["HF_HOME"].enabled is True
    assert loaded.vars["TORCH_HOME"].enabled is False
    assert loaded.parallel_jobs == 2
    assert loaded.lock_timeout_seconds == 60
    assert loaded.skip_if_fresh_seconds == 1800


def test_load_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Run 'euler-files init' first"):
        load_config(path=tmp_path / "nonexistent.json")


def test_load_version_mismatch(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"version": 999, "vars": {}}))
    with pytest.raises(ValueError, match="Config version mismatch"):
        load_config(path=config_path)


def test_scratch_dir_for() -> None:
    config = EulerFilesConfig(
        scratch_base="/scratch/user",
        cache_root=".cache/euler-files",
        vars={"HF_HOME": VarConfig(source="/home/user/.cache/hf")},
    )
    assert config.scratch_dir_for("HF_HOME") == Path("/scratch/user/.cache/euler-files/HF_HOME")


def test_marker_path_for() -> None:
    config = EulerFilesConfig(
        scratch_base="/scratch/user",
        vars={"X": VarConfig(source="/src")},
    )
    assert config.marker_path_for("X") == Path("/scratch/user/.cache/euler-files/.X.synced")


def test_lock_path_for() -> None:
    config = EulerFilesConfig(
        scratch_base="/scratch/user",
        vars={"X": VarConfig(source="/src")},
    )
    assert config.lock_path_for("X") == Path("/scratch/user/.cache/euler-files/.X.lock")


def test_save_creates_valid_json(tmp_path: Path) -> None:
    config = EulerFilesConfig(
        scratch_base="$SCRATCH",
        vars={"A": VarConfig(source="/a")},
    )
    config_path = tmp_path / "config.json"
    save_config(config, path=config_path)

    raw = json.loads(config_path.read_text())
    assert raw["version"] == CONFIG_VERSION
    assert raw["scratch_base"] == "$SCRATCH"
    assert raw["vars"]["A"]["source"] == "/a"
    assert raw["vars"]["A"]["enabled"] is True


def test_defaults() -> None:
    config = EulerFilesConfig()
    assert config.version == CONFIG_VERSION
    assert config.cache_root == ".cache/euler-files"
    assert config.parallel_jobs == 4
    assert config.lock_timeout_seconds == 300
    assert config.skip_if_fresh_seconds == 3600
    assert config.rsync_extra_args == []
    assert config.migrations == []


def test_migration_record_roundtrip(tmp_path: Path) -> None:
    config = EulerFilesConfig(
        scratch_base="/scratch",
        vars={"HF_HOME": VarConfig(source="/new/hf")},
        migrations=[
            MigrationRecord(
                old_path="/old/hf",
                new_path="/new/hf",
                migrated_at=1700000000.0,
                field_name="source",
                var_name="HF_HOME",
            ),
            MigrationRecord(
                old_path="/old/venvs",
                new_path="/data/venvs",
                migrated_at=1700001000.0,
                field_name="venv_base",
                var_name="",
            ),
        ],
    )
    config_path = tmp_path / "config.json"
    save_config(config, path=config_path)

    loaded = load_config(path=config_path)
    assert len(loaded.migrations) == 2
    assert loaded.migrations[0].old_path == "/old/hf"
    assert loaded.migrations[0].new_path == "/new/hf"
    assert loaded.migrations[0].migrated_at == 1700000000.0
    assert loaded.migrations[0].field_name == "source"
    assert loaded.migrations[0].var_name == "HF_HOME"
    assert loaded.migrations[1].field_name == "venv_base"
    assert loaded.migrations[1].var_name == ""


def test_old_config_without_migrations_loads(tmp_path: Path) -> None:
    """Config JSON without 'migrations' key loads with empty list."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "version": CONFIG_VERSION,
        "scratch_base": "/scratch",
        "vars": {},
    }))
    loaded = load_config(path=config_path)
    assert loaded.migrations == []


def test_empty_migrations_not_serialized(tmp_path: Path) -> None:
    """Empty migrations list is omitted from JSON to keep config clean."""
    config = EulerFilesConfig(scratch_base="/scratch", vars={})
    config_path = tmp_path / "config.json"
    save_config(config, path=config_path)

    raw = json.loads(config_path.read_text())
    assert "migrations" not in raw
