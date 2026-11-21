"""failure map: code graph of a target with family tags, blast radius, coverage and clusters. owner: v2-map."""

from __future__ import annotations

from pathlib import Path

MAP_FILE = "map.sqlite"
JSON_FILE = "map.json"


def map_dir(work_root: Path, target: str) -> Path:
    return work_root / target
