"""eval runner against a fake harbor wrapper: routing, cap stop, resume."""

import json
from pathlib import Path

import pytest

from incidentforge import evaluate
from incidentforge.budget import Ledger
from incidentforge.evaluate import (
    Limits,
    ResultsStore,
    RunRequest,
    discover_tasks,
    key_env,
    pick_subset,
    read_trials,
    route,
    run_eval,
)

ENV = {"GEMINI_API_KEY": "free-k", "GEMINI_API_KEY2": "paid-k", "PATH": "/bin"}


def make_task(root: Path, target: str, name: str, family: str) -> None:
    d = root / target / name
    (d / "tests").mkdir(parents=True)
    (d / "task.toml").write_text(
        f'version = "1.0"\n[metadata]\nfamily = "{family}"\ndifficulty = "easy"\ntarget = "{target}"\n'
        'fault_cases = ["smtp host without from"]\n'
    )
    (d / "instruction.md").write_text(f"do {name}")
    (d / "tests" / "test.sh").write_text("#!/bin/sh\n")
    (d / "tests" / f"test_{name.replace('-', '_')}.py").write_text("")


@pytest.fixture
def tasks_root(tmp_path: Path) -> Path:
    root = tmp_path / "tasks"
    make_task(root, "fastapi-template", "ff-001", "fail-fast-config")
    make_task(root, "fastapi-template", "ff-002", "fail-fast-config")
    make_task(root, "fastapi-template", "cf-001", "cross-field-validation")
    make_task(root, "go-svc", "hr-001", "hot-reload-config")
    return root


class FakeHarbor:
    """writes trial result.json files the way harbor does; passes tasks whose name is in `passing`."""

    def __init__(self, tmp: Path, passing: set[str] | None = None, tokens: tuple[int, int] = (1000, 200)):
        self.tmp = tmp
        self.passing = passing or set()
        self.tokens = tokens
        self.requests: list[RunRequest] = []
        self.errored: set[str] = set()

    def __call__(self, req: RunRequest) -> Path:
        self.requests.append(req)
        job = req.jobs_dir / req.job_name
        for i, name in enumerate(req.task_names):
            trial = job / f"{name}__{i}"
            (trial / "verifier").mkdir(parents=True)
            ok = name in self.passing
            data: dict[str, object] = {
                "task_name": name,
                "trial_name": trial.name,
                "agent_result": {"n_input_tokens": self.tokens[0], "n_output_tokens": self.tokens[1]},
                "verifier_result": None if name in self.errored else {"rewards": {"reward": 1.0 if ok else 0.0}},
                "exception_info": {"exception_type": "RateLimitError"} if name in self.errored else None,
            }
            (trial / "result.json").write_text(json.dumps(data))
            tests = [{"name": "test_fault_missing_from", "status": "passed" if ok else "failed"}]
            (trial / "verifier" / "ctrf.json").write_text(json.dumps({"results": {"tests": tests}}))
            (trial / "verifier" / "reward.json").write_text(
                json.dumps({"reward": 1.0 if ok else 0.0, "feature_tests": float(ok), "repo_suite": 1.0})
            )
        return job


def run(tasks_root: Path, tmp: Path, harbor: FakeHarbor, models: list[str], **kw: object) -> list:
    ledger = kw.pop("ledger", None) or Ledger(tmp / "ledger.jsonl", cap=70.0)
    return run_eval(
        tasks_root,
        models,
        runner=harbor,
        ledger=ledger,  # type: ignore[arg-type]
        results_path=tmp / "reports/eval/results.jsonl",
        jobs_dir=tmp / "jobs",
        env=ENV,
        echo=lambda s: None,
        **kw,  # type: ignore[arg-type]
    )


def test_discover_reads_metadata_and_feature_tests(tasks_root: Path) -> None:
    tasks = {t.task_id: t for t in discover_tasks(tasks_root)}
    assert set(tasks) == {
        "fastapi-template/ff-001",
        "fastapi-template/ff-002",
        "fastapi-template/cf-001",
        "go-svc/hr-001",
    }
    t = tasks["fastapi-template/ff-001"]
    assert t.family == "fail-fast-config" and t.name == "ff-001" and t.difficulty == "easy"
    assert t.feature_tests == ("test_ff_001.py",) and t.fault_cases == ("smtp host without from",)


