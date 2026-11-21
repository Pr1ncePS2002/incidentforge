"""writes a TaskSpec to a harbor task directory. owner: phase 1."""

from __future__ import annotations

import json
import re
import shlex
import shutil
from pathlib import Path, PurePosixPath

from incidentforge.failmap.difficulty import fix_scope
from incidentforge.models import Language, TaskSpec

REPO_ROOT = "/app"
# feature tests ship under tests/feature/ so they never clash with test.sh
FEATURE_DIR = "feature"
AGENT_TIMEOUT_SEC = 1800.0
VERIFIER_TIMEOUT_SEC = 900.0
BUILD_TIMEOUT_SEC = 1200.0

FOOTER = (
    "\n\n---\n\nThe repository is checked out at `/app`. Run the test suite with `run_tests` "
    "(it accepts the usual test runner arguments).\n"
)


def feature_test_paths(spec: TaskSpec) -> list[str]:
    """feature test paths relative to the source root; a bare filename lands in tests/."""
    out = []
    for name in spec.feature_tests:
        p = PurePosixPath(name)
        if p.is_absolute() or ".." in p.parts:
            raise ValueError(f"feature test path must stay inside the repo: {name}")
        out.append(str(p if len(p.parts) > 1 else PurePosixPath("tests") / p))
    return out


def feature_command(language: Language, paths: list[str]) -> str:
    """command that runs only the feature tests via the env's run_tests helper."""
    if language is Language.go:
        # go tests run per package, so target each test file's directory
        dirs = sorted({"./" + str(PurePosixPath(p).parent) for p in paths})
        return "run_tests " + " ".join(shlex.quote(d) for d in dirs)
    return "run_tests -q -p no:cacheprovider " + " ".join(shlex.quote(p) for p in paths)


def _toml_value(v: object) -> str:
    # json string/list escapes are a valid subset of toml basic strings and arrays
    return json.dumps(v, ensure_ascii=False)


def render_task_toml(spec: TaskSpec) -> str:
    meta: dict[str, object] = {
        "title": spec.title,
        "family": spec.family,
        "difficulty": spec.difficulty,
        "origin": spec.origin,
        "target": spec.target.name,
        "base_commit": spec.target.commit,
        "fault_cases": spec.fault_cases,
    }
    # optional keys are left out when unset so v0.1 task.toml files render byte-identical
    optional = {
        "source_url": spec.source_url,
        "map_node": spec.surface.node_id if spec.surface else None,
        "blast_radius": spec.surface.blast_radius if spec.surface else None,
        "fix_scope": fix_scope(spec.surface.blast_radius) if spec.surface and spec.surface.blast_radius else None,
    }
    meta.update({k: v for k, v in optional.items() if v is not None})
    lines = ['schema_version = "1.4"', "", "[metadata]"]
    lines += [f"{k} = {_toml_value(v)}" for k, v in meta.items()]
    lines += [
        "",
        "[verifier]",
        f"timeout_sec = {VERIFIER_TIMEOUT_SEC}",
        'environment_mode = "shared"',
        "",
        "[agent]",
        f"timeout_sec = {AGENT_TIMEOUT_SEC}",
        "",
        "[environment]",
        f"build_timeout_sec = {BUILD_TIMEOUT_SEC}",
        "",
    ]
    return "\n".join(lines)


def render_test_sh(spec: TaskSpec) -> str:
    paths = feature_test_paths(spec)
    workdir = str(PurePosixPath(REPO_ROOT) / spec.target.source_root)
    copies = "\n".join(
        f'mkdir -p "$(dirname {shlex.quote(p)})" && cp /tests/{FEATURE_DIR}/{shlex.quote(p)} {shlex.quote(p)}'
        for p in paths
    )
    removes = "rm -f " + " ".join(shlex.quote(p) for p in paths)
    return f"""#!/bin/bash
# runs feature tests, then the repo suite without them; reward 1 only when both pass
set -u
mkdir -p /logs/verifier
cd {shlex.quote(workdir)}

{copies}
{feature_command(spec.target.language, paths)} > /logs/verifier/feature_tests.log 2>&1
feature=$?

# the repo suite must pass on its own, so the feature tests are taken out again
{removes}
bash -c {shlex.quote(spec.target.test_command)} > /logs/verifier/repo_suite.log 2>&1
suite=$?

f=$([ "$feature" -eq 0 ] && echo 1 || echo 0)
s=$([ "$suite" -eq 0 ] && echo 1 || echo 0)
r=$([ "$f" -eq 1 ] && [ "$s" -eq 1 ] && echo 1 || echo 0)
st() {{ [ "$1" -eq 1 ] && echo passed || echo failed; }}
now=$(date +%s)000
cat > /logs/verifier/ctrf.json <<EOF
{{"results": {{"tool": {{"name": "incidentforge"}},
  "summary": {{"tests": 2, "passed": $((f + s)), "failed": $((2 - f - s)), "pending": 0, "skipped": 0,
    "other": 0, "start": $now, "stop": $now}},
  "tests": [
    {{"name": "feature_tests", "status": "$(st $f)", "duration": 0}},
    {{"name": "repo_suite", "status": "$(st $s)", "duration": 0}}]}}}}
EOF
echo "{{\\"reward\\": $r, \\"feature_tests\\": $f, \\"repo_suite\\": $s}}" > /logs/verifier/reward.json
echo "feature_tests=$f repo_suite=$s reward=$r"
"""


SOLVE_SH = f"""#!/bin/bash
# applies the reference patch on the base commit
set -euo pipefail
cd {REPO_ROOT}
git apply --whitespace=nowarn /solution/reference.patch
"""


def pin_dockerfile(text: str, repo_url: str, commit: str) -> str:
    """rewrite the build arg defaults so the image always builds the spec's base commit."""
    text = re.sub(r"(?m)^ARG REPO_COMMIT=.*$", f"ARG REPO_COMMIT={commit}", text)
    return re.sub(r"(?m)^ARG REPO_URL=.*$", f"ARG REPO_URL={repo_url}", text)


def _write(path: Path, text: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if executable:
        path.chmod(0o755)


def write_task(spec: TaskSpec, tasks_root: Path) -> Path:
    """create tasks_root/<task_id>/ with instruction.md, task.toml, environment/, solution/, tests/."""
    task_dir = tasks_root / spec.task_id
    paths = feature_test_paths(spec)
    if task_dir.exists():
        shutil.rmtree(task_dir)
    task_dir.mkdir(parents=True)

    _write(task_dir / "instruction.md", spec.instruction.rstrip() + FOOTER)
    _write(task_dir / "task.toml", render_task_toml(spec))

    env_dir = task_dir / "environment"
    shutil.copytree(spec.target.env_template, env_dir)
    dockerfile = env_dir / "Dockerfile"
    if dockerfile.exists():
        dockerfile.write_text(pin_dockerfile(dockerfile.read_text(), spec.target.repo_url, spec.target.commit))

    patch = spec.solution_patch if spec.solution_patch.endswith("\n") else spec.solution_patch + "\n"
    _write(task_dir / "solution" / "reference.patch", patch)
    _write(task_dir / "solution" / "solve.sh", SOLVE_SH, executable=True)

    _write(task_dir / "tests" / "test.sh", render_test_sh(spec), executable=True)
    for rel, content in zip(paths, spec.feature_tests.values(), strict=True):
        _write(task_dir / "tests" / FEATURE_DIR / rel, content)
    return task_dir
