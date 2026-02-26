"""Tests for congruency checking."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from euler_files.config import ApptainerConfig, EulerFilesConfig, VarConfig
from euler_files.congruency import check_congruency, format_warnings


class TestCheckCongruency:
    def test_no_warnings_when_congruent(self, tmp_path: Path) -> None:
        source = tmp_path / "hf"
        source.mkdir()
        config = EulerFilesConfig(
            scratch_base=str(tmp_path),
            vars={"HF_HOME": VarConfig(source=str(source))},
        )
        with patch.dict("os.environ", {"HF_HOME": str(source)}):
            warnings = check_congruency(config)
        assert warnings == []

    def test_warning_when_env_var_differs(self, tmp_path: Path) -> None:
        config = EulerFilesConfig(
            scratch_base=str(tmp_path),
            vars={"HF_HOME": VarConfig(source="/new/path/hf")},
        )
        with patch.dict("os.environ", {"HF_HOME": "/old/path/hf"}):
            warnings = check_congruency(config)
        assert len(warnings) == 1
        assert warnings[0].var_name == "HF_HOME"
        assert warnings[0].env_value == "/old/path/hf"
        assert warnings[0].config_value == "/new/path/hf"
        assert "export HF_HOME=/new/path/hf" in warnings[0].message

    def test_no_warning_when_env_var_unset(self) -> None:
        config = EulerFilesConfig(
            scratch_base="/scratch",
            vars={"HF_HOME": VarConfig(source="/some/path")},
        )
        with patch.dict("os.environ", {}, clear=True):
            warnings = check_congruency(config)
        assert warnings == []

    def test_multiple_vars_one_mismatch(self, tmp_path: Path) -> None:
        good_path = tmp_path / "torch"
        good_path.mkdir()
        config = EulerFilesConfig(
            scratch_base=str(tmp_path),
            vars={
                "TORCH_HOME": VarConfig(source=str(good_path)),
                "HF_HOME": VarConfig(source="/new/hf"),
            },
        )
        with patch.dict("os.environ", {
            "TORCH_HOME": str(good_path),
            "HF_HOME": "/old/hf",
        }):
            warnings = check_congruency(config)
        assert len(warnings) == 1
        assert warnings[0].var_name == "HF_HOME"

    def test_disabled_var_skipped(self) -> None:
        config = EulerFilesConfig(
            scratch_base="/scratch",
            vars={"HF_HOME": VarConfig(source="/new/hf", enabled=False)},
        )
        with patch.dict("os.environ", {"HF_HOME": "/old/hf"}):
            warnings = check_congruency(config)
        assert warnings == []

    def test_path_normalization(self, tmp_path: Path) -> None:
        """Paths that resolve to the same location should not warn."""
        source = tmp_path / "cache" / "hf"
        source.mkdir(parents=True)
        # Use a path with '..' that resolves to the same place
        alt_path = str(tmp_path / "cache" / "extra" / ".." / "hf")
        config = EulerFilesConfig(
            scratch_base=str(tmp_path),
            vars={"HF_HOME": VarConfig(source=str(source))},
        )
        with patch.dict("os.environ", {"HF_HOME": alt_path}):
            warnings = check_congruency(config)
        assert warnings == []

    def test_apptainer_venv_base_missing_dir(self, tmp_path: Path) -> None:
        config = EulerFilesConfig(
            scratch_base=str(tmp_path),
            vars={},
            apptainer=ApptainerConfig(
                venv_base="$TEST_VENV_DIR",
            ),
        )
        with patch.dict("os.environ", {"TEST_VENV_DIR": str(tmp_path / "nonexistent")}):
            warnings = check_congruency(config)
        assert len(warnings) == 1
        assert "venv_base" in warnings[0].message
        assert "does not exist" in warnings[0].message

    def test_apptainer_venv_base_exists(self, tmp_path: Path) -> None:
        venv_dir = tmp_path / "venvs"
        venv_dir.mkdir()
        config = EulerFilesConfig(
            scratch_base=str(tmp_path),
            vars={},
            apptainer=ApptainerConfig(
                venv_base="$TEST_VENV_DIR",
            ),
        )
        with patch.dict("os.environ", {"TEST_VENV_DIR": str(venv_dir)}):
            warnings = check_congruency(config)
        assert warnings == []

    def test_apptainer_literal_path_not_checked(self) -> None:
        """Literal paths (not env var refs) are not checked for apptainer."""
        config = EulerFilesConfig(
            scratch_base="/scratch",
            vars={},
            apptainer=ApptainerConfig(
                venv_base="/some/literal/path",
            ),
        )
        warnings = check_congruency(config)
        assert warnings == []


class TestFormatWarnings:
    def test_empty_warnings(self) -> None:
        assert format_warnings([]) == ""

    def test_formats_warnings(self) -> None:
        from euler_files.congruency import CongruencyWarning

        warnings = [
            CongruencyWarning(
                var_name="HF_HOME",
                env_value="/old",
                config_value="/new",
                message="HF_HOME mismatch",
            ),
        ]
        result = format_warnings(warnings)
        assert "[WARN]" in result
        assert "HF_HOME mismatch" in result
