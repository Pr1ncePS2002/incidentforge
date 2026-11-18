"""validation gates for a harbor task directory. owner: phase 1."""

from __future__ import annotations

import json
import shutil
import time
import tomllib
from collections.abc import Callable
from pathlib import Path

from incidentforge import harbor
from incidentforge.harbor import Trial
from incidentforge.models import GateResult, ValidationReport
from incidentforge.targets import load_target
from incidentforge.validate.leak import check_leak
from incidentforge.validate.mutation import base_files, make_mutants, parse_patch

GATES = ("fail_on_base", "pass_on_reference", "regression", "mutation", "leak", "flakiness")
# cheapest first; the first failing gate stops the run
ORDER = ("leak", "fail_on_base", "pass_on_reference", "regression", "mutation", "flakiness")
MAX_CONCURRENT = 4
FLAKY_RUNS = 3

# (task_path, agent, job_name, extra_args) -> trials
Runner = Callable[[Path, str, str, list[str]], list[Trial]]


def harbor_runner(jobs_dir: Path) -> Runner:
    def run(task_path: Path, agent: str, job_name: str, extra_args: list[str]) -> list[Trial]:
        return harbor.read_trials(harbor.run_job(task_path, agent, job_name, jobs_dir, extra_args=extra_args))

    return run


def task_id_of(task_dir: Path) -> str:
    return f"{task_dir.parent.name}/{task_dir.name}"


class _Ctx:
    """per-task state shared between gates so the oracle run is reused."""

    def __init__(self, task_dir: Path, run: Runner, work_dir: Path) -> None:
        self.task_dir, self.run, self.work_dir = task_dir, run, work_dir
        self.slug = task_id_of(task_dir).replace("/", "--")
        self.stamp = time.strftime("%Y%m%d-%H%M%S")
        self.oracle: list[Trial] | None = None
        self.mutants_total = self.mutants_killed = 0

    def job(self, gate: str) -> str:
        return f"{self.slug}-{gate}-{self.stamp}"

    def oracle_trials(self) -> list[Trial]:
        if self.oracle is None:
            self.oracle = self.run(self.task_dir, "oracle", self.job("oracle"), [])
        return self.oracle


def _one(trials: list[Trial]) -> Trial:
    if len(trials) != 1:
        raise RuntimeError(f"expected 1 trial, got {len(trials)}")
    t = trials[0]
    if t.error:
        raise RuntimeError(f"trial errored: {t.error}")
    return t


def gate_leak(ctx: _Ctx) -> tuple[bool, str]:
    instruction = (ctx.task_dir / "instruction.md").read_text()
    return check_leak(instruction, (ctx.task_dir / "solution" / "reference.patch").read_text())


def gate_fail_on_base(ctx: _Ctx) -> tuple[bool, str]:
    t = _one(ctx.run(ctx.task_dir, "nop", ctx.job("nop"), []))
    r = t.rewards
    detail = f"reward={r.get('reward')} feature_tests={r.get('feature_tests')} repo_suite={r.get('repo_suite')}"
    # the feature tests must be what fails; a broken repo suite on base means a bad env, not a good task
    return r.get("reward") == 0 and r.get("feature_tests") == 0 and r.get("repo_suite") == 1, detail


def gate_pass_on_reference(ctx: _Ctx) -> tuple[bool, str]:
    t = _one(ctx.oracle_trials())
    return t.reward == 1, f"reward={t.reward}"


def _suite_from_ctrf(trial: Trial) -> bool | None:
    ctrf = trial.path / "verifier" / "ctrf.json"
    if not ctrf.exists():
        return None
    tests = json.loads(ctrf.read_text()).get("results", {}).get("tests", [])
    return any(t.get("name") == "repo_suite" and t.get("status") == "passed" for t in tests)


def gate_regression(ctx: _Ctx) -> tuple[bool, str]:
    t = _one(ctx.oracle_trials())
    ok = _suite_from_ctrf(t)
    if ok is None:
        ok = t.rewards.get("repo_suite") == 1
    return ok, "repo suite passed with the reference patch" if ok else "repo suite failed with the reference patch"