def test_route_picks_the_right_key() -> None:
    assert route("gemini/gemini-3.8-flash", "terminus-2") == "free"
    assert route("gemini/gemini-4-hydrogen", "terminus-2") == "free"
    assert route("gemini/gemini-2.5-pro", "terminus-2") == "paid"
    assert route("anything", "claude-code") == "subscription"


def test_key_env_exposes_exactly_one_gemini_key() -> None:
    free = key_env("free", ENV)
    assert free["GEMINI_API_KEY"] == "free-k" and "GEMINI_API_KEY2" not in free
    paid = key_env("paid", ENV)
    assert paid["GEMINI_API_KEY"] == "paid-k" and "GEMINI_API_KEY2" not in paid
    sub = key_env("subscription", ENV)
    assert not any(k.startswith("GEMINI") for k in sub) and sub["PATH"] == "/bin"
    with pytest.raises(RuntimeError):
        key_env("paid", {"GEMINI_API_KEY": "x"})
    with pytest.raises(RuntimeError):
        key_env("free", {})


def test_free_model_runs_with_free_key_and_records_results(tasks_root: Path, tmp_path: Path) -> None:
    h = FakeHarbor(tmp_path, passing={"ff-001"})
    new = run(tasks_root, tmp_path, h, ["gemini/gemini-3.8-flash"])
    assert len(new) == 4 and all(r.key == "free" and r.cost_usd == 0 for r in new)
    assert all(r.env["GEMINI_API_KEY"] == "free-k" for r in h.requests)
    # one job per dataset dir, filtered to the batch's task names
    assert sorted(r.dataset.name for r in h.requests) == ["fastapi-template", "go-svc"]
    assert {r.task_id: r.reward for r in new}["fastapi-template/ff-001"] == 1.0
    assert not (tmp_path / "ledger.jsonl").exists()
    side = [json.loads(x) for x in (tmp_path / "reports/eval/trials.jsonl").read_text().splitlines()]
    assert side[0]["parts"]["repo_suite"] == 1.0
    assert any(s["failed_tests"] == ["test_fault_missing_from"] for s in side)


def test_resume_skips_done_runs(tasks_root: Path, tmp_path: Path) -> None:
    h = FakeHarbor(tmp_path)
    run(tasks_root, tmp_path, h, ["gemini/gemini-3.8-flash"])
    first = len(h.requests)
    assert run(tasks_root, tmp_path, h, ["gemini/gemini-3.8-flash"]) == []
    assert len(h.requests) == first
    # k=2 only schedules the second attempt
    new = run(tasks_root, tmp_path, h, ["gemini/gemini-3.8-flash"], k=2)
    assert len(new) == 4 and {r.attempt for r in new} == {2}


def test_errored_trials_are_not_recorded_so_they_retry(tasks_root: Path, tmp_path: Path) -> None:
    h = FakeHarbor(tmp_path)
    h.errored = {"cf-001"}
    new = run(tasks_root, tmp_path, h, ["gemini/gemini-3.8-flash"])
    assert "fastapi-template/cf-001" not in {r.task_id for r in new}
    h.errored = set()
    again = run(tasks_root, tmp_path, h, ["gemini/gemini-3.8-flash"])
    assert [r.task_id for r in again] == ["fastapi-template/cf-001"]


