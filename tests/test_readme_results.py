"""readme results block is rebuilt from the report summary between fixed markers."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parent.parent

SUMMARY = {
    "generated_at": "2026-11-28T10:00:00+0530",
    "tasks_total": 40,
    "tasks_by_family": {"fail-fast-config": 6, "config-round-trip": 4},
    "validation": {"candidates": 70, "accepted": 40, "mutants_total": 200, "mutants_killed": 180},
    "models": [
        {"model": "m-low", "agent": "terminus-2", "k": 1, "pass_rate": 0.25, "n": 40},
        {"model": "m-high", "agent": "claude-code", "k": 1, "pass_rate": 0.6, "n": 40},
    ],
    "failures": {"m-low": {"fault": 18, "happy": 4, "regression": 1}},
    "spend_usd": 0.0,
    "findings": ["models miss the failure modes."],
}


def _mod() -> ModuleType:
    spec = importlib.util.spec_from_file_location("readme_results", REPO / "scripts" / "readme_results.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_block_is_replaced_and_surroundings_kept(tmp_path: Path) -> None:
    mod = _mod()
    readme = tmp_path / "README.md"
    readme.write_text(f"# x\n\n## Results\n\n{mod.START}\nold\n{mod.END}\n\n## Next\n")
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps(SUMMARY))
    mod.main(str(summary), str(readme))
    text = readme.read_text()
    assert "old" not in text and text.startswith("# x") and text.rstrip().endswith("## Next")
    assert "| Tasks in the dataset | 40 across 2 families |" in text
    assert "| Candidates passing every gate | 40 of 70 |" in text
    assert "180 of 200 (90%)" in text
    assert "$0.00 (hard cap $70)" in text
    # best model first
    assert text.index("m-high") < text.index("| m-low | terminus-2")
    assert "| m-low | 18 | 4 | 1 |" in text
    assert "- models miss the failure modes." in text
    # idempotent: a second run gives the same file
    mod.main(str(summary), str(readme))
    assert readme.read_text() == text


def test_missing_markers_refuse(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        _mod().update("# no markers\n", SUMMARY)


def test_repo_readme_has_markers() -> None:
    mod = _mod()
    text = (REPO / "README.md").read_text()
    assert mod.START in text and mod.END in text
