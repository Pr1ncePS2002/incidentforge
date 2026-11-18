"""batch evaluation through harbor with the paid-key cap enforced between batches. owner: phase 4."""

from __future__ import annotations

import json
import os
import random
import time
import tomllib
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from incidentforge.budget import BudgetExhausted, Ledger, cost_usd, render, status
from incidentforge.models import EvalResult

# models the free key can serve (F-06); anything else needs the capped paid key
FREE_MODELS = frozenset({"gemini-3.8-flash", "gemini-3.7-flash", "gemini-4-hydrogen"})
# agents that bill a subscription login, never a gemini key
SUBSCRIPTION_AGENTS = frozenset({"claude-code"})
GEMINI_KEY_VARS = ("GEMINI_API_KEY", "GEMINI_API_KEY2", "GOOGLE_API_KEY")
CLAUDE_TOKEN_VARS = ("CLAUDE_CODE_OAUTH_TOKEN",)

DEFAULT_RESULTS = Path("reports/eval/results.jsonl")
# turn cap of the main comparison; rows written before max_turns was recorded ran at this cap
DEFAULT_MAX_TURNS = 30
TRIALS_NAME = "trials.jsonl"


@dataclass(frozen=True)
class Limits:
    """per-trial ceilings; passed to the agent so the worst case is bounded."""

    max_turns: int = DEFAULT_MAX_TURNS
    max_input_per_turn: int = 64_000
    max_output_per_turn: int = 8_192

    def worst_tokens(self, trials: int) -> tuple[int, int]:
        return trials * self.max_turns * self.max_input_per_turn, trials * self.max_turns * self.max_output_per_turn

    def agent_args(self, agent: str) -> list[str]:
        if agent in SUBSCRIPTION_AGENTS or agent in {"oracle", "nop"}:
            return []
        return [
            "--ak",
            f"max_turns={self.max_turns}",
            "--ak",
            "llm_call_kwargs=" + json.dumps({"max_tokens": self.max_output_per_turn}),
        ]


@dataclass(frozen=True)
class TaskInfo:
    task_id: str  # path relative to the tasks root, e.g. fastapi-template/ff-001-email-config
    name: str  # harbor task name = task dir name
    dataset: Path  # dir harbor is pointed at with -p
    family: str = "unknown"
    difficulty: str = "medium"
    origin: str = "llm"
    target: str = ""
    fault_cases: tuple[str, ...] = ()
    feature_tests: tuple[str, ...] = ()


def discover_tasks(tasks_root: Path) -> list[TaskInfo]:
    """every dir under tasks_root holding a task.toml, with its forge metadata."""
    out: list[TaskInfo] = []
    for toml_path in sorted(tasks_root.rglob("task.toml")):
        task_dir = toml_path.parent
        meta: dict[str, Any] = {}
        try:
            meta = tomllib.loads(toml_path.read_text()).get("metadata") or {}
        except tomllib.TOMLDecodeError:
            pass
        tests_dir = task_dir / "tests"
        feature = tuple(
            sorted(p.name for p in tests_dir.iterdir() if p.is_file() and p.name != "test.sh")
            if tests_dir.is_dir()
            else ()
        )
        out.append(
            TaskInfo(
                task_id=task_dir.relative_to(tasks_root).as_posix(),
                name=task_dir.name,
                dataset=task_dir.parent,
                family=str(meta.get("family", "unknown")),
                difficulty=str(meta.get("difficulty", "medium")),
                origin=str(meta.get("origin", "llm")),
                target=str(meta.get("target", "")),
                fault_cases=tuple(str(f) for f in meta.get("fault_cases", []) or []),
                feature_tests=feature,
            )
        )
    return out


