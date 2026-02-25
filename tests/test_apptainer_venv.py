"""Tests for apptainer venv introspection utilities."""

from __future__ import annotations

from pathlib import Path

import pytest

from euler_files.apptainer.venv import (
    detect_python_version,
    list_venvs,
    parse_pyvenv_cfg,
    validate_venv,
)


def _create_venv(base: Path, name: str, cfg_content: str) -> Path:
    """Helper to create a mock venv directory."""
    venv = base / name
    venv.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text(cfg_content)
    (venv / "bin").mkdir()
    (venv / "bin" / "python").write_text("#!/usr/bin/env python3\n")
    return venv


class TestParsePyvenvCfg:
    def test_uv_cfg(self, tmp_path: Path) -> None:
        venv = _create_venv(tmp_path, "test", (
            "home = /usr/bin\n"
            "implementation = CPython\n"
            "uv = 0.4.0\n"
            "version_info = 3.11.5\n"
            "include-system-site-packages = false\n"
        ))
        cfg = parse_pyvenv_cfg(venv)
        assert cfg["home"] == "/usr/bin"
        assert cfg["version_info"] == "3.11.5"
        assert cfg["uv"] == "0.4.0"

    def test_stdlib_cfg(self, tmp_path: Path) -> None:
        venv = _create_venv(tmp_path, "test", (
            "home = /usr/bin\n"
            "implementation = CPython\n"
            "version = 3.12.0\n"
        ))
        cfg = parse_pyvenv_cfg(venv)
        assert cfg["version"] == "3.12.0"

    def test_missing_cfg(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="No pyvenv.cfg"):
            parse_pyvenv_cfg(tmp_path / "nonexistent")

    def test_empty_lines_and_comments(self, tmp_path: Path) -> None:
        venv = _create_venv(tmp_path, "test", (
            "# comment\n"
            "\n"
            "home = /usr/bin\n"
            "\n"
            "version_info = 3.10.0\n"
        ))
        cfg = parse_pyvenv_cfg(venv)
        assert cfg["home"] == "/usr/bin"
        assert cfg["version_info"] == "3.10.0"
        assert len(cfg) == 2


class TestDetectPythonVersion:
    def test_uv_version_info(self, tmp_path: Path) -> None:
        venv = _create_venv(tmp_path, "test", "version_info = 3.11.5\n")
        assert detect_python_version(venv) == "3.11.5"

    def test_stdlib_version(self, tmp_path: Path) -> None:
        venv = _create_venv(tmp_path, "test", "version = 3.12.0\n")
        assert detect_python_version(venv) == "3.12.0"

    def test_version_info_preferred_over_version(self, tmp_path: Path) -> None:
        venv = _create_venv(tmp_path, "test", (
            "version_info = 3.11.5\n"
            "version = 3.11.5\n"
        ))
        assert detect_python_version(venv) == "3.11.5"

    def test_no_version_key(self, tmp_path: Path) -> None:
        venv = _create_venv(tmp_path, "test", "home = /usr/bin\n")
        with pytest.raises(ValueError, match="Could not detect Python version"):
            detect_python_version(venv)


class TestValidateVenv:
    def test_valid_venv(self, tmp_path: Path) -> None:
        venv = _create_venv(tmp_path, "test", "version_info = 3.11.5\n")
        validate_venv(venv)  # Should not raise

    def test_not_a_directory(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Not a directory"):
            validate_venv(tmp_path / "nonexistent")

    def test_no_pyvenv_cfg(self, tmp_path: Path) -> None:
        d = tmp_path / "not-a-venv"
        d.mkdir()
        with pytest.raises(ValueError, match="no pyvenv.cfg"):
            validate_venv(d)

    def test_no_bin_dir(self, tmp_path: Path) -> None:
        d = tmp_path / "partial-venv"
        d.mkdir()
        (d / "pyvenv.cfg").write_text("version_info = 3.11\n")
        with pytest.raises(ValueError, match="no bin/ directory"):
            validate_venv(d)


class TestListVenvs:
    def test_discovers_venvs(self, tmp_path: Path) -> None:
        _create_venv(tmp_path, "env-a", "version_info = 3.11.5\n")
        _create_venv(tmp_path, "env-b", "version = 3.12.0\n")
        # Not a venv:
        (tmp_path / "not-a-venv").mkdir()
        # A file, not a dir:
        (tmp_path / "some-file.txt").write_text("hi")

        venvs = list_venvs(tmp_path)
        assert len(venvs) == 2
        assert venvs[0].name == "env-a"
        assert venvs[0].python_version == "3.11.5"
        assert venvs[0].python_major_minor == "3.11"
        assert venvs[1].name == "env-b"
        assert venvs[1].python_version == "3.12.0"
        assert venvs[1].python_major_minor == "3.12"

    def test_nonexistent_base(self, tmp_path: Path) -> None:
        venvs = list_venvs(tmp_path / "nonexistent")
        assert venvs == []

    def test_empty_directory(self, tmp_path: Path) -> None:
        venvs = list_venvs(tmp_path)
        assert venvs == []

    def test_skips_unparseable_venv(self, tmp_path: Path) -> None:
        # Venv with no version info in cfg
        venv = tmp_path / "bad-venv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
        (venv / "bin").mkdir()

        venvs = list_venvs(tmp_path)
        assert venvs == []
