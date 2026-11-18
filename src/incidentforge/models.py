"""shared data contracts; every phase builds against these types."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class Language(StrEnum):
    python = "python"
    go = "go"


class Target(BaseModel):
    """a repository pinned at a commit that tasks are generated from."""

    name: str  # e.g. fastapi-template
    repo_url: str
    commit: str
    language: Language
    env_template: Path  # dir with Dockerfile + run_tests.sh copied into each task
    test_command: str  # runs the repo suite inside the task container, e.g. "run_tests -q tests/"
    source_root: str = "."  # path inside the repo where application code lives


class Surface(BaseModel):
    """a code location a family can attach a task to."""

    file: str  # repo-relative path
    symbol: str  # class/function name
    kind: str  # settings-class | env-read | validator | consumer | cache-key | config-writer | pool-config
    excerpt: str = ""  # short code excerpt for the generator prompt


class TaskSpec(BaseModel):
    """everything needed to write one harbor task package."""

    task_id: str  # e.g. fastapi-template/ff-001-email-config
    family: str  # family slug, e.g. fail-fast-config
    target: Target
    title: str
    instruction: str  # markdown shown to the agent; must not contain the solution
    solution_patch: str  # unified diff applied on the base commit by solution/solve.sh
    feature_tests: dict[str, str]  # filename -> content, copied to /tests and run by test.sh
    fault_cases: list[str] = Field(default_factory=list)  # human-readable injected faults the tests cover
    difficulty: str = "medium"  # easy | medium | hard
    origin: str = "llm"  # llm | feature-removal | hand-written
    surface: Surface | None = None


class GateResult(BaseModel):
    gate: str  # fail_on_base | pass_on_reference | regression | mutation | leak | flakiness
    passed: bool
    detail: str = ""
    seconds: float = 0.0


class ValidationReport(BaseModel):
    task_id: str
    accepted: bool
    gates: list[GateResult]
    mutants_total: int = 0
    mutants_killed: int = 0
    log_path: str | None = None


class EvalResult(BaseModel):
    task_id: str
    family: str
    agent: str
    model: str
    attempt: int
    reward: float
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    key: str = "free"  # free | paid | subscription
    max_turns: int | None = None  # agent turn cap for the run; none = uncapped (e.g. claude-code)