def pick_subset(tasks: list[TaskInfo], n: int = 10, seed: int = 2026) -> list[str]:
    """fixed seeded subset with at least one task per family when n allows."""
    rng = random.Random(seed)
    by_family: dict[str, list[TaskInfo]] = defaultdict(list)
    for t in sorted(tasks, key=lambda t: t.task_id):
        by_family[t.family].append(t)
    chosen: list[str] = []
    for fam in sorted(by_family):
        if len(chosen) < n:
            chosen.append(rng.choice(by_family[fam]).task_id)
    rest = sorted(t.task_id for t in tasks if t.task_id not in chosen)
    rng.shuffle(rest)
    chosen.extend(rest[: max(n - len(chosen), 0)])
    return sorted(chosen)


PAID_SUFFIX = "@paid"
# provider-side failures that say nothing about the model's code; such trials are retried, not scored
INFRA_ERRORS = frozenset(
    {
        "RateLimitError",
        "APIConnectionError",
        "APIError",
        "InternalServerError",
        "ServiceUnavailableError",
        "Timeout",
        "AuthenticationError",
        "AgentAuthenticationError",
        "BudgetExceededError",
    }
)


def harbor_model(model: str) -> str:
    """model id as harbor/litellm expects it, without the routing suffix."""
    return model.removesuffix(PAID_SUFFIX)


DEFAULT_SUBSET = Path("reports/eval/subset.json")


def frozen_subset(tasks_root: Path, n: int, path: Path = DEFAULT_SUBSET) -> list[str]:
    """seeded subset picked once and kept in a file, so later dataset growth doesn't move it."""
    if path.exists():
        return [str(t) for t in json.loads(path.read_text())]
    picked = pick_subset(discover_tasks(tasks_root), n)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(picked, indent=2) + "\n")
    return picked


def bare_model(model: str) -> str:
    return harbor_model(model).split("/")[-1]


def route(model: str, agent: str) -> str:
    """which key pays for this (model, agent): free | paid | subscription; `model@paid` forces key2."""
    if agent in SUBSCRIPTION_AGENTS:
        return "subscription"
    if model.endswith(PAID_SUFFIX):
        return "paid"
    return "free" if bare_model(model) in FREE_MODELS else "paid"


def key_env(key: str, base: Mapping[str, str]) -> dict[str, str]:
    """process env for one harbor job: exactly one gemini key, never both."""
    env = {k: v for k, v in base.items() if k not in GEMINI_KEY_VARS and k not in CLAUDE_TOKEN_VARS}
    if key == "subscription":
        env.update({k: base[k] for k in CLAUDE_TOKEN_VARS if base.get(k)})
    if key == "free":
        if not base.get("GEMINI_API_KEY"):
            raise RuntimeError("free gemini key (GEMINI_API_KEY) is not set")
        env["GEMINI_API_KEY"] = base["GEMINI_API_KEY"]
    elif key == "paid":
        if not base.get("GEMINI_API_KEY2"):
            raise RuntimeError("paid gemini key (GEMINI_API_KEY2) is not set")
        env["GEMINI_API_KEY"] = base["GEMINI_API_KEY2"]
    elif base.get("CLAUDE_CODE_OAUTH_TOKEN"):
        # harbor's claude-code agent only uses the subscription token when forced (p1 spike)
        env["CLAUDE_FORCE_OAUTH"] = "1"
    return env


@dataclass(frozen=True)
class Trial:
    task_name: str
    reward: float | None  # none = no verifier reward, i.e. an infra error worth retrying
    input_tokens: int = 0
    output_tokens: int = 0
    cache_tokens: int = 0
    exception: str | None = None
    failed_tests: tuple[str, ...] = ()
    parts: tuple[tuple[str, float], ...] = ()  # reward.json sub-scores, e.g. feature_tests / repo_suite
    turns: int = 0  # agent steps taken, from the trajectory; compared with the cap to spot turn exhaustion
    trial_dir: str = ""


