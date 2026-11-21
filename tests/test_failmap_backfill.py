"""back-fill of map metadata and fault-based difficulty onto tasks that predate the map."""

import shutil
from pathlib import Path

import pytest
from failmap_repos import py_repo

from incidentforge.failmap.backfill import apply, backfill
from incidentforge.failmap.build import build
from incidentforge.failmap.tag import tag
from incidentforge.models import Language

PATCH_CRUD = (
    "diff --git a/app/crud.py b/app/crud.py\n--- a/app/crud.py\n+++ b/app/crud.py\n"
    "@@ -57,2 +57,3 @@ def create_user\n+    pass\n"
)
PATCH_NEW = "diff --git a/app/fresh.py b/app/fresh.py\n--- /dev/null\n+++ b/app/fresh.py\n@@ -0,0 +1 @@\n+x = 1\n"
TOML = """schema_version = "1.4"

[metadata]
title = "t"
family = "{family}"
difficulty = "hard"
origin = "llm"
fault_cases = {faults}

[verifier]
timeout_sec = 900.0
"""


def _task(root: Path, name: str, family: str, faults: int, patch: str | None) -> Path:
    d = root / name
    (d / "solution").mkdir(parents=True)
    (d / "task.toml").write_text(TOML.format(family=family, faults=[f"f{i}" for i in range(faults)]).replace("'", '"'))
    if patch is not None:
        (d / "solution" / "reference.patch").write_text(patch)
    return d


@pytest.fixture
def layout(tmp_path: Path) -> tuple[Path, Path]:
    m = build(py_repo(tmp_path / "repo"), Language.python, tmp_path / "out").map_path
    tag(m)
    work = tmp_path / "work"
    (work / "demo").mkdir(parents=True)
    shutil.copy(m, work / "demo" / "map.sqlite")
    tasks = tmp_path / "tasks"
    _task(tasks / "demo", "ic-001-create-user", "idempotent-consumer", 4, PATCH_CRUD)
    _task(tasks / "demo", "rt-001-fresh", "config-round-trip", 2, PATCH_NEW)
    _task(tasks / "demo", "ff-001-nopatch", "fail-fast-config", 6, None)
    _task(tasks / "nomap", "ff-001-x", "fail-fast-config", 3, PATCH_CRUD)
    return tasks, work


def test_backfill_pins_tagged_node_and_sets_labels(layout: tuple[Path, Path]) -> None:
    tasks, work = layout
    got = {b.task_id: b for b in backfill(tasks, work)}
    ic = got["demo/ic-001-create-user"]
    assert ic.difficulty == "medium" and ic.map_node == "app/crud.py::create_user#handler"
    assert ic.blast_radius is not None and ic.fix_scope is not None
    text = (tasks / "demo" / "ic-001-create-user" / "task.toml").read_text()
    assert 'difficulty = "medium"' in text and 'map_node = "app/crud.py::create_user#handler"' in text
    assert text.endswith("[verifier]\ntimeout_sec = 900.0\n")
    # a patch that only adds files has no node in the base map
    assert got["demo/rt-001-fresh"].map_node is None and got["demo/rt-001-fresh"].difficulty == "easy"
    assert got["demo/ff-001-nopatch"].fix_scope is None and got["demo/ff-001-nopatch"].difficulty == "hard"
    assert got["nomap/ff-001-x"].map_node is None and got["nomap/ff-001-x"].difficulty == "easy"


def test_backfill_is_idempotent(layout: tuple[Path, Path]) -> None:
    tasks, work = layout
    first = backfill(tasks, work)
    before = (tasks / "demo" / "ic-001-create-user" / "task.toml").read_text()
    assert [apply(tasks / b.task_id, b) for b in first] == [False] * len(first)
    assert (tasks / "demo" / "ic-001-create-user" / "task.toml").read_text() == before


def test_backfill_without_map_keeps_existing_map_keys(layout: tuple[Path, Path]) -> None:
    tasks, work = layout
    backfill(tasks, work)
    toml = tasks / "demo" / "ic-001-create-user" / "task.toml"
    before = toml.read_text()
    (work / "demo" / "map.sqlite").unlink()
    [b] = [b for b in backfill(tasks, work) if b.task_id == "demo/ic-001-create-user"]
    assert not b.mapped and toml.read_text() == before
