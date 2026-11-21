"""write_task produces a complete harbor task tree from a spec."""

import os
import subprocess
import tomllib
from pathlib import Path

import pytest

from incidentforge.models import Language, Surface, Target, TaskSpec
from incidentforge.package import feature_command, feature_test_paths, pin_dockerfile, write_task


def _spec(tmp_path: Path, language: Language = Language.python, tests: dict[str, str] | None = None) -> TaskSpec:
    env = tmp_path / "env"
    env.mkdir(parents=True)
    (env / "Dockerfile").write_text("FROM x\nARG REPO_URL=old\nARG REPO_COMMIT=deadbeef\nRUN true\n")
    (env / "run_tests.sh").write_text("#!/bin/bash\n")
    target = Target(
        name="demo",
        repo_url="https://example.com/demo.git",
        commit="abc123",
        language=language,
        env_template=env,
        test_command="run_tests -q tests/",
        source_root="backend",
    )
    return TaskSpec(
        task_id="demo/ff-001-x",
        family="fail-fast-config",
        target=target,
        title='email "config"',
        instruction="Make it fail fast.\n\n",
        solution_patch="--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b",
        feature_tests=tests or {"test_forge_x.py": "def test_x():\n    assert True\n"},
        fault_cases=["smtp host without from", "port out of range"],
        origin="hand-written",
    )


def test_write_task_tree(tmp_path):
    d = write_task(_spec(tmp_path), tmp_path / "tasks")
    assert d == tmp_path / "tasks" / "demo" / "ff-001-x"
    files = sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file())
    assert files == [
        "environment/Dockerfile",
        "environment/run_tests.sh",
        "instruction.md",
        "solution/reference.patch",
        "solution/solve.sh",
        "task.toml",
        "tests/feature/tests/test_forge_x.py",
        "tests/test.sh",
    ]
    assert os.access(d / "solution" / "solve.sh", os.X_OK)
    assert os.access(d / "tests" / "test.sh", os.X_OK)
    assert (d / "instruction.md").read_text().startswith("Make it fail fast.\n\n---")
    assert "/app" in (d / "instruction.md").read_text()
    assert (d / "solution" / "reference.patch").read_text().endswith("+b\n")
    assert "git apply" in (d / "solution" / "solve.sh").read_text()
    df = (d / "environment" / "Dockerfile").read_text()
    assert "ARG REPO_COMMIT=abc123" in df and "ARG REPO_URL=https://example.com/demo.git" in df


def test_task_toml(tmp_path):
    d = write_task(_spec(tmp_path), tmp_path)
    cfg = tomllib.loads((d / "task.toml").read_text())
    assert cfg["schema_version"] == "1.4"
    assert cfg["verifier"] == {"timeout_sec": 900.0, "environment_mode": "shared"}
    assert cfg["agent"]["timeout_sec"] == 1800.0
    assert cfg["environment"]["build_timeout_sec"] == 1200.0
    meta = cfg["metadata"]
    assert meta["title"] == 'email "config"'
    assert meta["family"] == "fail-fast-config"
    assert meta["origin"] == "hand-written"
    assert meta["target"] == "demo" and meta["base_commit"] == "abc123"
    assert meta["fault_cases"] == ["smtp host without from", "port out of range"]
    # v0.2 map keys stay out of v0.1-style specs
    assert not {"source_url", "map_node", "blast_radius"} & meta.keys()


def test_task_toml_map_metadata(tmp_path):
    surface = Surface(
        file="core/config.py",
        symbol="Settings",
        kind="settings-class",
        node_id="core/config.py::Settings",
        blast_radius=3,
    )
    spec = _spec(tmp_path).model_copy(
        update={"surface": surface, "source_url": "https://example.com/pm", "difficulty": "hard"}
    )
    meta = tomllib.loads((write_task(spec, tmp_path) / "task.toml").read_text())["metadata"]
    assert meta["source_url"] == "https://example.com/pm"
    assert meta["map_node"] == "core/config.py::Settings" and meta["blast_radius"] == 3
    assert meta["difficulty"] == "hard"


def test_test_sh_runs_feature_then_suite(tmp_path):
    d = write_task(_spec(tmp_path), tmp_path)
    sh = (d / "tests" / "test.sh").read_text()
    assert "cd /app/backend" in sh
    feature = sh.index("run_tests -q -p no:cacheprovider tests/test_forge_x.py")
    assert feature < sh.index("bash -c 'run_tests -q tests/'")
    assert "reward.json" in sh and "ctrf.json" in sh
    subprocess.run(["bash", "-n", str(d / "tests" / "test.sh")], check=True)


def test_test_sh_reward_logic(tmp_path):
    # run the script with a fake run_tests to check the reward and ctrf it writes
    import json

    d = write_task(_spec(tmp_path), tmp_path)
    root = tmp_path / "sandbox"
    sh = (d / "tests" / "test.sh").read_text()
    sh = sh.replace("/logs/verifier", str(root / "logs")).replace("/tests/feature", str(d / "tests" / "feature"))
    sh = sh.replace("cd /app/backend", f"mkdir -p {root}/app && cd {root}/app")
    bindir = root / "bin"
    bindir.mkdir(parents=True)
    for feature_rc, suite_rc, want in [(0, 0, 1), (1, 0, 0), (0, 1, 0)]:
        fake = bindir / "run_tests"
        fake.write_text(
            f'#!/bin/bash\nif [[ "$*" == *forge* ]]; then exit {feature_rc}; fi\n'
            f"test -e tests/test_forge_x.py && exit 9\nexit {suite_rc}\n"
        )
        fake.chmod(0o755)
        env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
        subprocess.run(["bash", "-c", sh], check=True, env=env, capture_output=True)
        rewards = json.loads((root / "logs" / "reward.json").read_text())
        assert rewards == {"reward": want, "feature_tests": int(feature_rc == 0), "repo_suite": int(suite_rc == 0)}
        ctrf = json.loads((root / "logs" / "ctrf.json").read_text())
        assert ctrf["results"]["summary"]["passed"] == int(feature_rc == 0) + int(suite_rc == 0)


def test_rewrite_is_idempotent(tmp_path):
    spec = _spec(tmp_path)
    d = write_task(spec, tmp_path / "t")
    (d / "stale.txt").write_text("x")
    write_task(spec, tmp_path / "t")
    assert not (d / "stale.txt").exists()


def test_feature_paths_and_commands(tmp_path):
    spec = _spec(tmp_path, tests={"a.py": "", "tests/sub/b.py": ""})
    assert feature_test_paths(spec) == ["tests/a.py", "tests/sub/b.py"]
    assert feature_command(Language.go, ["internal/cfg/x_test.go", "internal/cfg/y_test.go"]) == (
        "run_tests ./internal/cfg"
    )
    with pytest.raises(ValueError):
        feature_test_paths(_spec(tmp_path / "z", tests={"../evil.py": ""}))


def test_pin_dockerfile_leaves_other_lines():
    assert pin_dockerfile("FROM a\nRUN b\n", "u", "c") == "FROM a\nRUN b\n"
