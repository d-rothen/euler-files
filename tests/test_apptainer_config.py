"""Tests for apptainer config serialization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from euler_files.config import (
    ApptainerConfig,
    ApptainerImageConfig,
    EulerFilesConfig,
    VarConfig,
    load_config,
    save_config,
)


def test_roundtrip_with_apptainer(tmp_path: Path) -> None:
    config = EulerFilesConfig(
        scratch_base="/scratch/user",
        vars={"HF_HOME": VarConfig(source="/home/user/.cache/hf")},
        apptainer=ApptainerConfig(
            venv_base="/home/user/venvs",
            sif_store="/home/user/.cache/euler-files/sif",
            scratch_sif_dir="/scratch/user/.cache/euler-files/sif",
            base_image="python:{version}-slim",
            container_venv_path="/opt/venv",
            build_args=["--fakeroot"],
            images={
                "ml-env": ApptainerImageConfig(
                    venv_name="ml-env",
                    python_version="3.11.5",
                    sif_filename="ml-env.sif",
                    built_at=1700000000.0,
                ),
            },
        ),
    )
    config_path = tmp_path / "config.json"
    save_config(config, path=config_path)

    loaded = load_config(path=config_path)
    assert loaded.apptainer is not None

    apt = loaded.apptainer
    assert apt.venv_base == "/home/user/venvs"
    assert apt.sif_store == "/home/user/.cache/euler-files/sif"
    assert apt.scratch_sif_dir == "/scratch/user/.cache/euler-files/sif"
    assert apt.base_image == "python:{version}-slim"
    assert apt.container_venv_path == "/opt/venv"
    assert apt.build_args == ["--fakeroot"]

    assert "ml-env" in apt.images
    img = apt.images["ml-env"]
    assert img.venv_name == "ml-env"
    assert img.python_version == "3.11.5"
    assert img.sif_filename == "ml-env.sif"
    assert img.built_at == 1700000000.0
    assert img.enabled is True


def test_backward_compat_no_apptainer_key(tmp_path: Path) -> None:
    """Old configs without 'apptainer' key should load with apptainer=None."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "version": 1,
        "scratch_base": "/scratch",
        "cache_root": ".cache/euler-files",
        "vars": {"HF_HOME": {"source": "/home/.cache/hf", "enabled": True}},
        "rsync_extra_args": [],
        "parallel_jobs": 4,
        "lock_timeout_seconds": 300,
        "skip_if_fresh_seconds": 3600,
    }))

    loaded = load_config(path=config_path)
    assert loaded.apptainer is None
    assert loaded.vars["HF_HOME"].source == "/home/.cache/hf"


def test_save_without_apptainer(tmp_path: Path) -> None:
    """Config with apptainer=None should not include 'apptainer' key in JSON."""
    config = EulerFilesConfig(
        scratch_base="/scratch",
        vars={"X": VarConfig(source="/x")},
    )
    config_path = tmp_path / "config.json"
    save_config(config, path=config_path)

    raw = json.loads(config_path.read_text())
    assert "apptainer" not in raw


def test_apptainer_config_defaults() -> None:
    apt = ApptainerConfig()
    assert apt.venv_base == ""
    assert apt.base_image == "python:{version}-slim"
    assert apt.container_venv_path == "/opt/venv"
    assert apt.build_args == ["--fakeroot"]
    assert apt.images == {}


def test_apptainer_image_config_defaults() -> None:
    img = ApptainerImageConfig(
        venv_name="test",
        python_version="3.12.0",
        sif_filename="test.sif",
    )
    assert img.built_at == 0.0
    assert img.enabled is True


def test_empty_images_roundtrip(tmp_path: Path) -> None:
    config = EulerFilesConfig(
        scratch_base="/scratch",
        vars={},
        apptainer=ApptainerConfig(
            venv_base="/venvs",
            sif_store="/sif",
            scratch_sif_dir="/scratch/sif",
        ),
    )
    config_path = tmp_path / "config.json"
    save_config(config, path=config_path)

    loaded = load_config(path=config_path)
    assert loaded.apptainer is not None
    assert loaded.apptainer.images == {}
