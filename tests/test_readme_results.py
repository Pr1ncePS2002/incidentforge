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
    assert "spend" not in text.lower() and "$70" not in text
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


def test_primary_target_leads_the_block() -> None:
    click = {
        "tasks_total": 10,
        "tasks_by_family": {"a": 4, "b": 6},
        "validation": {
            "candidates": 18,
            "passed_gates": 14,
            "accepted": 10,
            "dropped": [{"task": "x"}],
            "mutants_total": 50,
            "mutants_killed": 45,
        },
        "harbor_matrix": {
            "harbor_version": "0.25.0",
            "nop": {"ok": 10, "total": 10},
            "oracle": {"ok": 10, "total": 10},
        },
        "models": [
            {"model": "m-low", "agent": "terminus-2", "k": 1, "pass_rate": 0.2, "mean_reward": 0.45, "n": 10},
            {"model": "m-high", "agent": "claude-code", "k": 1, "pass_rate": 0.9, "mean_reward": 0.95, "n": 10},
        ],
        "failure_causes": {
            "by_model": {"m-low": {"turn_budget": 3, "regression": 0, "fault_path_missed": 4, "wrong_code": 1}}
        },
        "findings": ["click finding."],
    }
    text = _mod().render(SUMMARY | {"by_target": {"primary": "click", "extra": [], "click": click}})
    assert "| Tasks in the dataset | 10 across 2 families |" in text
    assert "| Passing every gate | 14 of 18 |" in text and "| Kept in the dataset | 10 (1 dropped on review) |" in text
    assert "| No-op agent scores 0.0 | 10 of 10 (Harbor 0.25.0) |" in text
    assert "| m-high | claude-code | 10 (k=1) | 90% | 0.95 |" in text
    assert text.index("m-high") < text.index("| m-low |")
    assert "| m-low | 3 | 0 | 4 | 1 |" in text and "- click finding." in text
    # the all-target numbers stay out of the click block
    assert "40 across" not in text and "models miss" not in text
