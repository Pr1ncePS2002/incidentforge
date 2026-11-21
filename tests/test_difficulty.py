"""difficulty from fault cases, fix scope from blast radius, and the task.toml key the map page reads."""

from pathlib import Path

import pytest

from incidentforge import map_render
from incidentforge.failmap.difficulty import difficulty_from_faults, fix_scope
from incidentforge.models import Language, Surface, Target, TaskSpec
from incidentforge.package import write_task


@pytest.mark.parametrize(
    ("faults", "want"), [(0, "easy"), (3, "easy"), (4, "medium"), (5, "medium"), (6, "hard"), (9, "hard")]
)
def test_difficulty_from_faults(faults: int, want: str) -> None:
    assert difficulty_from_faults(faults) == want


@pytest.mark.parametrize(
    ("files", "want"), [(0, "1 file"), (1, "1 file"), (2, "2-3 files"), (3, "2-3 files"), (4, "4+ files")]
)
def test_fix_scope(files: int, want: str) -> None:
    assert fix_scope(files) == want


def test_packaged_task_is_pinned_on_the_map(tmp_path: Path) -> None:
    # writer and reader share one key (F-58)
    env = tmp_path / "env"
    env.mkdir()
    (env / "Dockerfile").write_text("FROM x\nARG REPO_URL=a\nARG REPO_COMMIT=b\n")
    (env / "run_tests.sh").write_text("#!/bin/bash\n")
    target = Target(name="demo", repo_url="u", commit="c", language=Language.python, env_template=env, test_command="t")
    surface = Surface(file="a.py", symbol="S", kind="settings-class", node_id="a.py::S", blast_radius=2)
    spec = TaskSpec(
        task_id="demo/ff-001-x",
        family="fail-fast-config",
        target=target,
        title="t",
        instruction="i",
        solution_patch="p",
        feature_tests={"test_x.py": "def test_x():\n    pass\n"},
        surface=surface,
    )
    root = tmp_path / "tasks"
    write_task(spec, root)
    assert map_render.tasks_from_dir(root / "demo") == [
        {"task_id": "demo/ff-001-x", "node_id": "a.py::S", "family": "fail-fast-config", "difficulty": "medium"}
    ]
    assert 'fix_scope = "2-3 files"' in (root / "demo" / "ff-001-x" / "task.toml").read_text()
