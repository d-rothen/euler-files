"""Helpers for JSON-based CLI input and output."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def load_json_input(input_json: Optional[str]) -> Dict[str, Any]:
    """Load a JSON object from a file path or stdin."""
    if input_json is None:
        return {}

    if input_json == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(input_json).read_text()

    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Input JSON must be an object.")
    return data


def dump_json(data: Dict[str, Any]) -> str:
    """Render a JSON object for CLI output."""
    return json.dumps(data, indent=2, sort_keys=True) + "\n"
