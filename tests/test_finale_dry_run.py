"""finale dry-run script with docker and forge faked, so scaffolding and timing logic run in the fast stage."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
NAME = "demo-repo"

FAKE_DOCKER = """#!/usr/bin/env bash
echo "$@" >> "$FAKE_LOG"
"""

# writes an accepted report and exits at once, so it finishes inside the poll interval
FAKE_FORGE = """#!/usr/bin/env bash
echo "forge $@" >> "$FAKE_LOG"
if [ "$1" = run ]; then
  mkdir -p reports/validation/demo-repo
  echo '{"task_id": "demo-repo/t1", "accepted": true}' > reports/validation/demo-repo/t1.json
fi
"""


def _sandbox(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "finale_dry_run.sh", root / "scripts")
    shutil.copytree(REPO / "scripts" / "finale", root / "scripts" / "finale")
    (root / "src" / "incidentforge" / "targets").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("fake-docker", FAKE_DOCKER), ("fake-forge", FAKE_FORGE)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    env = {
        **os.environ,
        "FAKE_LOG": str(tmp_path / "calls.log"),
        "FINALE_DOCKER": str(bin_dir / "fake-docker"),
        "FINALE_FORGE": str(bin_dir / "fake-forge"),
        "FINALE_POLL_SEC": "2",
    }
    return root, env


def _run(root: Path, env: dict[str, str], commit: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(root / "scripts" / "finale_dry_run.sh"), "https://example.com/x.git", commit, "python", NAME, "1"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_scaffold_build_suite_forge_and_first_accept(tmp_path: Path) -> None:
    root, env = _sandbox(tmp_path)
    out = _run(root, env, "abc123")
    assert out.returncode == 0, out.stdout + out.stderr
    target = yaml.safe_load((root / "src/incidentforge/targets" / f"{NAME}.yaml").read_text())
    assert target["commit"] == "abc123"
    assert target["test_command"] == "run_tests -q"
    dockerfile = (root / "src/incidentforge/targets/env" / NAME / "Dockerfile").read_text()
    assert "ARG REPO_COMMIT=abc123" in dockerfile
    # the report lands after the first poll and forge exits before the next one
    assert "time to first accepted task" in out.stdout
    calls = (tmp_path / "calls.log").read_text()
    assert "forge run --target demo-repo --n 1" in calls
    assert "forge validate tasks/demo-repo" in calls


def test_rerun_keeps_hand_edits_and_uses_edited_test_command(tmp_path: Path) -> None:
    root, env = _sandbox(tmp_path)
    assert _run(root, env, "abc123").returncode == 0
    yaml_path = root / "src/incidentforge/targets" / f"{NAME}.yaml"
    data = yaml.safe_load(yaml_path.read_text())
    data.update(test_command="run_tests -q -k not_slow", source_root="pkg")
    yaml_path.write_text(yaml.safe_dump(data))
    (tmp_path / "calls.log").unlink()

    out = _run(root, env, "def456")
    assert out.returncode == 0, out.stdout + out.stderr
    data = yaml.safe_load(yaml_path.read_text())
    assert data["commit"] == "def456"
    assert data["test_command"] == "run_tests -q -k not_slow"
    assert data["source_root"] == "pkg"
    assert "bash -lc run_tests -q -k not_slow" in (tmp_path / "calls.log").read_text()


def test_failed_step_stops_the_run(tmp_path: Path) -> None:
    root, env = _sandbox(tmp_path)
    failing = tmp_path / "bin" / "fake-docker"
    failing.write_text("#!/usr/bin/env bash\nexit 3\n")
    out = _run(root, env, "abc123")
    assert out.returncode == 1
    assert "build" in out.stdout and "FAILED" in out.stdout
    assert not (tmp_path / "calls.log").exists() or "forge" not in (tmp_path / "calls.log").read_text()


def test_python_template_does_not_swallow_install_errors() -> None:
    text = (REPO / "scripts" / "finale" / "python" / "Dockerfile").read_text()
    assert "|| true" not in text