def gate_mutation(ctx: _Ctx) -> tuple[bool, str]:
    meta = tomllib.loads((ctx.task_dir / "task.toml").read_text()).get("metadata", {})
    patch = (ctx.task_dir / "solution" / "reference.patch").read_text()
    mutants = make_mutants(patch, base_files(load_target(meta["target"]), parse_patch(patch)))
    if not mutants:
        return False, "no mutants could be generated from the reference patch"
    root = ctx.work_dir / ctx.job("mutants")
    names = {}
    for i, m in enumerate(mutants, 1):
        name = f"{ctx.task_dir.name}-m{i:02d}"
        names[name] = m
        shutil.copytree(ctx.task_dir, root / name)
        (root / name / "solution" / "reference.patch").write_text(m.patch)
    trials = ctx.run(root, "oracle", ctx.job("mutation"), ["-n", str(MAX_CONCURRENT)])
    by_name = {t.task_name: t for t in trials}
    killed, survived, errored = [], [], []
    for name, m in names.items():
        t = by_name.get(name)
        label = f"{m.op}@{m.file}:{m.line}"
        if t is None or t.error:
            errored.append(label)
        elif t.reward == 1:
            survived.append(label)
        else:
            killed.append(label)
    ctx.mutants_total, ctx.mutants_killed = len(mutants), len(killed)
    detail = f"killed {len(killed)}/{len(mutants)}; survived: {', '.join(survived) or '-'}"
    if errored:
        detail += f"; errored: {', '.join(errored)}"
    return len(killed) >= 1, detail


def gate_flakiness(ctx: _Ctx) -> tuple[bool, str]:
    first = [t.reward for t in ctx.oracle_trials()]
    more = ctx.run(ctx.task_dir, "oracle", ctx.job("flaky"), ["-k", str(FLAKY_RUNS - 1), "-n", str(FLAKY_RUNS - 1)])
    rewards = first + [t.reward for t in more]
    return len(rewards) == FLAKY_RUNS and len(set(rewards)) == 1, f"oracle rewards over {len(rewards)} runs: {rewards}"


GATE_FNS: dict[str, Callable[[_Ctx], tuple[bool, str]]] = {
    "leak": gate_leak,
    "fail_on_base": gate_fail_on_base,
    "pass_on_reference": gate_pass_on_reference,
    "regression": gate_regression,
    "mutation": gate_mutation,
    "flakiness": gate_flakiness,
}


def validate_task(
    task_dir: Path,
    gates: tuple[str, ...] = GATES,
    *,
    jobs_dir: Path = Path("jobs/validation"),
    reports_dir: Path = Path("reports/validation"),
    runner: Runner | None = None,
) -> ValidationReport:
    """run the named gates against one task dir and return a report; never raises on a failing gate."""
    unknown = set(gates) - set(GATE_FNS)
    if unknown:
        raise ValueError(f"unknown gates: {sorted(unknown)}")
    task_dir = task_dir.resolve()
    jobs_dir = jobs_dir.resolve()
    ctx = _Ctx(task_dir, runner or harbor_runner(jobs_dir), jobs_dir)
    results: list[GateResult] = []
    for name in (g for g in ORDER if g in gates):
        start = time.monotonic()
        try:
            passed, detail = GATE_FNS[name](ctx)
        except Exception as e:  # noqa: BLE001 - a gate crash is a rejection with a reason, not a crash
            passed, detail = False, f"{type(e).__name__}: {e}"[:1000]
        results.append(GateResult(gate=name, passed=passed, detail=detail, seconds=round(time.monotonic() - start, 1)))
        if not passed:
            break
    report = ValidationReport(
        task_id=task_id_of(task_dir),
        accepted=len(results) == len([g for g in ORDER if g in gates]) and all(r.passed for r in results),
        gates=results,
        mutants_total=ctx.mutants_total,
        mutants_killed=ctx.mutants_killed,
        log_path=_display(jobs_dir),
    )
    out = reports_dir / f"{report.task_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.model_dump_json(indent=2) + "\n")
    return report


def _display(path: Path) -> str:
    # keep machine-specific absolute paths out of committed reports
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def find_task_dirs(paths: list[Path]) -> list[Path]:
    """a path is a task dir when it holds task.toml; otherwise search it for task dirs."""
    found: list[Path] = []
    for p in paths:
        if (p / "task.toml").exists():
            found.append(p)
        else:
            found += sorted(t.parent for t in p.rglob("task.toml"))
    return found
