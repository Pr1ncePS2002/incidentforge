"""exact gate wiring (paths, job names, harbor args, details); written to kill surviving mutmut mutants."""

import itertools
import json
import re
from pathlib import Path
from typing import Any

import pytest
from test_validate import BASE_SRC, FakeRunner, _task

from incidentforge import validate as v
from incidentforge.harbor import Trial
from incidentforge.validate import mutation

STAMP = r"\d{8}-\d{6}"


class Recorder(FakeRunner):
    """fake runner that also keeps task paths and snapshots mutant patches as harbor would see them."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.paths: list[Path] = []
        self.mutant_patches: dict[str, str] = {}

    def __call__(self, task_path: Path, agent: str, job_name: str, extra_args: list[str]) -> list[Trial]:
        self.paths.append(task_path)
        if "-mutation-" in job_name:
            for d in sorted(task_path.iterdir()):
                self.mutant_patches[d.name] = (d / "solution" / "reference.patch").read_text()
        trials: list[Trial] = super().__call__(task_path, agent, job_name, extra_args)
        return trials


@pytest.fixture
def targets(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    seen: list[Any] = []

    def load(name: str) -> str:
        seen.append(("load", name))
        return f"target:{name}"

    def files(target: str, fps: list[mutation.FilePatch]) -> dict[str, str]:
        seen.append(("base", target))
        return {f.path: BASE_SRC for f in fps}

    monkeypatch.setattr(v, "load_target", load)
    monkeypatch.setattr(v, "base_files", files)
    return seen


def _run(task: Path, tmp_path: Path, runner: Any, gates: tuple[str, ...] = v.GATES) -> Any:
    return v.validate_task(task, gates, jobs_dir=tmp_path / "jobs", reports_dir=tmp_path / "reports", runner=runner)


def test_every_gate_gets_the_right_task_job_and_args(tmp_path: Path, targets: list[Any]) -> None:
    task = _task(tmp_path)
    rec = Recorder()
    r = _run(task, tmp_path, rec)
    assert r.accepted
    agents = [(a, re.sub(STAMP, "S", j), x) for a, j, x in rec.calls]
    assert agents == [
        ("nop", "demo--ff-001-x-nop-S", []),
        ("oracle", "demo--ff-001-x-oracle-S", []),
        ("oracle", "demo--ff-001-x-mutation-S", ["-n", "4"]),
        ("oracle", "demo--ff-001-x-flaky-S", ["-k", "2", "-n", "2"]),
    ]
    mutants_root = tmp_path.resolve() / "jobs" / re.sub("mutation", "mutants", rec.calls[2][1])
    assert rec.paths == [task.resolve(), task.resolve(), mutants_root, task.resolve()]
    names = sorted(rec.mutant_patches)
    assert names == [f"ff-001-x-m{i:02d}" for i in range(1, len(names) + 1)]
    original = (task / "solution" / "reference.patch").read_text()
    assert all(p != original and p.startswith("diff --git") for p in rec.mutant_patches.values())
    assert targets == [("load", "demo"), ("base", "target:demo")]


def test_fail_on_base_detail_lists_each_reward(tmp_path: Path, targets: list[Any]) -> None:
    r = _run(_task(tmp_path), tmp_path, FakeRunner(nop={"reward": 1, "feature_tests": 1, "repo_suite": 1}))
    assert r.gates[-1].detail == "reward=1.0 feature_tests=1.0 repo_suite=1.0"


def test_one_trial_errors_carry_their_reason(tmp_path: Path) -> None:
    def two(*a: Any) -> list[Trial]:
        return [Trial("x", "a", tmp_path, {"reward": 1.0}), Trial("x", "b", tmp_path, {"reward": 1.0})]

    def errored(*a: Any) -> list[Trial]:
        return [Trial("x", "a", tmp_path, {}, error="boom")]

    r = _run(_task(tmp_path), tmp_path, two, gates=("pass_on_reference",))
    assert r.gates[0].detail == "RuntimeError: expected 1 trial, got 2"
    r = _run(_task(tmp_path / "e"), tmp_path, errored, gates=("pass_on_reference",))
    assert r.gates[0].detail == "RuntimeError: trial errored: boom"


def _ctrf_runner(tmp_path: Path, ctrf: Any, suite_reward: int) -> Any:
    trial_dir = tmp_path / "trial"
    (trial_dir / "verifier").mkdir(parents=True)
    if ctrf is not None:
        (trial_dir / "verifier" / "ctrf.json").write_text(json.dumps(ctrf))

    def run(*a: Any) -> list[Trial]:
        return [Trial("x", "x__1", trial_dir, {"reward": 1.0, "feature_tests": 1.0, "repo_suite": float(suite_reward)})]

    return run


@pytest.mark.parametrize(
    ("ctrf", "suite_reward", "passed"),
    [
        ({"results": {"tests": [{"name": "repo_suite", "status": "passed"}]}}, 0, True),
        ({"results": {"tests": [{"name": "repo_suite", "status": "failed"}]}}, 1, False),
        ({"results": {"tests": [{"name": "feature_tests", "status": "passed"}]}}, 1, False),
        ({"results": {}}, 1, False),
        ({}, 1, False),
        (None, 1, True),
        (None, 0, False),
    ],
)
def test_regression_trusts_ctrf_then_falls_back_to_rewards(
    tmp_path: Path, ctrf: Any, suite_reward: int, passed: bool
) -> None:
    r = _run(_task(tmp_path), tmp_path, _ctrf_runner(tmp_path, ctrf, suite_reward), gates=("regression",))
    word = "passed" if passed else "failed"
    assert r.gates[0].passed is passed
    assert r.gates[0].detail == f"repo suite {word} with the reference patch"


def test_mutation_gate_without_metadata_crashes_with_a_key_error(tmp_path: Path, targets: list[Any]) -> None:
    task = _task(tmp_path)
    (task / "task.toml").write_text('schema_version = "1.4"\n')
    r = _run(task, tmp_path, FakeRunner(), gates=("mutation",))
    assert r.gates[0].detail == "KeyError: 'target'"


def test_mutation_gate_rejects_when_no_mutants(
    tmp_path: Path, targets: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(v, "make_mutants", lambda patch, base: [])
    r = _run(_task(tmp_path), tmp_path, FakeRunner(), gates=("mutation",))
    assert (r.gates[0].passed, r.gates[0].detail) == (False, "no mutants could be generated from the reference patch")


def test_mutation_detail_names_survivors_and_errored(
    tmp_path: Path, targets: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    ms = [
        mutation.Mutant(op, "pkg/cfg.py", n, f"diff --git {op}\n") for op, n in (("a", 1), ("b", 2), ("c", 3), ("d", 4))
    ]
    monkeypatch.setattr(v, "make_mutants", lambda patch, base: ms)

    def run(task_path: Path, agent: str, job_name: str, extra_args: list[str]) -> list[Trial]:
        return [
            Trial("ff-001-x-m01", "1", task_path, {"reward": 0.0}),
            Trial("ff-001-x-m02", "2", task_path, {"reward": 1.0}),
            Trial("ff-001-x-m03", "3", task_path, {"reward": 0.0}, error="docker"),
        ]

    r = _run(_task(tmp_path), tmp_path, run, gates=("mutation",))
    assert r.gates[0].detail == "killed 1/4; survived: b@pkg/cfg.py:2; errored: c@pkg/cfg.py:3, d@pkg/cfg.py:4"
    assert (r.mutants_total, r.mutants_killed) == (4, 1)


def test_mutation_detail_with_no_survivors(tmp_path: Path, targets: list[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    ms = [mutation.Mutant("a", "f.py", 1, "p\n")]
    monkeypatch.setattr(v, "make_mutants", lambda patch, base: ms)
    r = _run(_task(tmp_path), tmp_path, FakeRunner(), gates=("mutation",))
    assert r.gates[0].detail == "killed 1/1; survived: -"


def test_mutation_detail_joins_several_survivors(
    tmp_path: Path, targets: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    ms = [mutation.Mutant(op, "f.py", n, "p\n") for op, n in (("a", 1), ("b", 2), ("c", 3))]
    monkeypatch.setattr(v, "make_mutants", lambda patch, base: ms)
    r = _run(_task(tmp_path), tmp_path, FakeRunner(survivors={"ff-001-x-m02", "ff-001-x-m03"}), gates=("mutation",))
    assert r.gates[0].detail == "killed 1/3; survived: b@f.py:2, c@f.py:3"


def test_unknown_gate_message(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=re.escape("unknown gates: ['nope']")):
        v.validate_task(tmp_path, ("nope",))


def test_default_runner_goes_through_harbor_with_the_jobs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []

    def run_job(task_path: Path, agent: str, job_name: str, jobs_dir: Path, extra_args: list[str]) -> Path:
        calls.append((task_path, agent, job_name, jobs_dir, extra_args))
        return tmp_path / "jobdir"

    monkeypatch.setattr(v.harbor, "run_job", run_job)
    monkeypatch.setattr(
        v.harbor, "read_trials", lambda d: [Trial("x", "x", d, {"reward": 1.0})] if d == tmp_path / "jobdir" else []
    )
    task = _task(tmp_path)
    r = v.validate_task(task, ("pass_on_reference",), jobs_dir=tmp_path / "jobs", reports_dir=tmp_path / "reports")
    assert r.accepted
    [(path, agent, job, jobs, extra)] = calls
    assert (path, agent, jobs, extra) == (task.resolve(), "oracle", (tmp_path / "jobs").resolve(), [])
    assert re.fullmatch(rf"demo--ff-001-x-oracle-{STAMP}", job)


def test_harbor_runner_passes_every_argument(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []
    monkeypatch.setattr(v.harbor, "run_job", lambda *a, **k: seen.append((a, k)) or tmp_path / "j")
    monkeypatch.setattr(v.harbor, "read_trials", lambda d: [Trial("x", "x", d)])
    [t] = v.harbor_runner(tmp_path / "jobs")(tmp_path / "t", "nop", "job", ["-n", "2"])
    assert seen == [((tmp_path / "t", "nop", "job", tmp_path / "jobs"), {"extra_args": ["-n", "2"]})]
    assert t.path == tmp_path / "j"


def test_gate_crash_detail_is_typed_and_capped(tmp_path: Path) -> None:
    def boom(*a: Any) -> list[Trial]:
        raise OSError("x" * 3000)

    r = _run(_task(tmp_path), tmp_path, boom, gates=("pass_on_reference",))
    assert r.gates[0].detail.startswith("OSError: xxx") and len(r.gates[0].detail) == 1000


def test_gate_seconds_are_rounded_wall_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = itertools.cycle([100.0, 100.26])
    monkeypatch.setattr(v.time, "monotonic", lambda: next(ticks))
    r = _run(_task(tmp_path), tmp_path, FakeRunner(), gates=("leak",))
    assert r.gates[0].seconds == 0.3


def test_report_is_saved_indented_with_the_jobs_dir(tmp_path: Path, targets: list[Any]) -> None:
    r = _run(_task(tmp_path), tmp_path, FakeRunner(), gates=("leak",))
    assert r.log_path == str((tmp_path / "jobs").resolve())
    saved = (tmp_path / "reports" / "demo" / "ff-001-x.json").read_text()
    assert saved == r.model_dump_json(indent=2) + "\n"


def test_display_is_relative_inside_cwd_only(tmp_path: Path) -> None:
    assert v._display(Path.cwd() / "jobs" / "x") == str(Path("jobs") / "x")
    assert v._display(tmp_path) == str(tmp_path)


def test_find_task_dirs_collects_across_paths(tmp_path: Path) -> None:
    a = _task(tmp_path / "a")
    b = _task(tmp_path / "b")
    assert v.find_task_dirs([a, tmp_path / "b" / "tasks"]) == [a, b]
    assert v.find_task_dirs([tmp_path / "a" / "tasks", tmp_path / "b" / "tasks"]) == [a, b]
