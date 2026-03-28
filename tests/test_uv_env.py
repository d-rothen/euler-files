"""Tests for uv environment installation helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from euler_files.uv_env import infer_pytorch_extra_index_urls, run_venv_install


def test_infer_pytorch_extra_index_urls_for_cuda_wheels() -> None:
    urls = infer_pytorch_extra_index_urls(
        ["torch==2.4.0+cu121", "torchvision==0.19.0+cu121", "numpy"]
    )
    assert urls == ["https://download.pytorch.org/whl/cu121"]


def test_infer_pytorch_extra_index_urls_rejects_conflicting_variants() -> None:
    with pytest.raises(ValueError, match="Conflicting PyTorch wheel variants"):
        infer_pytorch_extra_index_urls(
            ["torch==2.4.0+cu121", "torchvision==0.19.0+cu118"]
        )


def test_run_venv_install_dry_run_without_uv_binary(tmp_path: Path) -> None:
    venv_base = tmp_path / "venvs"

    with patch("euler_files.uv_env.shutil.which", return_value=None):
        result = run_venv_install(
            env_name="ml-env",
            packages=["torch==2.4.0+cu121", "datasets"],
            venv_base=str(venv_base),
            dry_run=True,
        )

    assert result["created"] is True
    assert result["venv_path"] == str(venv_base / "ml-env")
    assert result["commands"][0].startswith("uv venv ")
    assert "--extra-index-url https://download.pytorch.org/whl/cu121" in result["commands"][1]


def test_run_venv_install_executes_create_and_install(tmp_path: Path) -> None:
    venv_base = tmp_path / "venvs"

    with patch("euler_files.uv_env.shutil.which", return_value="/usr/bin/uv"), patch(
        "euler_files.uv_env.subprocess.run", return_value=MagicMock(returncode=0)
    ) as mock_run:
        result = run_venv_install(
            env_name="ml-env",
            packages=["transformers"],
            venv_base=str(venv_base),
        )

    assert result["created"] is True
    assert mock_run.call_count == 2
