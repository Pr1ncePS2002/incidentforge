"""write_task produces a complete harbor task tree from a spec."""

import json
import os
import shlex
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest
from conftest import REGRESSION_IDS

from incidentforge.models import Language, Surface, Target, TaskSpec
from incidentforge.package import feature_command, feature_test_paths, pin_dockerfile, rerender_task, write_task


def _spec(tmp_path: Path, language: Language = Language.python, tests: dict[str, str] | None = None) -> TaskSpec:
    env = tmp_path / "env"
    env.mkdir(parents=True)
    (env / "Dockerfile").write_text("FROM x\nARG REPO_URL=old\nARG REPO_COMMIT=deadbeef\nRUN true\n")
    (env / "run_tests.sh").write_text("#!/bin/bash\n")
    target = Target(
        name="demo",
        repo_url="https://example.com/demo.git",
        commit="0123456789abcdef0123456789abcdef01234567",
        licence="MIT",
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
        "tests/fail_to_pass.json",
        "tests/feature/tests/test_forge_x.py",
        "tests/pass_to_pass.json",
        "tests/test.sh",
    ]
    assert json.loads((d / "tests" / "fail_to_pass.json").read_text()) == ["tests/test_forge_x.py::test_x"]
    assert json.loads((d / "tests" / "pass_to_pass.json").read_text()) == REGRESSION_IDS
    assert os.access(d / "solution" / "solve.sh", os.X_OK)
    assert os.access(d / "tests" / "test.sh", os.X_OK)
    assert (d / "instruction.md").read_text().startswith("Make it fail fast.\n\n---")
    assert "/app" in (d / "instruction.md").read_text()
    assert (d / "solution" / "reference.patch").read_text().endswith("+b\n")
    assert "git apply" in (d / "solution" / "solve.sh").read_text()
    df = (d / "environment" / "Dockerfile").read_text()
    assert (
        "ARG REPO_COMMIT=0123456789abcdef0123456789abcdef01234567" in df
        and "ARG REPO_URL=https://example.com/demo.git" in df
    )


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
    assert meta["target"] == "demo" and meta["base_commit"] == "0123456789abcdef0123456789abcdef01234567"
    assert meta["repo_url"] == "https://example.com/demo.git" and meta["licence"] == "MIT"
    assert meta["fault_cases"] == ["smtp host without from", "port out of range"]
    # v0.2 map keys stay out of v0.1-style specs
    assert not {"source_url", "map_node", "blast_radius", "generator_backend"} & meta.keys()


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
    feature = sh.index("run_tests -q -p no:cacheprovider -rA tests/test_forge_x.py")
    assert feature < sh.index("bash -c 'run_tests -q tests/'")
    assert "reward.json" in sh and "ctrf.json" in sh
    subprocess.run(["bash", "-n", str(d / "tests" / "test.sh")], check=True)


TWO_TESTS = "def test_a():\n    pass\n\n\nclass TestB:\n    def test_b(self):\n        pass\n"


def _run_test_sh(
    tmp_path: Path, spec: TaskSpec, fake_run_tests: str, guards: list[str] | None = None
) -> tuple[dict[str, float], dict[str, Any]]:
    # runs the rendered script with a fake run_tests and returns reward.json and ctrf.json
    d = write_task(spec, tmp_path / "tasks", guards=guards or [])
    root = tmp_path / "sandbox"
    sh = (d / "tests" / "test.sh").read_text()
    sh = sh.replace("/logs/verifier", str(root / "logs")).replace("/tests/feature", str(d / "tests" / "feature"))
    workdir = "/app/backend" if spec.target.language is Language.python else "/app"
    sh = sh.replace(f"cd {workdir}\n", f"mkdir -p {root}/app && cd {root}/app\n")
    bindir = root / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    fake = bindir / "run_tests"
    fake.write_text("#!/bin/bash\n" + fake_run_tests)
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
    subprocess.run(["bash", "-c", sh], check=True, env=env, capture_output=True)
    logs = root / "logs"
    return json.loads((logs / "reward.json").read_text()), json.loads((logs / "ctrf.json").read_text())


