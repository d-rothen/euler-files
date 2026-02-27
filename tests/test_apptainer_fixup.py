"""Tests for apptainer fixup (venv path repair)."""

from __future__ import annotations

from pathlib import Path

import pytest

from euler_files.config import ApptainerConfig, EulerFilesConfig, save_config
from euler_files.apptainer.fixup import fixup_venv, run_fixup, _detect_old_path


def _make_venv(base: Path, name: str, virtual_env_path: str = None) -> Path:
    """Create a venv with paths pointing to virtual_env_path (defaults to actual)."""
    venv = base / name
    venv.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\nversion_info = 3.11.5\n")
    bin_dir = venv / "bin"
    bin_dir.mkdir()

    path_in_scripts = virtual_env_path or str(venv)
    (bin_dir / "activate").write_text(
        f'VIRTUAL_ENV="{path_in_scripts}"\n'
        f'export VIRTUAL_ENV\n'
        f'PATH="$VIRTUAL_ENV/bin:$PATH"\n'
    )
    (bin_dir / "pip").write_text(
        f"#!{path_in_scripts}/bin/python\nimport sys\nsys.exit(0)\n"
    )
    (bin_dir / "uv").write_text(
        f"#!{path_in_scripts}/bin/python3\nimport uv\n"
    )
    (bin_dir / "python").write_text("#!/usr/bin/env python3\n")
    (bin_dir / "data.bin").write_bytes(b"\x00\x01\x02")
    return venv


class TestDetectOldPath:
    def test_double_quoted(self, tmp_path: Path) -> None:
        f = tmp_path / "activate"
        f.write_text('VIRTUAL_ENV="/old/path/venvs/myenv"\n')
        assert _detect_old_path(f) == "/old/path/venvs/myenv"

    def test_single_quoted(self, tmp_path: Path) -> None:
        f = tmp_path / "activate"
        f.write_text("VIRTUAL_ENV='/old/path/venvs/myenv'\n")
        assert _detect_old_path(f) == "/old/path/venvs/myenv"

    def test_unquoted(self, tmp_path: Path) -> None:
        f = tmp_path / "activate"
        f.write_text("VIRTUAL_ENV=/old/path/venvs/myenv\n")
        assert _detect_old_path(f) == "/old/path/venvs/myenv"

    def test_no_match(self, tmp_path: Path) -> None:
        f = tmp_path / "activate"
        f.write_text("# no VIRTUAL_ENV here\n")
        assert _detect_old_path(f) is None

    def test_missing_file(self, tmp_path: Path) -> None:
        assert _detect_old_path(tmp_path / "nonexistent") is None


class TestFixupVenv:
    def test_fixes_broken_venv(self, tmp_path: Path) -> None:
        venv = _make_venv(tmp_path, "myenv", virtual_env_path="/old/venvs/myenv")

        fixed = fixup_venv(venv)

        assert fixed > 0
        activate = (venv / "bin" / "activate").read_text()
        assert str(venv) in activate
        assert "/old/venvs/myenv" not in activate

    def test_fixes_shebangs(self, tmp_path: Path) -> None:
        venv = _make_venv(tmp_path, "myenv", virtual_env_path="/old/venvs/myenv")

        fixup_venv(venv)

        pip = (venv / "bin" / "pip").read_text()
        assert pip.startswith(f"#!{venv}/bin/python\n")
        assert "/old/" not in pip

        uv = (venv / "bin" / "uv").read_text()
        assert uv.startswith(f"#!{venv}/bin/python3\n")

    def test_skips_correct_venv(self, tmp_path: Path) -> None:
        venv = _make_venv(tmp_path, "myenv")  # paths already correct
        fixed = fixup_venv(venv)
        assert fixed == 0

    def test_skips_binary_files(self, tmp_path: Path) -> None:
        venv = _make_venv(tmp_path, "myenv", virtual_env_path="/old/venvs/myenv")
        fixup_venv(venv)
        assert (venv / "bin" / "data.bin").read_bytes() == b"\x00\x01\x02"

    def test_dry_run(self, tmp_path: Path) -> None:
        venv = _make_venv(tmp_path, "myenv", virtual_env_path="/old/venvs/myenv")

        fixed = fixup_venv(venv, dry_run=True)

        assert fixed > 0
        # Files should NOT be modified
        activate = (venv / "bin" / "activate").read_text()
        assert "/old/venvs/myenv" in activate

    def test_preserves_script_body(self, tmp_path: Path) -> None:
        venv = _make_venv(tmp_path, "myenv", virtual_env_path="/old/venvs/myenv")
        fixup_venv(venv)
        pip = (venv / "bin" / "pip").read_text()
        assert "import sys" in pip
        assert "sys.exit(0)" in pip

    def test_no_activate(self, tmp_path: Path) -> None:
        """Venv without activate script is skipped gracefully."""
        venv = tmp_path / "noactivate"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text("version_info = 3.11\n")
        (venv / "bin").mkdir()
        assert fixup_venv(venv) == 0


class TestRunFixup:
    def _make_config(self, tmp_path: Path, venv_base: Path) -> Path:
        config = EulerFilesConfig(
            scratch_base=str(tmp_path / "scratch"),
            vars={},
            apptainer=ApptainerConfig(venv_base=str(venv_base)),
        )
        config_path = tmp_path / "config.json"
        save_config(config, path=config_path)
        return config_path

    def test_fixes_all_venvs(self, tmp_path: Path) -> None:
        venv_base = tmp_path / "venvs"
        _make_venv(venv_base, "env1", virtual_env_path="/old/env1")
        _make_venv(venv_base, "env2", virtual_env_path="/old/env2")
        config_path = self._make_config(tmp_path, venv_base)

        run_fixup(config_path=config_path)

        for name in ("env1", "env2"):
            activate = (venv_base / name / "bin" / "activate").read_text()
            assert str(venv_base / name) in activate
            assert "/old/" not in activate

    def test_fixes_single_venv(self, tmp_path: Path) -> None:
        venv_base = tmp_path / "venvs"
        _make_venv(venv_base, "env1", virtual_env_path="/old/env1")
        _make_venv(venv_base, "env2", virtual_env_path="/old/env2")
        config_path = self._make_config(tmp_path, venv_base)

        run_fixup(venv_name="env1", config_path=config_path)

        # env1 should be fixed
        act1 = (venv_base / "env1" / "bin" / "activate").read_text()
        assert str(venv_base / "env1") in act1

        # env2 should still have old path
        act2 = (venv_base / "env2" / "bin" / "activate").read_text()
        assert "/old/env2" in act2

    def test_nonexistent_venv_raises(self, tmp_path: Path) -> None:
        venv_base = tmp_path / "venvs"
        venv_base.mkdir()
        config_path = self._make_config(tmp_path, venv_base)

        with pytest.raises(ValueError, match="not found"):
            run_fixup(venv_name="nonexistent", config_path=config_path)

    def test_no_apptainer_config_raises(self, tmp_path: Path) -> None:
        config = EulerFilesConfig(scratch_base=str(tmp_path), vars={})
        config_path = tmp_path / "config.json"
        save_config(config, path=config_path)

        with pytest.raises(FileNotFoundError, match="apptainer init"):
            run_fixup(config_path=config_path)
