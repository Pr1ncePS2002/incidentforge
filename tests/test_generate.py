"""generation loop against a local git fixture repo, a fake backend and a fake validator."""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from incidentforge import generate as gen_mod
from incidentforge.families import load_family
from incidentforge.generate import (
    describe_failure,
    difficulty,
    generate,
    gold_example,
    plan_pairs,
    slugify,
)
from incidentforge.models import GateResult, Language, Surface, Target, ValidationReport
from incidentforge.package import write_task

CONFIG = """from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    NAME: str = "x"
    POOL_SIZE: int = 5
"""
NEW_CONFIG = CONFIG.replace('    NAME: str = "x"\n', '    NAME: str = "x"\n    STRICT: bool = True\n')
TESTS = {"test_forge_x.py": "def test_fault_missing():\n    assert True\n\ndef test_valid():\n    assert True\n"}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def target(tmp_path: Path) -> Target:
    repo = tmp_path / "upstream"
    (repo / "backend" / "app").mkdir(parents=True)
    (repo / "backend" / "app" / "config.py").write_text(CONFIG)
    _git(repo.parent, "init", "-q", str(repo))
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    commit = _git(repo, "rev-parse", "HEAD").strip()
    env = tmp_path / "env"
    env.mkdir()
    (env / "Dockerfile").write_text("FROM scratch\nARG REPO_URL=x\nARG REPO_COMMIT=y\n")
    return Target(
        name="fixture",
        repo_url=str(repo),
        commit=commit,
        language=Language.python,
        env_template=env,
        test_command="run_tests -q tests/",
        source_root="backend",
    )


def good_patch(target: Target) -> str:
    repo = Path(target.repo_url)
    (repo / "backend/app/config.py").write_text(NEW_CONFIG)
    diff = _git(repo, "diff")
    _git(repo, "checkout", "--", ".")
    return diff


class FakeBackend:
    name = "fake"

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    def generate_json(
        self, prompt: str, schema: dict[str, Any], max_output_tokens: int = 8192, tag: str = ""
    ) -> dict[str, Any]:
        self.prompts.append(prompt)
        self.max_tokens = max_output_tokens
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return dict(a)


def answer(patch: str, title: str = "strict mode flag") -> dict[str, Any]:
    return {
        "title": title,
        "instruction": "add a strict flag",
        "solution_patch": patch,
        "feature_tests": TESTS,
        "fault_cases": ["missing: STRICT unset"],
        "difficulty": "hard",
    }


class FakeValidator:
    def __init__(self, *verdicts: bool) -> None:
        self.verdicts = list(verdicts)
        self.dirs: list[Path] = []

    def __call__(self, task_dir: Path) -> ValidationReport:
        self.dirs.append(task_dir)
        ok = self.verdicts.pop(0)
        gate = GateResult(gate="fail_on_base", passed=ok, detail="" if ok else "tests passed on base")
        return ValidationReport(task_id=task_dir.name, accepted=ok, gates=[gate], mutants_total=3)


def run(target: Target, tmp_path: Path, backend: FakeBackend, validator: FakeValidator, **kw: Any) -> list[Any]:
    return generate(
        target,
        kw.pop("families", ["fail-fast-config"]),
        kw.pop("n", 1),
        backend,
        tasks_root=tmp_path / "tasks",
        work_root=tmp_path / "work",
        writer=write_task,
        validator=validator,
        jobs=1,
        log=lambda _m: None,
        **kw,
    )


def test_accepts_first_try(target: Target, tmp_path: Path) -> None:
    patch = good_patch(target)
    backend = FakeBackend(answer(patch))
    reports = run(target, tmp_path, backend, FakeValidator(True))
    assert [r.accepted for r in reports] == [True]
    (task,) = (tmp_path / "tasks" / "fixture").iterdir()
    assert task.name.startswith("ff-001-")
    assert "STRICT" in (task / "solution" / "reference.patch").read_text()
    # one changed file and one fault is easy, whatever the model claimed
    assert 'difficulty = "easy"' in (task / "task.toml").read_text()
    prompt = backend.prompts[0]
    assert "backend/app/config.py::Settings (settings-class)" in prompt
    assert "{{" not in prompt
    # a whole task does not fit the protocol's 8k default
    assert backend.max_tokens > 8192
    log = [json.loads(x) for x in (tmp_path / "work/generate-log.jsonl").read_text().splitlines()]
    assert log[0]["accepted"] is True and log[0]["attempt"] == 1


