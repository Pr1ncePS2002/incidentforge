"""thin wrapper over the harbor cli. owner: phase 1 (used by validate and evaluate)."""

from pathlib import Path


def run_job(
    task_path: Path,
    agent: str,
    job_name: str,
    jobs_dir: Path,
    model: str | None = None,
    extra_args: list[str] | None = None,
) -> Path:
    """run `harbor run` and return the job directory."""
    raise NotImplementedError


def read_rewards(job_dir: Path) -> dict[str, float]:
    """map trial task name -> reward from a finished job."""
    raise NotImplementedError
