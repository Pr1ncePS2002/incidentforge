"""end-to-end factory run: real generate() + all six gates in docker, with a recorded llm answer instead of a model."""

import copy
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from incidentforge.generate import generate
from incidentforge.models import ValidationReport
from incidentforge.targets import load_target
from incidentforge.validate import GATES, validate_task

pytestmark = pytest.mark.docker

FIXTURE = Path(__file__).parent / "fixtures" / "replay" / "fail-fast-config-accepted.json"
# feature tests that already pass on the base commit; the factory must refuse them
PASSES_ON_BASE = {"tests/test_forge_noop.py": "def test_fault_noop():\n    assert True\n"}


class ReplayBackend:
    """answers every prompt with a recorded task, so the run makes no model call."""

    name = "replay"

    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def generate_json(
        self, prompt: str, schema: dict[str, Any], max_output_tokens: int = 8192, tag: str = ""
    ) -> dict[str, Any]:
        self.prompts.append(prompt)
        return copy.deepcopy(self.answer)


def _run(tmp_path: Path, backend: ReplayBackend, monkeypatch: pytest.MonkeyPatch) -> list[ValidationReport]:
    work = tmp_path / "work"
    # the mutation gate reuses the generator's clone instead of fetching the repo again
    monkeypatch.setenv("FORGE_REPO_CACHE", str(work / "checkouts"))

    def check(task_dir: Path) -> ValidationReport:
        return validate_task(task_dir, GATES, jobs_dir=tmp_path / "jobs", reports_dir=tmp_path / "reports")

    return generate(
        load_target("fastapi-template"),
        ["fail-fast-config"],
        1,
        backend,
        tasks_root=tmp_path / "tasks",
        work_root=work,
        validator=check,
        jobs=1,
        max_pairs=1,
    )


@pytest.fixture(autouse=True)
def _need_harbor() -> None:
    if shutil.which("harbor") is None:
        pytest.skip("harbor cli not installed")


def test_e2e_recorded_task_is_generated_validated_and_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = ReplayBackend(json.loads(FIXTURE.read_text()))
    [report] = _run(tmp_path, backend, monkeypatch)
    assert report.accepted, report.model_dump_json(indent=2)
    assert [g.gate for g in report.gates] == [
        "leak",
        "fail_on_base",
        "pass_on_reference",
        "regression",
        "mutation",
        "flakiness",
    ]
    assert report.mutants_killed >= 1
    assert len(backend.prompts) == 1
    task = tmp_path / "tasks" / report.task_id
    assert (task / "task.toml").exists() and (task / "solution" / "reference.patch").exists()


def test_e2e_tests_that_pass_on_base_are_rejected_by_fail_on_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer = json.loads(FIXTURE.read_text())
    answer["feature_tests"] = PASSES_ON_BASE
    backend = ReplayBackend(answer)
    [report] = _run(tmp_path, backend, monkeypatch)
    assert not report.accepted
    assert [(g.gate, g.passed) for g in report.gates] == [("leak", True), ("fail_on_base", False)]
    assert report.gates[-1].detail == "reward=1.0 feature_tests=1.0 repo_suite=1.0"
    # one retry with the failure fed back, then the task is moved out of tasks/
    assert len(backend.prompts) == 2 and "fail_on_base" in backend.prompts[1]
    assert not (tmp_path / "tasks" / report.task_id).exists()
    assert (tmp_path / "work" / "rejected" / report.task_id / "validation.json").exists()
