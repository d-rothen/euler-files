"""Tests for the migration feature."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from euler_files.config import (
    ApptainerConfig,
    EulerFilesConfig,
    VarConfig,
    load_config,
    save_config,
)
from euler_files.migrate import run_migrate, _fixup_venvs


def _make_config(
    tmp_path: Path,
    source_name: str = "hf_cache",
    with_apptainer: bool = False,
) -> Path:
    """Create a config with a managed var and optional apptainer section."""
    source = tmp_path / source_name
    source.mkdir(parents=True)
    (source / "models").mkdir()
    (source / "models" / "bert.bin").write_bytes(b"x" * 100)

    apptainer = None
    if with_apptainer:
        venv_base = tmp_path / "venvs"
        venv_base.mkdir()
        sif_store = tmp_path / "sif-store"
        sif_store.mkdir()
        apptainer = ApptainerConfig(
            venv_base=str(venv_base),
            sif_store=str(sif_store),
        )

    config = EulerFilesConfig(
        scratch_base=str(tmp_path / "scratch"),
        vars={"HF_HOME": VarConfig(source=str(source))},
        apptainer=apptainer,
    )
    config_path = tmp_path / "config.json"
    save_config(config, path=config_path)
    return config_path


class TestRunMigrate:
    @patch("euler_files.migrate.run_rsync")
    def test_migrate_var_updates_config(
        self, mock_rsync: MagicMock, tmp_path: Path
    ) -> None:
        config_path = _make_config(tmp_path)
        new_dest = tmp_path / "new_location"

        run_migrate(
            what="HF_HOME",
            to_path=str(new_dest),
            yes=True,
            keep_old=True,
            config_path=config_path,
        )

        loaded = load_config(path=config_path)
        assert loaded.vars["HF_HOME"].source == str(new_dest)

    @patch("euler_files.migrate.run_rsync")
    def test_migrate_var_records_migration(
        self, mock_rsync: MagicMock, tmp_path: Path
    ) -> None:
        config_path = _make_config(tmp_path)
        old_source = str(tmp_path / "hf_cache")
        new_dest = tmp_path / "new_location"

        run_migrate(
            what="HF_HOME",
            to_path=str(new_dest),
            yes=True,
            keep_old=True,
            config_path=config_path,
        )

        loaded = load_config(path=config_path)
        assert len(loaded.migrations) == 1
        m = loaded.migrations[0]
        assert m.old_path == old_source
        assert m.new_path == str(new_dest)
        assert m.field_name == "source"
        assert m.var_name == "HF_HOME"
        assert m.migrated_at > 0

    @patch("euler_files.migrate.run_rsync")
    def test_migrate_calls_rsync_with_delete(
        self, mock_rsync: MagicMock, tmp_path: Path
    ) -> None:
        config_path = _make_config(tmp_path)
        new_dest = tmp_path / "new_location"

        run_migrate(
            what="HF_HOME",
            to_path=str(new_dest),
            yes=True,
            keep_old=True,
            config_path=config_path,
        )

        mock_rsync.assert_called_once()
        call_kwargs = mock_rsync.call_args
        assert call_kwargs.kwargs["delete"] is True
        assert call_kwargs.kwargs["source"] == tmp_path / "hf_cache"
        assert call_kwargs.kwargs["target"] == new_dest

    @patch("euler_files.migrate.run_rsync")
    def test_migrate_dry_run_no_changes(
        self, mock_rsync: MagicMock, tmp_path: Path
    ) -> None:
        config_path = _make_config(tmp_path)
        old_source = str(tmp_path / "hf_cache")
        new_dest = tmp_path / "new_location"

        run_migrate(
            what="HF_HOME",
            to_path=str(new_dest),
            dry_run=True,
            config_path=config_path,
        )

        mock_rsync.assert_not_called()
        loaded = load_config(path=config_path)
        assert loaded.vars["HF_HOME"].source == old_source
        assert loaded.migrations == []

    def test_migrate_nonexistent_source_raises(self, tmp_path: Path) -> None:
        # Create config pointing to a source that doesn't exist
        config = EulerFilesConfig(
            scratch_base=str(tmp_path),
            vars={"HF_HOME": VarConfig(source=str(tmp_path / "nonexistent"))},
        )
        config_path = tmp_path / "config.json"
        save_config(config, path=config_path)

        with pytest.raises(FileNotFoundError, match="does not exist"):
            run_migrate(
                what="HF_HOME",
                to_path=str(tmp_path / "new"),
                yes=True,
                config_path=config_path,
            )

    def test_migrate_same_path_raises(self, tmp_path: Path) -> None:
        config_path = _make_config(tmp_path)
        same_path = str(tmp_path / "hf_cache")

        with pytest.raises(ValueError, match="same"):
            run_migrate(
                what="HF_HOME",
                to_path=same_path,
                yes=True,
                config_path=config_path,
            )

    def test_migrate_unknown_var_raises(self, tmp_path: Path) -> None:
        config_path = _make_config(tmp_path)

        with pytest.raises(ValueError, match="not a managed variable"):
            run_migrate(
                what="NONEXISTENT_VAR",
                to_path=str(tmp_path / "new"),
                config_path=config_path,
            )

    @patch("euler_files.migrate.run_rsync")
    def test_migrate_apptainer_venv_base(
        self, mock_rsync: MagicMock, tmp_path: Path
    ) -> None:
        config_path = _make_config(tmp_path, with_apptainer=True)
        new_dest = tmp_path / "new_venvs"

        run_migrate(
            what="venv_base",
            to_path=str(new_dest),
            yes=True,
            keep_old=True,
            config_path=config_path,
        )

        loaded = load_config(path=config_path)
        assert loaded.apptainer.venv_base == str(new_dest)
        assert len(loaded.migrations) == 1
        assert loaded.migrations[0].field_name == "venv_base"
        assert loaded.migrations[0].var_name == ""

    @patch("euler_files.migrate.run_rsync")
    def test_migrate_apptainer_sif_store(
        self, mock_rsync: MagicMock, tmp_path: Path
    ) -> None:
        config_path = _make_config(tmp_path, with_apptainer=True)
        new_dest = tmp_path / "new_sif"

        run_migrate(
            what="sif_store",
            to_path=str(new_dest),
            yes=True,
            keep_old=True,
            config_path=config_path,
        )

        loaded = load_config(path=config_path)
        assert loaded.apptainer.sif_store == str(new_dest)

    @patch("euler_files.migrate.run_rsync")
    def test_migrate_keeps_old_directory(
        self, mock_rsync: MagicMock, tmp_path: Path
    ) -> None:
        config_path = _make_config(tmp_path)
        old_source = tmp_path / "hf_cache"
        new_dest = tmp_path / "new_location"

        run_migrate(
            what="HF_HOME",
            to_path=str(new_dest),
            yes=True,
            keep_old=True,
            config_path=config_path,
        )

        # Old directory should still exist
        assert old_source.exists()

    @patch("euler_files.migrate.run_rsync")
    def test_migrate_deletes_old_directory(
        self, mock_rsync: MagicMock, tmp_path: Path
    ) -> None:
        config_path = _make_config(tmp_path)
        old_source = tmp_path / "hf_cache"
        new_dest = tmp_path / "new_location"

        run_migrate(
            what="HF_HOME",
            to_path=str(new_dest),
            yes=True,
            keep_old=False,
            config_path=config_path,
        )

        # Old directory should be removed
        assert not old_source.exists()


class TestFixupVenvs:
    def _make_venv(self, base: Path, name: str) -> Path:
        """Create a mock venv with hardcoded paths."""
        venv = base / name
        venv.mkdir(parents=True)
        (venv / "pyvenv.cfg").write_text(
            f"home = /usr/bin\nversion_info = 3.11.5\n"
        )
        bin_dir = venv / "bin"
        bin_dir.mkdir()
        # Activate script with VIRTUAL_ENV
        (bin_dir / "activate").write_text(
            f'VIRTUAL_ENV="{base}/{name}"\nexport VIRTUAL_ENV\n'
        )
        # pip script with shebang
        (bin_dir / "pip").write_text(
            f"#!/{base}/{name}/bin/python\nimport sys\n"
        )
        # python symlink (points to system python — unchanged by fixup)
        (bin_dir / "python").write_text("#!/usr/bin/env python3\n")
        # Binary file — should be skipped
        (bin_dir / "data.bin").write_bytes(b"\x00\x01\x02\x03")
        return venv

    def test_fixup_rewrites_activate(self, tmp_path: Path) -> None:
        old_base = tmp_path / "old_venvs"
        new_base = tmp_path / "new_venvs"
        old_base.mkdir()
        self._make_venv(old_base, "myenv")

        # Simulate rsync by copying
        import shutil
        shutil.copytree(old_base, new_base)

        _fixup_venvs(new_base, str(old_base), str(new_base))

        activate = (new_base / "myenv" / "bin" / "activate").read_text()
        assert str(new_base / "myenv") in activate
        assert str(old_base / "myenv") not in activate

    def test_fixup_rewrites_shebangs(self, tmp_path: Path) -> None:
        old_base = tmp_path / "old_venvs"
        new_base = tmp_path / "new_venvs"
        old_base.mkdir()
        self._make_venv(old_base, "myenv")

        import shutil
        shutil.copytree(old_base, new_base)

        _fixup_venvs(new_base, str(old_base), str(new_base))

        pip = (new_base / "myenv" / "bin" / "pip").read_text()
        assert pip.startswith(f"#!/{new_base}/myenv/bin/python")
        assert str(old_base) not in pip
        # Body preserved
        assert "import sys" in pip

    def test_fixup_skips_non_venvs(self, tmp_path: Path) -> None:
        """Directories without pyvenv.cfg are ignored."""
        new_base = tmp_path / "venvs"
        new_base.mkdir()
        not_venv = new_base / "random_dir"
        not_venv.mkdir()
        (not_venv / "somefile.txt").write_text("hello")

        # Should not crash
        _fixup_venvs(new_base, "/old", str(new_base))

    def test_fixup_skips_binary_files(self, tmp_path: Path) -> None:
        old_base = tmp_path / "old"
        new_base = tmp_path / "new"
        old_base.mkdir()
        self._make_venv(old_base, "env")

        import shutil
        shutil.copytree(old_base, new_base)

        _fixup_venvs(new_base, str(old_base), str(new_base))

        # Binary file should be untouched
        data = (new_base / "env" / "bin" / "data.bin").read_bytes()
        assert data == b"\x00\x01\x02\x03"

    def test_fixup_handles_multiple_venvs(self, tmp_path: Path) -> None:
        old_base = tmp_path / "old"
        new_base = tmp_path / "new"
        old_base.mkdir()
        self._make_venv(old_base, "env1")
        self._make_venv(old_base, "env2")

        import shutil
        shutil.copytree(old_base, new_base)

        _fixup_venvs(new_base, str(old_base), str(new_base))

        for name in ("env1", "env2"):
            activate = (new_base / name / "bin" / "activate").read_text()
            assert str(new_base / name) in activate
            assert str(old_base / name) not in activate
