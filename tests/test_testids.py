"""fail_to_pass ids from feature sources, pass_to_pass ids from the target suite."""

import json
import subprocess
from pathlib import Path

import pytest

from incidentforge import testids
from incidentforge.models import Language, Target

SHA = "0123456789abcdef0123456789abcdef01234567"


def _target(language: Language = Language.python, test_command: str = "run_tests -q tests/") -> Target:
    return Target(
        name="demo",
        repo_url="u",
        commit=SHA,
        licence="MIT",
        language=language,
        env_template=Path("."),
        test_command=test_command,
    )


def test_python_ids_cover_functions_and_class_methods():
    src = (
        "import pytest\n\ndef helper():\n    pass\n\ndef test_a():\n    pass\n\n"
        "async def test_b():\n    pass\n\nclass TestC:\n    def test_d(self):\n        pass\n"
        "    def setup_method(self):\n        pass\n\nclass Helper:\n    def test_no(self):\n        pass\n"
    )
    assert testids.fail_to_pass(Language.python, {"tests/test_x.py": src}) == [
        "tests/test_x.py::test_a",
        "tests/test_x.py::test_b",
        "tests/test_x.py::TestC::test_d",
    ]
    assert testids.python_test_names("def (") == []


def test_go_ids_are_package_qualified():
    src = "package x\n\nfunc TestA(t *testing.T) {}\nfunc helper(t *testing.T) {}\nfunc TestB( tt *testing.T ) {}\n"
    assert testids.fail_to_pass(Language.go, {"internal/x/a_test.go": src, "b_test.go": src}) == [
        "internal/x::TestA",
        "internal/x::TestB",
        ".::TestA",
        ".::TestB",
    ]


def test_collect_command():
    assert testids.collect_command(_target()) == "run_tests --collect-only -q -p no:cacheprovider tests/"
    assert "-list . ./..." in testids.collect_command(_target(Language.go, "run_tests ./..."))


def test_parse_collected_pytest():
    out = (
        "tests/a.py::test_x\ntests/a.py::test_p[1 2]\n\n"
        "tests/a.py::test_x\n  /venv/x.py:1: Warning:: here\n3 tests collected in 0.1s\n"
    )
    assert testids.parse_collected(Language.python, out) == ["tests/a.py::test_p[1 2]", "tests/a.py::test_x"]


def test_parse_collected_go():
    out = (
        "module example.com/m\nTestRoot\nExampleRoot\nok  \texample.com/m\t0.01s\n"
        "TestA\nBenchmarkA\nok  \texample.com/m/internal/a\t0.02s\n"
        "?   \texample.com/m/cmd\t[no test files]\n"
    )
    assert testids.parse_collected(Language.go, out) == [".::ExampleRoot", ".::TestRoot", "internal/a::TestA"]


def test_pass_to_pass_is_cached(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(testids, "collect_pass_to_pass", lambda t: calls.append(t) or ["a::b"])
    assert testids.pass_to_pass(_target(), tmp_path) == ["a::b"]
    assert testids.pass_to_pass(_target(), tmp_path) == ["a::b"]
    assert len(calls) == 1
    assert json.loads((tmp_path / "demo-0123456789ab.json").read_text()) == ["a::b"]


def _fake_docker(monkeypatch, stdout: str, rc: int = 0) -> list[list[str]]:
    seen: list[list[str]] = []

    def run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, rc, stdout, "")

    monkeypatch.setattr("incidentforge.failmap.coverage.ensure_image", lambda target, image: None)
    monkeypatch.setattr(testids.subprocess, "run", run)
    return seen


def test_collect_pass_to_pass_runs_in_the_target_image(monkeypatch):
    seen = _fake_docker(monkeypatch, "tests/a.py::test_x\n")
    assert testids.collect_pass_to_pass(_target()) == ["tests/a.py::test_x"]
    assert seen[0][:4] == ["docker", "run", "--rm", "incidentforge/demo-env:0123456789ab"]


@pytest.mark.parametrize(("stdout", "rc"), [("tests/a.py::test_x\n", 2), ("no tests ran\n", 0)])
def test_collect_pass_to_pass_fails_loudly(monkeypatch, stdout, rc):
    _fake_docker(monkeypatch, stdout, rc)
    with pytest.raises(RuntimeError, match="collecting demo tests failed"):
        testids.collect_pass_to_pass(_target())


def test_target_needs_a_full_sha():
    with pytest.raises(ValueError):
        Target.model_validate({**_target().model_dump(), "commit": "abc123"})