def _log_failures(log: Path) -> list[str]:
    """failing test ids from pytest -rA (`FAILED id`) or go test (`--- FAIL: TestX`) output."""
    try:
        text = log.read_text(errors="replace")
    except OSError:
        return []
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith(("FAILED ", "ERROR ")) and "::" in line:
            out.append(line.split()[1])
        elif line.startswith("--- FAIL: "):
            out.append(line.split()[2])
    return list(dict.fromkeys(out))


def _failed_tests(trial_dir: Path) -> tuple[str, ...]:
    """per-test failures from the verifier logs, prefixed feature:: or repo::; ctrf as a fallback."""
    vdir = trial_dir / "verifier"
    failed = [f"feature::{t}" for t in _log_failures(vdir / "feature_tests.log")]
    failed += [f"repo::{t}" for t in _log_failures(vdir / "repo_suite.log")]
    if failed:
        return tuple(failed)
    for ctrf in sorted((trial_dir / "verifier").glob("ctrf*.json")):
        try:
            data = json.loads(ctrf.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        tests = (data.get("results") or {}).get("tests") if isinstance(data, dict) else None
        for t in tests or []:
            if t.get("status") in {"failed", "error"}:
                failed.append(str(t.get("name", "")))
    return tuple(failed)


def _turns(trial_dir: Path) -> int:
    try:
        steps = json.loads((trial_dir / "agent" / "trajectory.json").read_text()).get("steps") or []
    except (json.JSONDecodeError, OSError, AttributeError):
        return 0
    return sum(1 for s in steps if isinstance(s, dict) and s.get("source") == "agent")


def _parts(trial_dir: Path) -> tuple[tuple[str, float], ...]:
    try:
        data = json.loads((trial_dir / "verifier" / "reward.json").read_text())
    except (json.JSONDecodeError, OSError):
        return ()
    if not isinstance(data, dict):
        return ()
    return tuple((k, float(v)) for k, v in sorted(data.items()) if k != "reward" and isinstance(v, int | float))


def read_trials(job_dir: Path) -> list[Trial]:
    """parse each trial's result.json: reward, token usage, exception and failing ctrf tests."""
    out: list[Trial] = []
    for result in sorted(job_dir.glob("*/result.json")):
        data = json.loads(result.read_text())
        rewards = (data.get("verifier_result") or {}).get("rewards") or {}
        reward = rewards.get("reward")
        agent_result = data.get("agent_result") or {}
        exc = data.get("exception_info") or {}
        if exc.get("exception_type") in INFRA_ERRORS:
            reward = None
        out.append(
            Trial(
                task_name=str(data.get("task_name") or result.parent.name.split("__")[0]),
                reward=None if reward is None else float(reward),
                input_tokens=int(agent_result.get("n_input_tokens") or 0),
                output_tokens=int(agent_result.get("n_output_tokens") or 0),
                cache_tokens=int(agent_result.get("n_cache_tokens") or 0),
                exception=exc.get("exception_type"),
                failed_tests=_failed_tests(result.parent),
                parts=_parts(result.parent),
                turns=_turns(result.parent),
                trial_dir=str(result.parent),
            )
        )
    return out


@dataclass(frozen=True)
class RunRequest:
    dataset: Path
    agent: str
    model: str
    job_name: str
    jobs_dir: Path
    task_names: tuple[str, ...]
    extra_args: tuple[str, ...]
    env: Mapping[str, str] = field(repr=False, default_factory=dict)


Runner = Callable[[RunRequest], Path]


def harbor_runner(req: RunRequest) -> Path:
    """default runner over p1's harbor.run_job; the key travels only in the process env."""
    from incidentforge import harbor

    run_job = cast(Callable[..., Path], harbor.run_job)
    args = list(req.extra_args)
    for name in req.task_names:
        args += ["-i", name]
    return run_job(
        task_path=req.dataset,
        agent=req.agent,
        job_name=req.job_name,
        jobs_dir=req.jobs_dir,
        model=None if req.agent in SUBSCRIPTION_AGENTS else req.model,
        extra_args=args,
        env=dict(req.env),
    )


class ResultsStore:
    """append-only jsonl of EvalResult plus a sidecar with failing tests per trial."""

    def __init__(self, path: Path = DEFAULT_RESULTS) -> None:
        self.path = path
        self.trials_path = path.with_name(TRIALS_NAME)

    def load(self) -> list[EvalResult]:
        if not self.path.exists():
            return []
        rows = [EvalResult.model_validate_json(line) for line in self.path.read_text().splitlines() if line.strip()]
        for r in rows:
            if r.max_turns is None and r.agent not in SUBSCRIPTION_AGENTS:
                r.max_turns = DEFAULT_MAX_TURNS
        return rows

    def done(self) -> set[tuple[str, str, str, int, int | None]]:
        return {(r.task_id, r.agent, r.model, r.attempt, r.max_turns) for r in self.load()}

    def append(self, result: EvalResult, trial: Trial) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(result.model_dump_json() + "\n")
        side = {
            "task_id": result.task_id,
            "agent": result.agent,
            "model": result.model,
            "attempt": result.attempt,
            "failed_tests": list(trial.failed_tests),
            "parts": dict(trial.parts),
            "exception": trial.exception,
            "max_turns": result.max_turns,
            "turns": trial.turns,
        }
        with self.trials_path.open("a") as f:
            f.write(json.dumps(side) + "\n")


def _fit_batch(batch: list[TaskInfo], price_model: str, limits: Limits, ledger: Ledger) -> list[TaskInfo]:
    for n in range(len(batch), 0, -1):
        try:
            ledger.check(price_model, *limits.worst_tokens(n))
        except BudgetExhausted:
            continue
        return batch[:n]
    return []


def pass_rates(results: Iterable[EvalResult]) -> dict[str, tuple[int, int]]:
    """model -> (passed, total)."""
    acc: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in results:
        acc[r.model][0] += int(r.reward >= 1.0)
        acc[r.model][1] += 1
    return {m: (p, n) for m, (p, n) in acc.items()}


@dataclass
class _Progress:
    total: int
    done: int = 0
    errored: int = 0
    paid_runs: int = 0
    paid_usd: float = 0.0


def _progress_line(prog: _Progress, store: ResultsStore, ledger: Ledger, paid_left: int, worst_per_run: float) -> str:
    rates = ", ".join(f"{m} {p}/{n}" for m, (p, n) in sorted(pass_rates(store.load()).items()))
    per_run = prog.paid_usd / prog.paid_runs if prog.paid_runs else worst_per_run
    lines = [f"progress   {prog.done}/{prog.total} runs done, {prog.errored} errored | pass so far: {rates or '-'}"]
    lines.append(render(status(ledger, paid_left, per_run if paid_left else None)))
    return "\n".join(lines)


def run_eval(
    tasks_root: Path,
    models: list[str],
    agent: str = "terminus-2",
    k: int = 1,
    subset: list[str] | None = None,
    *,
    runner: Runner | None = None,
    ledger: Ledger | None = None,
    limits: Limits | None = None,
    batch_size: int = 4,
    concurrency: int = 2,
    results_path: Path = DEFAULT_RESULTS,
    jobs_dir: Path = Path("jobs"),
    env: Mapping[str, str] | None = None,
    echo: Callable[[str], None] = print,
) -> list[EvalResult]:
    """run every pending (task, model, attempt) in batches; paid batches only while their worst case fits."""
    runner = runner or harbor_runner
    ledger = ledger or Ledger.default()
    limits = limits or Limits()
    cap = None if agent in SUBSCRIPTION_AGENTS else limits.max_turns
    base_env = dict(env if env is not None else os.environ)
    store = ResultsStore(results_path)
    tasks = discover_tasks(tasks_root)
    if subset is not None:
        wanted = set(subset)
        tasks = [t for t in tasks if t.task_id in wanted]
    done = store.done()

    plan: list[tuple[str, int, list[TaskInfo]]] = []
    for model in models:
        for attempt in range(1, k + 1):
            pending = [t for t in tasks if (t.task_id, agent, harbor_model(model), attempt, cap) not in done]
            if pending:
                plan.append((model, attempt, pending))
    prog = _Progress(total=sum(len(p) for _, _, p in plan))
    paid_left = sum(len(p) for m, _, p in plan if route(m, agent) == "paid")
    echo(f"plan       {prog.total} runs pending over {len(models)} model(s), k={k}, {len(tasks)} task(s)")

    new: list[EvalResult] = []
    blocked: set[str] = set()
    for model, attempt, pending in plan:
        key = route(model, agent)
        if model in blocked:
            continue
        price_model = bare_model(model)
        worst_per_run = cost_usd(price_model, *limits.worst_tokens(1)) if key == "paid" else 0.0
        by_dataset: dict[Path, list[TaskInfo]] = defaultdict(list)
        for t in pending:
            by_dataset[t.dataset].append(t)
        for dataset, items in sorted(by_dataset.items()):
            queue = list(items)
            while queue and model not in blocked:
                batch = queue[:batch_size]
                if key == "paid":
                    # shrink the batch until its worst case fits; stop the model when even one run doesn't
                    batch = _fit_batch(batch, price_model, limits, ledger)
                    if not batch:
                        echo(f"stopped    {model}: worst case of one more run no longer fits the paid cap")
                        blocked.add(model)
                        break
                queue = queue[len(batch) :]
                stamp = time.strftime("%Y%m%d-%H%M%S")
                job_name = f"eval-{agent}-{price_model}-a{attempt}-{stamp}-{uuid.uuid4().hex[:6]}"
                req = RunRequest(
                    dataset=dataset,
                    agent=agent,
                    model=harbor_model(model),
                    job_name=job_name,
                    jobs_dir=jobs_dir,
                    task_names=tuple(t.name for t in batch),
                    extra_args=("-k", "1", "-n", str(concurrency), *limits.agent_args(agent)),
                    env=key_env(key, base_env),
                )
                try:
                    job_dir = runner(req)
                except RuntimeError as exc:
                    # harbor failed as a whole; keep whatever trials it wrote, and never retry a paid model blindly
                    echo(f"job failed {job_name}: {str(exc)[:300]}")
                    job_dir = jobs_dir / job_name
                    if key == "paid":
                        blocked.add(model)
                trials = read_trials(job_dir) if job_dir.is_dir() else []
                by_name = {t.name: t for t in batch}
                batch_in = sum(tr.input_tokens for tr in trials)
                batch_out = sum(tr.output_tokens for tr in trials)
                batch_cached = sum(tr.cache_tokens for tr in trials)
                if key == "paid":
                    # errored trials burned tokens too, so the whole batch is metered
                    prog.paid_usd += ledger.record(
                        price_model, batch_in, batch_out, tag=f"eval:{job_name}", cached_tokens=batch_cached
                    )
                    prog.paid_runs += len(batch)
                    paid_left -= len(batch)
                for tr in trials:
                    info = by_name.get(tr.task_name)
                    if info is None:
                        continue
                    prog.done += 1
                    if tr.reward is None:
                        prog.errored += 1
                        continue
                    res = EvalResult(
                        task_id=info.task_id,
                        family=info.family,
                        agent=agent,
                        model=harbor_model(model),
                        attempt=attempt,
                        reward=tr.reward,
                        input_tokens=tr.input_tokens,
                        output_tokens=tr.output_tokens,
                        cost_usd=round(cost_usd(price_model, tr.input_tokens, tr.output_tokens, tr.cache_tokens), 6)
                        if key == "paid"
                        else 0.0,
                        key=key,
                        max_turns=cap,
                    )
                    store.append(res, tr)
                    new.append(res)
                echo(_progress_line(prog, store, ledger, paid_left, worst_per_run))
    return new
