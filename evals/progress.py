"""Atomic per-case checkpoints; API responses remain in the existing raw cache."""

import json
from pathlib import Path
from typing import Any

from agent_patterns.providers.base import write_json_atomic


class Progress:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.rows: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {}

    def save(self, key: str, result: dict[str, Any]) -> None:
        self.rows[key] = result
        write_json_atomic(self.path, self.rows)
