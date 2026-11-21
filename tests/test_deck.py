"""deck data loading: summary.json is authoritative, including explicit zeros; raw logs only fill gaps."""

from __future__ import annotations

import importlib.util
import json
from html import escape
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parent.parent


def _deck() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_deck", REPO / "deck" / "build_deck.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _log(root: Path, task: str, accepted: bool, killed: int) -> None:
    path = root / "reports" / "validation" / "t" / f"{task}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"accepted": accepted, "mutants_total": 5, "mutants_killed": killed}))


def _summary(root: Path, data: dict[str, object]) -> None:
    (root / "reports").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "summary.json").write_text(json.dumps(data))


def test_explicit_zero_totals_win_over_old_logs(tmp_path: Path) -> None:
    _log(tmp_path, "a", True, 4)
    _summary(
        tmp_path,
        {
            "tasks_total": 0,
            "validation": {"candidates": 3, "accepted": 0, "mutants_total": 0, "mutants_killed": 0},
        },
    )
    d = _deck().load_data(tmp_path)
    assert (d["validated"], d["accepted"], d["mutants_total"], d["mutants_killed"]) == (3, 0, 0, 0)
    assert d["tasks_total"] == 0


def test_logs_fill_in_when_summary_is_missing(tmp_path: Path) -> None:
    _log(tmp_path, "a", True, 4)
    _log(tmp_path, "b", False, 1)
    d = _deck().load_data(tmp_path)
    assert (d["validated"], d["accepted"], d["mutants_total"], d["mutants_killed"]) == (2, 1, 5, 4)


def test_nothing_known_renders_as_tbd(tmp_path: Path) -> None:
    deck = _deck()
    d = deck.load_data(tmp_path)
    assert d["accepted"] is None and d["tasks_total"] is None
    assert deck.TBD in deck._v(d["accepted"])
    assert deck._v(0) == "0"


def test_cause_bars_count_each_failed_run_once() -> None:
    deck = _deck()
    svg = deck._cause_bars({"m": {"turn_budget": 3, "wrong_code": 2}, "n": {"regression": 1}})
    # totals are drawn after each bar; the legend names all four causes
    assert ">5</text>" in svg and ">1</text>" in svg
    assert all(escape(label) in svg for _, label, _ in deck.CAUSES)


def test_difficulty_counted_from_task_metadata(tmp_path: Path) -> None:
    for name, level in (("a", "easy"), ("b", "easy"), ("c", "hard")):
        toml = tmp_path / "tasks" / "t" / name / "task.toml"
        toml.parent.mkdir(parents=True)
        toml.write_text(f'[metadata]\ndifficulty = "{level}"\n')
    assert _deck().load_data(tmp_path)["difficulty"] == {"easy": 2, "hard": 1}


def test_map_slide_without_data_shows_tbd(tmp_path: Path) -> None:
    deck = _deck()
    d = deck.load_data(tmp_path)
    html = deck._map_slide(d)
    assert deck.TBD in html and "failure-map.png" not in html
