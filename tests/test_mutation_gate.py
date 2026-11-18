"""the nightly mutation gate: survivors fail unless allowlisted for this platform."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mutation_gate", ROOT / "scripts" / "mutation_gate.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load()

RESULTS = """    pkg.a__mutmut_1: killed
    pkg.a__mutmut_2: survived
    pkg.a__mutmut_3: no tests
    pkg.a__mutmut_4: timeout
    pkg.a__mutmut_5: killed
"""


def test_parse_results() -> None:
    assert gate.parse_results(RESULTS + "\nnoise\n")["pkg.a__mutmut_3"] == "no tests"
    assert len(gate.parse_results(RESULTS)) == 5


def test_allowlist_filters_by_platform_and_needs_a_reason() -> None:
    text = "# c\n\npkg.x any equivalent\npkg.y darwin case only fs\npkg.z linux other\n"
    assert gate.load_allowlist(text, "darwin") == {"pkg.x": "equivalent", "pkg.y": "case only fs"}
    with pytest.raises(ValueError):
        gate.load_allowlist("pkg.x any\n", "linux")


def test_evaluate_flags_unlisted_survivors_and_stale_entries() -> None:
    results = gate.parse_results(RESULTS)
    allow = {"pkg.a__mutmut_2": "eq", "pkg.a__mutmut_5": "eq"}
    bad, stale, summary = gate.evaluate(results, allow)
    assert bad == ["pkg.a__mutmut_3: no tests"]
    assert stale == ["pkg.a__mutmut_5"]
    assert summary == "mutants: 5, killed 3 (60.0%), allowlisted 1, failing 1"


def test_main_reads_a_saved_results_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "r.txt"
    f.write_text("    pkg.b__mutmut_1: killed\n")
    assert gate.main([str(f)]) == 0
    f.write_text("    pkg.b__mutmut_1: survived\n")
    assert gate.main([str(f)]) == 1
    assert "::error::mutant not killed: pkg.b__mutmut_1: survived" in capsys.readouterr().out
    f.write_text("")
    assert gate.main([str(f)]) == 1


def test_committed_allowlist_parses() -> None:
    assert gate.load_allowlist(gate.ALLOWLIST.read_text(), sys.platform)