def test_paid_model_is_metered_and_cap_stops_scheduling(tasks_root: Path, tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl", cap=70.0)
    limits = Limits(max_turns=10, max_input_per_turn=100_000, max_output_per_turn=8_000)
    # worst case per trial for 2.5-pro: 1M in * 2.5 + 80k out * 15 = $3.70; batch of 2 = $7.40
    ledger.record("gemini-2.5-pro", 0, 4_200_000)  # $63 spent, $7 left
    h = FakeHarbor(tmp_path, tokens=(1_000_000, 80_000))
    new = run(tasks_root, tmp_path, h, ["gemini/gemini-2.5-pro"], ledger=ledger, limits=limits, batch_size=2)
    assert new == [] and h.requests == []
    # the first batch spends its full worst case, so the second no longer fits
    ledger2 = Ledger(tmp_path / "ledger2.jsonl", cap=10.0)
    new = run(tasks_root, tmp_path, h, ["gemini/gemini-2.5-pro"], ledger=ledger2, limits=limits, batch_size=2)
    assert len(h.requests) == 1 and len(new) == 2
    assert all(r.key == "paid" and r.cost_usd > 0 for r in new)
    assert h.requests[0].env["GEMINI_API_KEY"] == "paid-k"
    assert ledger2.spent() == pytest.approx(sum(r.cost_usd for r in new), rel=1e-3)
    assert "--ak" in h.requests[0].extra_args and "max_turns=10" in h.requests[0].extra_args


def test_free_models_still_run_when_paid_is_blocked(tasks_root: Path, tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl", cap=0.01)
    h = FakeHarbor(tmp_path)
    new = run(tasks_root, tmp_path, h, ["gemini/gemini-2.5-pro", "gemini/gemini-3.8-flash"], ledger=ledger)
    assert {r.model for r in new} == {"gemini/gemini-3.8-flash"}


def test_subset_is_seeded_and_covers_every_family(tasks_root: Path, tmp_path: Path) -> None:
    tasks = discover_tasks(tasks_root)
    a = pick_subset(tasks, n=3)
    assert a == pick_subset(tasks, n=3) and len(a) == 3
    fams = {t.family for t in tasks if t.task_id in a}
    assert fams == {"fail-fast-config", "cross-field-validation", "hot-reload-config"}
    assert len(pick_subset(tasks, n=10)) == 4
    h = FakeHarbor(tmp_path)
    new = run(tasks_root, tmp_path, h, ["gemini/gemini-3.8-flash"], subset=a[:1], k=3)
    assert len(new) == 3 and {r.attempt for r in new} == {1, 2, 3}


def test_subscription_agent_passes_no_model_args(tasks_root: Path, tmp_path: Path) -> None:
    h = FakeHarbor(tmp_path)
    new = run(tasks_root, tmp_path, h, ["claude-sonnet"], agent="claude-code", subset=["go-svc/hr-001"])
    assert new[0].key == "subscription" and "--ak" not in h.requests[0].extra_args


def test_read_trials_handles_missing_pieces(tmp_path: Path) -> None:
    trial = tmp_path / "job" / "t__1"
    (trial / "verifier").mkdir(parents=True)
    (trial / "result.json").write_text(json.dumps({"verifier_result": {"rewards": {"reward": 1}}}))
    (trial / "verifier" / "ctrf.json").write_text("not json")
    (trial / "verifier" / "reward.json").write_text("[]")
    [tr] = read_trials(tmp_path / "job")
    assert tr.task_name == "t" and tr.reward == 1.0 and tr.failed_tests == () and tr.parts == ()


def test_results_store_roundtrip(tmp_path: Path) -> None:
    store = ResultsStore(tmp_path / "r.jsonl")
    assert store.load() == [] and store.done() == set()


def test_harbor_runner_forwards_env_and_filters(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def fake_run_job(**kw: object) -> Path:
        seen.update(kw)
        return tmp_path

    monkeypatch.setattr("incidentforge.harbor.run_job", fake_run_job)
    req = RunRequest(
        tmp_path, "terminus-2", "gemini/x", "j", tmp_path, ("a", "b"), ("-k", "1"), {"GEMINI_API_KEY": "sekret"}
    )
    assert evaluate.harbor_runner(req) == tmp_path
    assert seen["extra_args"] == ["-k", "1", "-i", "a", "-i", "b"]
    assert seen["env"] == {"GEMINI_API_KEY": "sekret"} and seen["model"] == "gemini/x"
    assert "sekret" not in repr(req)


class FailingHarbor(FakeHarbor):
    """writes the trials, then fails like harbor exiting non-zero."""

    def __init__(self, tmp: Path, write: bool) -> None:
        super().__init__(tmp, passing={"ff-001", "ff-002", "cf-001", "hr-001"})
        self.write = write

    def __call__(self, req: RunRequest) -> Path:
        if self.write:
            super().__call__(req)
        else:
            self.requests.append(req)
        raise RuntimeError("harbor run exited 1")


def test_failed_free_job_keeps_written_trials_and_continues(tasks_root: Path, tmp_path: Path) -> None:
    h = FailingHarbor(tmp_path, write=True)
    new = run(tasks_root, tmp_path, h, ["gemini/gemini-3.8-flash"])
    assert len(new) == 4 and len(h.requests) == 2


def test_failed_paid_job_blocks_the_model(tasks_root: Path, tmp_path: Path) -> None:
    h = FailingHarbor(tmp_path, write=False)
    new = run(tasks_root, tmp_path, h, ["gemini/gemini-2.5-pro"], batch_size=1)
    assert new == [] and len(h.requests) == 1
