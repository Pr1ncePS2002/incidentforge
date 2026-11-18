"""ci assertion over a finished harbor job: every trial must hit the expected reward."""

import json
import sys
from pathlib import Path


def trial_rewards(job_dir: Path) -> dict[str, float | None]:
    """map trial name -> reward; None when the trial errored or produced no reward."""
    out: dict[str, float | None] = {}
    for result in sorted(job_dir.glob("*/result.json")):
        data = json.loads(result.read_text())
        rewards = (data.get("verifier_result") or {}).get("rewards") or {}
        reward = rewards.get("reward")
        out[data.get("trial_name") or result.parent.name] = None if data.get("exception_info") else reward
    return out


def check(job_dir: Path, expected: float) -> list[str]:
    """return human-readable problems; empty means every trial matched."""
    rewards = trial_rewards(job_dir)
    if not rewards:
        return [f"no trials found under {job_dir}"]
    return [f"{name}: reward {r!r}, expected {expected}" for name, r in rewards.items() if r != expected]


def main(argv: list[str]) -> int:
    job_dir, expected = Path(argv[0]), float(argv[1])
    problems = check(job_dir, expected)
    for p in problems:
        print(f"::error::{p}")
    print(f"{len(trial_rewards(job_dir)) - len(problems)} trial(s) ok, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