def test_retry_feeds_failure_back_then_rejects(target: Target, tmp_path: Path) -> None:
    patch = good_patch(target)
    backend = FakeBackend(answer(patch), answer(patch))
    reports = run(target, tmp_path, backend, FakeValidator(False, False), max_pairs=1)
    assert [r.accepted for r in reports] == [False]
    assert "tests passed on base" in backend.prompts[1]
    assert not any((tmp_path / "tasks" / "fixture").iterdir())
    (rejected,) = (tmp_path / "work" / "rejected" / "fixture").iterdir()
    assert (rejected / "validation.json").exists()


def test_bad_patch_and_backend_errors_are_rejections(target: Target, tmp_path: Path) -> None:
    patch = good_patch(target)
    no_fault = {**answer(patch), "feature_tests": {"test_a.py": "def test_ok():\n    pass\n"}}
    backend = FakeBackend(
        answer("--- a/nope.py\n+++ b/nope.py\n@@ -1 +1 @@\n-a\n+b\n"),
        RuntimeError("backend down"),
        no_fault,
        {k: v for k, v in answer(patch).items() if k != "instruction"},
    )
    reports = run(target, tmp_path, backend, FakeValidator(), n=2, max_pairs=2)
    gates = [r.gates[0].gate for r in reports]
    assert gates == ["generator", "spec_schema"]
    log = [json.loads(x) for x in (tmp_path / "work/generate-log.jsonl").read_text().splitlines()]
    assert [r["failed_gates"] for r in log] == [["patch_apply"], ["generator"], ["patch_apply"], ["spec_schema"]]


def test_dedupe_across_runs_and_existing_titles(target: Target, tmp_path: Path) -> None:
    patch = good_patch(target)
    run(target, tmp_path, FakeBackend(answer(patch, "first")), FakeValidator(True))
    backend = FakeBackend(answer(patch, "second"))
    run(target, tmp_path, backend, FakeValidator(True))
    # second run must pick a different surface for the same family and number the task 002
    assert "Settings (settings-class)" not in backend.prompts[0]
    # the sibling surface in the same file is told what the first task already covers
    assert "- first" in backend.prompts[0]
    names = sorted(p.name for p in (tmp_path / "tasks" / "fixture").iterdir())
    assert names[0].startswith("ff-001-") and names[1].startswith("ff-002-")


def test_empty_patch_rejected(target: Target, tmp_path: Path) -> None:
    gen_mod.checkout(target, tmp_path / "work")
    reports = run(target, tmp_path, FakeBackend(answer("")), FakeValidator(), max_pairs=1)
    assert reports[0].accepted is False


