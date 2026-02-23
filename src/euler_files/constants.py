"""Preset environment variables and their default paths."""

from __future__ import annotations

from typing import Dict

# Preset env vars: name -> default path relative to $HOME
PRESETS: Dict[str, str] = {
    "HF_HOME": ".cache/huggingface",
    "TORCH_HOME": ".cache/torch",
    "TRANSFORMERS_CACHE": ".cache/huggingface/transformers",
    "PIP_CACHE_DIR": ".cache/pip",
    "XDG_CACHE_HOME": ".cache",
    "CONDA_PKGS_DIRS": ".conda/pkgs",
}

# Human-readable descriptions for the wizard
PRESET_DESCRIPTIONS: Dict[str, str] = {
    "HF_HOME": "HuggingFace hub models, datasets, tokenizers",
    "TORCH_HOME": "PyTorch hub models and checkpoints",
    "TRANSFORMERS_CACHE": "HuggingFace transformers (subset of HF_HOME)",
    "PIP_CACHE_DIR": "pip download cache",
    "XDG_CACHE_HOME": "General XDG cache directory (large, includes many tools)",
    "CONDA_PKGS_DIRS": "Conda package cache",
}
