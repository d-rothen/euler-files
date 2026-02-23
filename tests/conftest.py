"""Shared test fixtures."""

from __future__ import annotations

import pytest
from pathlib import Path

from euler_files.config import EulerFilesConfig, VarConfig, save_config


@pytest.fixture
def tmp_scratch(tmp_path: Path) -> Path:
    """Temp directory simulating scratch space."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return scratch


@pytest.fixture
def tmp_source(tmp_path: Path) -> Path:
    """Temp directory simulating a persistent cache (e.g. HF_HOME)."""
    source = tmp_path / "home" / ".cache" / "huggingface"
    source.mkdir(parents=True)
    (source / "model.bin").write_bytes(b"x" * 1000)
    (source / "config.json").write_text('{"key": "value"}')
    (source / "subdir").mkdir()
    (source / "subdir" / "nested.txt").write_text("nested content")
    return source


@pytest.fixture
def sample_config(tmp_path: Path, tmp_scratch: Path, tmp_source: Path) -> Path:
    """Create a sample config file and return its path."""
    config = EulerFilesConfig(
        scratch_base=str(tmp_scratch),
        vars={
            "HF_HOME": VarConfig(source=str(tmp_source)),
        },
        parallel_jobs=1,
        lock_timeout_seconds=5,
        skip_if_fresh_seconds=3600,
    )
    config_path = tmp_path / "euler-files.json"
    save_config(config, path=config_path)
    return config_path
