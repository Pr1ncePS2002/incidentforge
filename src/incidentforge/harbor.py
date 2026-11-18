"""thin wrapper over the harbor cli. owner: phase 1 (used by validate and evaluate).
harbor 0.26 trial dirs: <job>/<task>__<id>/{result.json, verifier/{ctrf.json,reward.json,*.log}}."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


class HarborError(RuntimeError):
    """harbor exited non-zero or wrote no job dir."""


@dataclass
class Trial:
    task_name: str
    trial_name: str
    path: Path
    rewards: dict[str, float] = field(default_factory=dict)
    error: str | None = None
    input_tokens: int = 0
    cache_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def reward(self) -> float | None:
        """None when the trial errored or wrote no reward."""
        return None if self.error else self.rewards.get("reward")


def build_command(
    task_path: Path,
    agent: str,
    job_name: str,
    jobs_dir: Path,
    model: str | None = None,
    extra_args: list[str] | None = None,
) -> list[str]:
    cmd = ["harbor", "run", "-p", str(task_path), "-a", agent, "-o", str(jobs_dir), "--job-name", job_name, "-y", "-q"]
    if model:
        cmd += ["-m", model]
    return cmd + list(extra_args or [])


def run_job(
    task_path: Path,
    agent: str,
    job_name: str,
    jobs_dir: Path,
    model: str | None = None,
    extra_args: list[str] | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> Path:
    """run `harbor run` and return the job directory; env is merged over os.environ."""
    cmd = build_command(task_path, agent, job_name, jobs_dir, model, extra_args)
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, env={**os.environ, **(env or {})}, check=False
    )
    job_dir = jobs_dir / job_name
    if proc.returncode != 0 or not job_dir.is_dir():
        tail = (proc.stdout + proc.stderr)[-2000:]
        raise HarborError(f"harbor run exited {proc.returncode} for job {job_name}: {tail}")
    return job_dir


def _int(v: object) -> int:
    return int(v) if isinstance(v, int | float) else 0


def read_trials(job_dir: Path) -> list[Trial]:
    """parse trial result.json files: verifier_result.rewards, exception_info and
    agent_result {n_input_tokens, n_cache_tokens, n_output_tokens, cost_usd} (null for oracle/nop)."""
    trials = []
    for result in sorted(job_dir.glob("*/result.json")):
        data = json.loads(result.read_text())
        rewards = (data.get("verifier_result") or {}).get("rewards") or {}
        usage = data.get("agent_result") or {}
        exc = data.get("exception_info")
        error = None
        if exc:
            error = f"{exc.get('exception_type', 'error')}: {exc.get('exception_message', '')}"[:500]
        trials.append(
            Trial(
                task_name=data.get("task_name") or result.parent.name.split("__")[0],
                trial_name=data.get("trial_name") or result.parent.name,
                path=result.parent,
                rewards={k: float(v) for k, v in rewards.items() if isinstance(v, int | float)},
                error=error,
                input_tokens=_int(usage.get("n_input_tokens")),
                cache_tokens=_int(usage.get("n_cache_tokens")),
                output_tokens=_int(usage.get("n_output_tokens")),
                cost_usd=float(usage.get("cost_usd") or 0.0),
            )
        )
    return trials


def read_rewards(job_dir: Path) -> dict[str, float]:
    """map trial name -> reward from a finished job; errored trials count as 0."""
    return {t.trial_name: t.reward or 0.0 for t in read_trials(job_dir)}