def _pytest_fake(summary: str, suite_rc: int) -> str:
    # feature run prints -rA summary lines; the suite run must not see the feature file
    return (
        f'if [[ "$*" == *forge* ]]; then printf {shlex.quote(summary)}; exit 1; fi\n'
        f"test -e tests/test_forge_x.py && exit 9\nexit {suite_rc}\n"
    )


@pytest.mark.parametrize(
    ("summary", "suite_rc", "reward", "feature"),
    [
        ("PASSED tests/test_forge_x.py::test_a\nPASSED tests/test_forge_x.py::TestB::test_b\n", 0, 1, 1),
        ("PASSED tests/test_forge_x.py::test_a\nFAILED tests/test_forge_x.py::TestB::test_b - boom\n", 0, 0.5, 0.5),
        ("ERROR tests/test_forge_x.py - ImportError\n", 0, 0, 0),
        # a failing regression zeroes the reward even when every feature test passes
        ("PASSED tests/test_forge_x.py::test_a\nPASSED tests/test_forge_x.py::TestB::test_b\n", 1, 0, 1),
        # one failing parametrized case fails the whole function
        ("PASSED tests/test_forge_x.py::test_a[1]\nFAILED tests/test_forge_x.py::test_a[2]\n", 0, 0, 0),
    ],
)
def test_test_sh_per_test_reward(tmp_path, summary, suite_rc, reward, feature):
    spec = _spec(tmp_path, tests={"test_forge_x.py": TWO_TESTS})
    rewards, ctrf = _run_test_sh(tmp_path, spec, _pytest_fake(summary, suite_rc))
    assert rewards == {"reward": reward, "feature_tests": feature, "repo_suite": int(suite_rc == 0)}
    tests = {t["name"]: t["status"] for t in ctrf["results"]["tests"]}
    assert tests["repo_suite"] == ("passed" if suite_rc == 0 else "failed")
    assert tests["feature_tests"] == ("passed" if feature == 1 else "failed")
    assert set(tests) == {
        "feature_tests",
        "repo_suite",
        "tests/test_forge_x.py::test_a",
        "tests/test_forge_x.py::TestB::test_b",
    }
    assert ctrf["results"]["summary"]["tests"] == 4


def test_test_sh_partial_reward_is_a_fraction(tmp_path):
    body = "".join(f"def test_{i}():\n    pass\n\n" for i in range(3))
    spec = _spec(tmp_path, tests={"test_forge_x.py": body})
    rewards, _ = _run_test_sh(tmp_path, spec, _pytest_fake("PASSED tests/test_forge_x.py::test_1\n", 0))
    assert 0 < rewards["reward"] < 1 and rewards["reward"] == pytest.approx(1 / 3, abs=1e-4)


def test_test_sh_go_per_test_reward(tmp_path):
    src = "package cfg\n\nfunc TestFaultA(t *testing.T) {}\n\nfunc TestHappy(t *testing.T) {}\n"
    spec = _spec(tmp_path, Language.go, tests={"internal/cfg/forge_x_test.go": src})
    spec = spec.model_copy(update={"target": spec.target.model_copy(update={"source_root": "."})})
    fake = (
        'if [[ "$*" == *-run* ]]; then\n'
        '  [[ "$*" == *"^(TestFaultA|TestHappy)\\$"* ]] || exit 7\n'
        '  echo "--- FAIL: TestFaultA (0.00s)"; echo "    --- PASS: TestHappy/sub (0.00s)"\n'
        '  echo "--- PASS: TestHappy (0.00s)"; exit 1\nfi\nexit 0\n'
    )
    rewards, ctrf = _run_test_sh(tmp_path, spec, fake)
    assert rewards == {"reward": 0.5, "feature_tests": 0.5, "repo_suite": 1}
    tests = {t["name"]: t["status"] for t in ctrf["results"]["tests"]}
    assert tests["internal/cfg::TestFaultA"] == "failed" and tests["internal/cfg::TestHappy"] == "passed"


def test_test_sh_falls_back_to_exit_code_without_ids(tmp_path):
    spec = _spec(tmp_path, tests={"test_forge_x.py": "not python ("})
    rewards, _ = _run_test_sh(tmp_path, spec, "exit 0\n")
    assert rewards == {"reward": 1, "feature_tests": 1, "repo_suite": 1}


