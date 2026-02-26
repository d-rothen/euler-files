"""Tests for apptainer prune workflow."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from euler_files.config import (
    ApptainerConfig,
    ApptainerImageConfig,
    EulerFilesConfig,
    load_config,
    save_config,
)
from euler_files.apptainer.prune import run_prune, PruneMode


def _make_env(
    tmp_path: Path,
    name: str = "my-env",
    create_venv: bool = True,
    create_sif: bool = True,
    create_scratch_sif: bool = False,
    add_to_config: bool = True,
) -> Path:
    """Set up a full test environment and return the config path."""
    venv_base = tmp_path / "venvs"
    venv_base.mkdir(exist_ok=True)
    sif_store = tmp_path / "sif-store"
    sif_store.mkdir(exist_ok=True)
    scratch_sif = tmp_path / "scratch" / "sif"
    scratch_sif.mkdir(parents=True, exist_ok=True)

    if create_venv:
        venv = venv_base / name
        venv.mkdir(parents=True, exist_ok=True)
        (venv / "pyvenv.cfg").write_text("version_info = 3.11.5\n")
        (venv / "bin").mkdir(exist_ok=True)
        (venv / "bin" / "python").write_text("#!/usr/bin/env python3\n")
        (venv / "lib").mkdir(exist_ok=True)
        (venv / "lib" / "site-packages").mkdir(exist_ok=True)
        (venv / "lib" / "site-packages" / "torch.py").write_text("# big package\n")

    if create_sif:
        (sif_store / f"{name}.sif").write_bytes(b"fake-sif-content")
        (sif_store / f"{name}.def").write_text("Bootstrap: docker\n")

    if create_scratch_sif:
        (scratch_sif / f"{name}.sif").write_bytes(b"fake-scratch-sif")

    images = {}
    if add_to_config:
        images[name] = ApptainerImageConfig(
            venv_name=name,
            python_version="3.11.5",
            sif_filename=f"{name}.sif",
            built_at=time.time(),
        )

    config = EulerFilesConfig(
        scratch_base=str(tmp_path / "scratch"),
        vars={},
        apptainer=ApptainerConfig(
            venv_base=str(venv_base),
            sif_store=str(sif_store),
            scratch_sif_dir=str(scratch_sif),
            images=images,
        ),
    )
    config_path = tmp_path / "config.json"
    save_config(config, path=config_path)
    return config_path


class TestRunPrune:
    def test_no_apptainer_config(self, tmp_path: Path) -> None:
        config = EulerFilesConfig(scratch_base=str(tmp_path), vars={})
        config_path = tmp_path / "config.json"
        save_config(config, path=config_path)

        with pytest.raises(FileNotFoundError, match="apptainer init"):
            run_prune(image_name="test", mode="both", config_path=config_path)

    def test_prune_both(self, tmp_path: Path) -> None:
        config_path = _make_env(tmp_path, create_sif=True, create_venv=True)

        run_prune(
            image_name="my-env", mode=PruneMode.BOTH,
            yes=True, config_path=config_path,
        )

        # Venv should be gone
        assert not (tmp_path / "venvs" / "my-env").exists()
        # SIF should be gone
        assert not (tmp_path / "sif-store" / "my-env.sif").exists()
        # Def should be gone
        assert not (tmp_path / "sif-store" / "my-env.def").exists()
        # Config should be updated
        loaded = load_config(path=config_path)
        assert "my-env" not in loaded.apptainer.images

    def test_prune_venv_only(self, tmp_path: Path) -> None:
        config_path = _make_env(tmp_path)

        run_prune(
            image_name="my-env", mode=PruneMode.VENV_ONLY,
            yes=True, config_path=config_path,
        )

        # Venv should be gone
        assert not (tmp_path / "venvs" / "my-env").exists()
        # SIF should still exist
        assert (tmp_path / "sif-store" / "my-env.sif").exists()
        # Config should still have the image
        loaded = load_config(path=config_path)
        assert "my-env" in loaded.apptainer.images

    def test_prune_sif_only(self, tmp_path: Path) -> None:
        config_path = _make_env(tmp_path)

        run_prune(
            image_name="my-env", mode=PruneMode.SIF_ONLY,
            yes=True, config_path=config_path,
        )

        # Venv should still exist
        assert (tmp_path / "venvs" / "my-env").exists()
        # SIF should be gone
        assert not (tmp_path / "sif-store" / "my-env.sif").exists()
        assert not (tmp_path / "sif-store" / "my-env.def").exists()
        # Config should be updated
        loaded = load_config(path=config_path)
        assert "my-env" not in loaded.apptainer.images

    def test_prune_also_removes_scratch_sif(self, tmp_path: Path) -> None:
        config_path = _make_env(tmp_path, create_scratch_sif=True)

        run_prune(
            image_name="my-env", mode=PruneMode.SIF_ONLY,
            yes=True, config_path=config_path,
        )

        assert not (tmp_path / "scratch" / "sif" / "my-env.sif").exists()

    def test_dry_run_deletes_nothing(self, tmp_path: Path) -> None:
        config_path = _make_env(tmp_path)

        run_prune(
            image_name="my-env", mode=PruneMode.BOTH,
            dry_run=True, config_path=config_path,
        )

        # Everything should still exist
        assert (tmp_path / "venvs" / "my-env").exists()
        assert (tmp_path / "sif-store" / "my-env.sif").exists()
        loaded = load_config(path=config_path)
        assert "my-env" in loaded.apptainer.images

    def test_prune_missing_venv(self, tmp_path: Path) -> None:
        """Pruning venv that doesn't exist on disk should not crash."""
        config_path = _make_env(tmp_path, create_venv=False)

        run_prune(
            image_name="my-env", mode=PruneMode.BOTH,
            yes=True, config_path=config_path,
        )

        # SIF should still be removed
        assert not (tmp_path / "sif-store" / "my-env.sif").exists()

    def test_prune_missing_sif(self, tmp_path: Path) -> None:
        """Pruning sif that doesn't exist on disk should not crash."""
        config_path = _make_env(tmp_path, create_sif=False)

        run_prune(
            image_name="my-env", mode=PruneMode.BOTH,
            yes=True, config_path=config_path,
        )

        # Venv should still be removed
        assert not (tmp_path / "venvs" / "my-env").exists()

    def test_prune_nothing_to_delete(self, tmp_path: Path) -> None:
        """Nothing exists on disk — should handle gracefully."""
        config_path = _make_env(
            tmp_path, create_venv=False, create_sif=False, add_to_config=False,
        )

        # Should not raise
        run_prune(
            image_name="my-env", mode=PruneMode.BOTH,
            yes=True, config_path=config_path,
        )

    def test_prune_removes_config_entry_on_sif_mode(self, tmp_path: Path) -> None:
        config_path = _make_env(tmp_path)

        run_prune(
            image_name="my-env", mode=PruneMode.SIF_ONLY,
            yes=True, config_path=config_path,
        )

        loaded = load_config(path=config_path)
        assert "my-env" not in loaded.apptainer.images

    def test_prune_keeps_config_entry_on_venv_mode(self, tmp_path: Path) -> None:
        config_path = _make_env(tmp_path)

        run_prune(
            image_name="my-env", mode=PruneMode.VENV_ONLY,
            yes=True, config_path=config_path,
        )

        loaded = load_config(path=config_path)
        assert "my-env" in loaded.apptainer.images

    def test_prune_venv_with_many_files(self, tmp_path: Path) -> None:
        """Ensure shutil.rmtree handles deep venv directories."""
        config_path = _make_env(tmp_path)

        # Add some nested files to simulate a real venv
        venv = tmp_path / "venvs" / "my-env"
        deep = venv / "lib" / "python3.11" / "site-packages" / "torch" / "cuda"
        deep.mkdir(parents=True)
        for i in range(10):
            (deep / f"lib{i}.so").write_bytes(b"x" * 100)

        run_prune(
            image_name="my-env", mode=PruneMode.VENV_ONLY,
            yes=True, config_path=config_path,
        )

        assert not venv.exists()
