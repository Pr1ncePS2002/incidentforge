"""validation gates for a harbor task directory. owner: phase 1."""

from pathlib import Path

from incidentforge.models import ValidationReport

GATES = ("fail_on_base", "pass_on_reference", "regression", "mutation", "leak", "flakiness")


def validate_task(task_dir: Path, gates: tuple[str, ...] = GATES) -> ValidationReport:
    """run the named gates against one task dir and return a report; never raises on a failing gate."""
    raise NotImplementedError
