"""writes a TaskSpec to a harbor task directory. owner: phase 1."""

from pathlib import Path

from incidentforge.models import TaskSpec


def write_task(spec: TaskSpec, tasks_root: Path) -> Path:
    """create tasks_root/<task_id>/ with instruction.md, task.toml, environment/, solution/, tests/."""
    raise NotImplementedError