def test_family_language_filter(target: Target, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fam = load_family("fail-fast-config").model_copy(update={"languages": ["go"]})
    monkeypatch.setattr(gen_mod, "load_family", lambda _s: fam)
    assert run(target, tmp_path, FakeBackend(), FakeValidator()) == []


def test_helpers(tmp_path: Path) -> None:
    assert slugify("Fail Fast: on SMTP host!") == "fail-fast-on-smtp"
    assert slugify("!!!") == "task"
    one = "diff --git a/x b/x\n"
    assert difficulty(one, 2) == "easy"
    assert difficulty(one * 2, 2) == "medium"
    assert difficulty(one * 3, 1) == "hard"
    assert difficulty(one, 4) == "hard"
    report = ValidationReport(task_id="t", accepted=False, gates=[], mutants_total=4, mutants_killed=0)
    text = describe_failure(report)
    assert "without a failing gate" in text and "0 of 4 mutants" in text
    assert gold_example(tmp_path, Target.model_construct(name="none")) == "none"


def test_gold_example_reads_hand_written(tmp_path: Path) -> None:
    d = tmp_path / "t" / "ff-001-x"
    (d / "solution").mkdir(parents=True)
    (d / "tests" / "feature" / "tests").mkdir(parents=True)
    (d / "task.toml").write_text('[metadata]\norigin = "hand-written"\n')
    (d / "instruction.md").write_text("do it\n\n---\n\nfooter")
    (d / "solution" / "reference.patch").write_text("diff\n")
    (d / "tests" / "feature" / "tests" / "test_a.py").write_text("def test_a(): pass\n")
    (tmp_path / "t" / "other").mkdir()
    text = gold_example(tmp_path, Target.model_construct(name="t"))
    assert "do it" in text and "footer" not in text and "tests/test_a.py" in text


def test_plan_pairs_round_robin() -> None:
    a = load_family("fail-fast-config")
    b = load_family("cross-field-validation")
    s1 = Surface(file="c.py", symbol="S", kind="settings-class")
    s2 = Surface(file="m.py", symbol="M", kind="validator")
    pairs = [(f.slug, s.symbol) for f, s in plan_pairs([a, b], [s1, s2], set())]
    assert pairs == [("fail-fast-config", "S"), ("cross-field-validation", "S"), ("cross-field-validation", "M")]


def test_cli_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from incidentforge import cli

    seen: dict[str, Any] = {}

    def fake_generate(tgt: Target, slugs: list[str], n: int, backend: Any, **kw: Any) -> list[ValidationReport]:
        seen.update(slugs=slugs, n=n, backend=backend.name)
        return [ValidationReport(task_id="x", accepted=True, gates=[])]

    monkeypatch.setattr("incidentforge.generate.generate", fake_generate)
    res = CliRunner().invoke(cli.app, ["run", "--n", "1", "--out", str(tmp_path)])
    assert res.exit_code == 0, res.output
    assert seen["backend"] == "claude-code" and len(seen["slugs"]) == len(set(seen["slugs"]))
    res = CliRunner().invoke(cli.app, ["run", "--n", "2", "--family", "fail-fast-config", "--out", str(tmp_path)])
    assert res.exit_code == 1 and "only 1/2" in res.output


@pytest.mark.parametrize(
    ("gate", "agent", "log"),
    [
        ("fail_on_base", "nop", "feature_tests.log"),
        ("regression", "oracle", "repo_suite.log"),
        ("pass_on_reference", "oracle", "feature_tests.log"),
    ],
)
def test_verifier_excerpt(tmp_path: Path, gate: str, agent: str, log: str) -> None:
    from incidentforge.generate import verifier_excerpt

    d = tmp_path / f"t--ff-001-x-{agent}-20261118/trial1/verifier"
    d.mkdir(parents=True)
    (d / log).write_text("\n".join(f"line {i}" for i in range(100)))
    report = ValidationReport(task_id="t/ff-001-x", accepted=False, gates=[GateResult(gate=gate, passed=False)])
    text = verifier_excerpt(tmp_path, "t/ff-001-x", report)
    assert "line 99" in text and "line 39" not in text and agent in text


def test_verifier_excerpt_none(tmp_path: Path) -> None:
    from incidentforge.generate import verifier_excerpt

    leak = ValidationReport(task_id="t/x", accepted=False, gates=[GateResult(gate="leak", passed=False)])
    assert verifier_excerpt(tmp_path, "t/x", leak) == ""
    nop = ValidationReport(task_id="t/x", accepted=False, gates=[GateResult(gate="fail_on_base", passed=False)])
    assert verifier_excerpt(tmp_path, "t/x", nop) == ""


def test_stray_untracked_files_stay_out_of_patch(target: Target, tmp_path: Path) -> None:
    patch = good_patch(target)
    repo = gen_mod.checkout(target, tmp_path / "work")
    (repo / ".pre-commit-config.yaml").write_text("repos: []\n")
    run(target, tmp_path, FakeBackend(answer(patch)), FakeValidator(True))
    (task,) = (tmp_path / "tasks" / "fixture").iterdir()
    text = (task / "solution" / "reference.patch").read_text()
    assert "pre-commit" not in text and "STRICT" in text


def test_family_titles_include_gold_and_skip_other_families(target: Target, tmp_path: Path) -> None:
    from incidentforge.generate import family_titles

    rows = [("ff-001-gold", "fail-fast-config", "gold title"), ("cf-001-x", "cross-field-validation", "other")]
    for name, fam, title in rows:
        d = tmp_path / "tasks" / "fixture" / name
        d.mkdir(parents=True)
        (d / "task.toml").write_text(f'[metadata]\nfamily = "{fam}"\ntitle = "{title}"\n')
    assert family_titles(tmp_path / "tasks", "fixture", "fail-fast-config") == ["gold title"]
    assert family_titles(tmp_path / "nowhere", "fixture", "fail-fast-config") == []
    backend = FakeBackend(answer(good_patch(target)))
    run(target, tmp_path, backend, FakeValidator(True))
    assert "- gold title" in backend.prompts[0] and "- other" not in backend.prompts[0]
