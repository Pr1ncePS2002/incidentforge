"""coverage parsing, scoring, the docker run (mocked; one real run is docker-marked) and the cache."""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from failmap_repos import py_repo, target

from incidentforge.failmap import coverage
from incidentforge.failmap.build import build
from incidentforge.failmap.store import read_annotations
from incidentforge.failmap.tag import tag
from incidentforge.models import Language

GO_PROFILE = """mode: set
example.com/svc/internal/config/options.go:30.20,33.2 2 1
example.com/svc/internal/config/options.go:35.20,38.2 2 0
garbage line
"""


def test_parse_go():
    lines = coverage.parse_go(GO_PROFILE, "example.com/svc")
    assert lines == {"internal/config/options.go": {"executed": [30, 31, 32, 33], "missing": [35, 36, 37, 38]}}


def test_parse_python():
    data = {"files": {"/app/backend/app/x.py": {"executed_lines": [3, 1], "missing_lines": [9]}, "backend/y.py": {}}}
    assert coverage.parse_python(data) == {
        "backend/app/x.py": {"executed": [1, 3], "missing": [9]},
        "backend/y.py": {"executed": [], "missing": []},
    }


def test_go_module(tmp_path: Path):
    (tmp_path / "go.mod").write_text("// c\nmodule example.com/svc\n")
    assert coverage.go_module(tmp_path) == "example.com/svc"
    (tmp_path / "go.mod").write_text("go 1.22\n")
    with pytest.raises(ValueError):
        coverage.go_module(tmp_path)


def test_coverage_command():
    go = coverage.coverage_command(target("m", Language.go))
    assert go == "run_tests -coverprofile=/out/cover.out ./..."
    py = coverage.coverage_command(target("p", Language.python))
    assert "coverage run -m pytest" in py and "bash /tmp/rt -q tests/" in py and "/out/coverage.json" in py


def test_score():
    full = coverage.score([1, 2, 3], [], 1, 3, static_tests=1)
    assert full == coverage.Coverage(True, 1.0, 1)
    half = coverage.score([1], [2], 1, 2, static_tests=0)
    assert half.covered and half.risk_score == 2.0
    none = coverage.score([], [], 1, 2, static_tests=0)
    assert not none.covered and none.risk_score == 2.5


class FakeDocker:
    """records docker calls and writes the report a real run would leave in /out."""

    def __init__(self, report: str | None, image_exists: bool = True) -> None:
        self.calls: list[list[str]] = []
        self.report = report
        self.image_exists = image_exists

    def __call__(self, cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        if cmd[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(cmd, 0 if self.image_exists else 1, "", "")
        if cmd[:2] == ["docker", "run"] and self.report is not None:
            out = Path(cmd[cmd.index("-v") + 1].split(":")[0])
            name, text = self.report.split("|", 1)
            (out / name).write_text(text)
        return subprocess.CompletedProcess(cmd, 0, "ok", "")


def test_run_coverage_go(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "go.mod").write_text("module example.com/svc\n")
    fake = FakeDocker("cover.out|" + GO_PROFILE, image_exists=False)
    monkeypatch.setattr(coverage.subprocess, "run", fake)
    lines = coverage.run_coverage(target("m", Language.go), tmp_path / "repo", tmp_path / "out", "img:x")
    assert lines["internal/config/options.go"]["executed"][0] == 30
    assert [c[1] for c in fake.calls] == ["image", "build", "run"]


def test_run_coverage_python_and_missing_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    report = json.dumps({"files": {"backend/app/x.py": {"executed_lines": [1], "missing_lines": []}}})
    monkeypatch.setattr(coverage.subprocess, "run", FakeDocker("coverage.json|" + report))
    lines = coverage.run_coverage(target("p", Language.python), tmp_path, tmp_path / "o1", "img:x")
    assert lines == {"backend/app/x.py": {"executed": [1], "missing": []}}
    monkeypatch.setattr(coverage.subprocess, "run", FakeDocker(None))
    with pytest.raises(RuntimeError, match=r"wrote no coverage\.json"):
        coverage.run_coverage(target("p", Language.python), tmp_path, tmp_path / "o2", "img:x")


def test_load_or_run_caches_by_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    t = target("p", Language.python)
    assert coverage.load_or_run(t, tmp_path, tmp_path, None, run=False) is None
    report = json.dumps({"files": {"a.py": {"executed_lines": [1], "missing_lines": [2]}}})
    fake = FakeDocker("coverage.json|" + report)
    monkeypatch.setattr(coverage.subprocess, "run", fake)
    first = coverage.load_or_run(t, tmp_path, tmp_path, None, run=True)
    assert coverage.cache_path(tmp_path, t.commit).name == "coverage-0123456789ab.json"
    assert "incidentforge/p-env:map" in fake.calls[0]
    fake.calls.clear()
    assert coverage.load_or_run(t, tmp_path, tmp_path, None, run=True) == first and fake.calls == []


def test_apply_static_and_dynamic(tmp_path: Path):
    m = build(py_repo(tmp_path / "r"), Language.python, tmp_path / "o").map_path
    tag(m)
    static = coverage.apply(m, None)
    assert static["app/crud.py::create_user#handler"].covered is True
    assert static["app/export.py::save_config"] == coverage.Coverage(False, 2.5, 0)
    lines = {"app/export.py": {"executed": [5], "missing": [6]}}
    dyn = coverage.apply(m, lines)
    assert dyn["app/export.py::save_config"].covered is True and dyn["app/export.py::save_config"].risk_score == 2.0
    # a file the run never measured counts as uncovered
    assert dyn["app/crud.py::create_user#handler"].covered is False
    assert read_annotations(m)["app/export.py::save_config"].risk_score == 2.0


@pytest.mark.docker
def test_real_go_coverage_run(tmp_path: Path):
    from incidentforge.generate import checkout
    from incidentforge.targets import load_target

    t = load_target("miniflux")
    repo = checkout(t, Path("work"))
    lines = coverage.run_coverage(t, repo, tmp_path, "incidentforge/miniflux-env:test")
    assert any(info["executed"] for f, info in lines.items() if f.startswith("internal/config/"))
