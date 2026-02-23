"""Tests for config module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from euler_files.config import (
    CONFIG_VERSION,
    EulerFilesConfig,
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