def test_unsafe_test_ids_are_rejected(tmp_path):
    spec = _spec(tmp_path, tests={'we"ird.py': "def test_a():\n    pass\n"})
    with pytest.raises(ValueError, match="unsupported characters"):
        write_task(spec, tmp_path / "t", regression_tests=[])


def test_rerender_keeps_content_and_extra_metadata(tmp_path):
    spec = _spec(tmp_path).model_copy(update={"source_url": "https://example.com/pm", "origin": "llm"})
    d = write_task(spec, tmp_path / "tasks", regression_tests=["old::id"])
    toml = d / "task.toml"
    # an older task: no repo_url/licence yet, plus keys a back-fill added
    text = toml.read_text().replace('repo_url = "https://example.com/demo.git"\n', "").replace('licence = "MIT"\n', "")
    toml.write_text(text.replace("[verifier]", 'map_node = "a.py::f"\nclassifier_family = "none"\n\n[verifier]'))
    before = {p.relative_to(d): p.read_bytes() for p in d.rglob("*") if p.is_file()}
    out = rerender_task(d, spec.target)
    after = {p.relative_to(d): p.read_bytes() for p in out.rglob("*") if p.is_file()}
    changed = {str(k) for k in after if before.get(k) != after[k]}
    # the pass_to_pass list already in the task is kept, so only task.toml gains keys
    assert changed == {"task.toml"}
    meta = tomllib.loads(toml.read_text())["metadata"]
    assert meta["licence"] == "MIT" and meta["map_node"] == "a.py::f" and meta["classifier_family"] == "none"
    assert meta["source_url"] == "https://example.com/pm" and meta["generator_backend"] == "claude-code"
    assert list(meta)[-3:] == ["source_url", "map_node", "classifier_family"]


def test_generator_metadata(tmp_path):
    spec = _spec(tmp_path).model_copy(update={"generator_backend": "gemini", "generator_model": "default"})
    meta = tomllib.loads((write_task(spec, tmp_path) / "task.toml").read_text())["metadata"]
    assert meta["generator_backend"] == "gemini" and meta["generator_model"] == "default"


def test_rewrite_is_idempotent(tmp_path):
    spec = _spec(tmp_path)
    d = write_task(spec, tmp_path / "t")
    (d / "stale.txt").write_text("x")
    write_task(spec, tmp_path / "t")
    assert not (d / "stale.txt").exists()


def test_feature_paths_and_commands(tmp_path):
    spec = _spec(tmp_path, tests={"a.py": "", "tests/sub/b.py": ""})
    assert feature_test_paths(spec) == ["tests/a.py", "tests/sub/b.py"]
    go = feature_command(Language.go, ["internal/cfg/x_test.go", "a_test.go"], ["internal/cfg::TestA", ".::TestB"])
    assert "run_tests -v -run '^(TestB)$' ./. >>" in go
    assert "run_tests -v -run '^(TestA)$' ./internal/cfg >>" in go
    assert "run_tests -v ./internal/cfg" in feature_command(Language.go, ["internal/cfg/x_test.go"])
    with pytest.raises(ValueError):
        feature_test_paths(_spec(tmp_path / "z", tests={"../evil.py": ""}))


def test_pin_dockerfile_leaves_other_lines():
    assert pin_dockerfile("FROM a\nRUN b\n", "u", "c") == "FROM a\nRUN b\n"


def test_rerender_skips_backend_for_hand_written_tasks(tmp_path):
    d = write_task(_spec(tmp_path), tmp_path / "tasks", regression_tests=[])
    rerender_task(d, _spec(tmp_path / "x").target)
    assert "generator_backend" not in tomllib.loads((d / "task.toml").read_text())["metadata"]


