"""each target env image must build and pass its own repo suite at the pinned commit."""

import subprocess

import pytest

from incidentforge.targets import TARGETS_DIR, load_target

pytestmark = pytest.mark.docker


@pytest.mark.parametrize("name", sorted(p.stem for p in TARGETS_DIR.glob("*.yaml")))
def test_target_image_builds_and_repo_suite_passes(name):
    t = load_target(name)
    tag = f"incidentforge/{name}-env:test"
    subprocess.run(["docker", "build", "-q", "-t", tag, str(t.env_template)], check=True, timeout=1800)
    run = subprocess.run(
        ["docker", "run", "--rm", tag, "bash", "-lc", t.test_command],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-2000:]
