"""Bundled reference data shipped with the catalog package."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
SOURCE_PATHS_FILE = DATA_DIR / "source_paths.json"


@lru_cache(maxsize=1)
def source_paths() -> tuple[tuple[str, int], ...]:
    """The audited source category paths with their record counts."""
    payload = json.loads(SOURCE_PATHS_FILE.read_text(encoding="utf-8"))
    return tuple((path, int(count)) for path, count in payload["paths"])


@lru_cache(maxsize=1)
def known_paths() -> frozenset[str]:
    return frozenset(path.strip("/").lower() for path, _ in source_paths())