def test_cli_rerender(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from incidentforge import cli

    spec = _spec(tmp_path)
    d = write_task(spec, tmp_path / "tasks", regression_tests=[])
    monkeypatch.setattr("incidentforge.targets.load_target", lambda name: spec.target)
    res = CliRunner().invoke(cli.app, ["rerender", str(tmp_path / "tasks")])
    assert res.exit_code == 0, res.output
    assert f"rewrote {d}" in res.output
    assert json.loads((d / "tests" / "pass_to_pass.json").read_text()) == []
    (d / "tests" / "pass_to_pass.json").unlink()
    assert CliRunner().invoke(cli.app, ["rerender", str(d)]).exit_code == 0
    # without a list in the task it is collected again
    assert json.loads((d / "tests" / "pass_to_pass.json").read_text()) == REGRESSION_IDS


@pytest.mark.parametrize(
    ("summary", "reward", "suite"),
    [
        # the guard passes and the one scored test passes
        ("PASSED tests/test_forge_x.py::test_a\nPASSED tests/test_forge_x.py::TestB::test_b\n", 1, 1),
        # a failing guard is a regression even when the scored test passes
        ("FAILED tests/test_forge_x.py::test_a\nPASSED tests/test_forge_x.py::TestB::test_b\n", 0, 0),
        ("PASSED tests/test_forge_x.py::test_a\nFAILED tests/test_forge_x.py::TestB::test_b\n", 0, 1),
    ],
)
def test_guards_count_as_regressions(tmp_path, summary, reward, suite):
    spec = _spec(tmp_path, tests={"test_forge_x.py": TWO_TESTS})
    guard = "tests/test_forge_x.py::test_a"
    d = write_task(spec, tmp_path / "g", regression_tests=["r::t"], guards=[guard])
    assert json.loads((d / "tests" / "fail_to_pass.json").read_text()) == ["tests/test_forge_x.py::TestB::test_b"]
    assert json.loads((d / "tests" / "pass_to_pass.json").read_text()) == ["r::t", guard]
    rewards, ctrf = _run_test_sh(tmp_path, spec, _pytest_fake(summary, 0), guards=[guard])
    assert rewards == {
        "reward": reward,
        "feature_tests": reward if suite else rewards["feature_tests"],
        "repo_suite": suite,
    }
    names = [t["name"] for t in ctrf["results"]["tests"]]
    assert names[-1] == guard and ctrf["results"]["summary"]["tests"] == 4


def test_rerender_keeps_the_guard_split(tmp_path):
    spec = _spec(tmp_path, tests={"test_forge_x.py": TWO_TESTS})
    guard = "tests/test_forge_x.py::test_a"
    d = write_task(spec, tmp_path / "tasks", regression_tests=["r::t"], guards=[guard])
    before = (d / "tests" / "test.sh").read_text()
    rerender_task(d, spec.target)
    assert (d / "tests" / "test.sh").read_text() == before
    assert json.loads((d / "tests" / "pass_to_pass.json").read_text()) == ["r::t", guard]


def test_only_guards_scores_zero(tmp_path):
    spec = _spec(tmp_path, tests={"test_forge_x.py": "def test_a():\n    pass\n"})
    rewards, _ = _run_test_sh(
        tmp_path,
        spec,
        _pytest_fake("PASSED tests/test_forge_x.py::test_a\n", 0),
        guards=["tests/test_forge_x.py::test_a"],
    )
    assert rewards == {"reward": 0, "feature_tests": 0, "repo_suite": 1}


def test_cli_rerender_moves_tests_that_passed_in_a_nop_job(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from incidentforge import cli

    spec = _spec(tmp_path, tests={"test_forge_x.py": TWO_TESTS})
    d = write_task(spec, tmp_path / "tasks", regression_tests=["r::t"])
    trial = tmp_path / "job" / "ff-001-x__abc"
    (trial / "verifier").mkdir(parents=True)
    (trial / "result.json").write_text(json.dumps({"task_name": "ff-001-x", "verifier_result": {"rewards": {}}}))
    tests = [{"name": "tests/test_forge_x.py::test_a", "status": "passed"}]
    (trial / "verifier" / "ctrf.json").write_text(json.dumps({"results": {"tests": tests}}))
    monkeypatch.setattr("incidentforge.targets.load_target", lambda name: spec.target)
    res = CliRunner().invoke(cli.app, ["rerender", str(d), "--nop-job", str(tmp_path / "job")])
    assert res.exit_code == 0, res.output
    assert "1 base-passing test(s) moved" in res.output
    assert json.loads((d / "tests" / "fail_to_pass.json").read_text()) == ["tests/test_forge_x.py::TestB::test_b"]
