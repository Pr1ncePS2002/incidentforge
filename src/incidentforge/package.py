"""writes a TaskSpec to a harbor task directory. owner: phase 1."""

from __future__ import annotations

import json
import re
import shlex
import shutil
import tomllib
from collections.abc import Collection
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple

from incidentforge.failmap.difficulty import fix_scope
from incidentforge.models import Language, Target, TaskSpec
from incidentforge.testids import fail_to_pass, go_package, pass_to_pass

REPO_ROOT = "/app"
LOG_DIR = "/logs/verifier"
# marks which go package the following `go test -v` lines belong to in feature_tests.log
GO_PKG_MARK = "=== forge-pkg "
_SAFE_ID = re.compile(r"[\w./:-]+")
# feature tests ship under tests/feature/ so they never clash with test.sh
FEATURE_DIR = "feature"
F2P_FILE = "fail_to_pass.json"
P2P_FILE = "pass_to_pass.json"
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


def feature_command(language: Language, paths: list[str], tests: list[str] | None = None) -> str:
    """runs only the feature tests via the env's run_tests helper, logging to feature_tests.log."""
    log = f"{LOG_DIR}/feature_tests.log"
    if language is not Language.go:
        args = " ".join(shlex.quote(p) for p in paths)
        return f"run_tests -q -p no:cacheprovider -rA {args} > {log} 2>&1 || feature=1"
    # go tests run per package; one run per feature package keeps --- PASS lines attributable to it
    lines = [f": > {log}"]
    for pkg in sorted({go_package(p) for p in paths}):
        names = [t.split("::", 1)[1] for t in tests or [] if t.split("::", 1)[0] == pkg]
        run = f"-v -run {shlex.quote('^(' + '|'.join(names) + ')$')} " if names else "-v "
        lines.append(
            f"echo {shlex.quote(GO_PKG_MARK + pkg)} >> {log}; "
            f"run_tests {run}{shlex.quote('./' + pkg)} >> {log} 2>&1 || feature=1"
        )
    return "\n".join(lines)


def _toml_value(v: object) -> str:
    # json string/list escapes are a valid subset of toml basic strings and arrays
    return json.dumps(v, ensure_ascii=False)


def render_task_toml(spec: TaskSpec, extra: dict[str, object] | None = None) -> str:
    """task.toml; `extra` carries metadata keys this renderer does not own, e.g. from a back-fill."""
    meta: dict[str, object] = {
        "title": spec.title,
        "family": spec.family,
        "difficulty": spec.difficulty,
        "origin": spec.origin,
        "target": spec.target.name,
        "base_commit": spec.target.commit,
        "repo_url": spec.target.repo_url,
        "licence": spec.target.licence,
        "fault_cases": spec.fault_cases,
    }
    # optional keys are left out when unset so older task.toml files keep their shape
    optional = {
        "source_url": spec.source_url,
        "generator_backend": spec.generator_backend,
        "generator_model": spec.generator_model,
        "map_node": spec.surface.node_id if spec.surface else None,
        "blast_radius": spec.surface.blast_radius if spec.surface else None,
        "fix_scope": fix_scope(spec.surface.blast_radius) if spec.surface and spec.surface.blast_radius else None,
    }
    meta.update({k: v for k, v in optional.items() if v is not None})
    meta.update({k: v for k, v in (extra or {}).items() if k not in meta})
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


# per-test status from the feature log: pytest -rA summary lines, or column-0 go `--- PASS:` lines
_PY_STATUS = (
    '($1=="PASSED"||$1=="FAILED"||$1=="ERROR") { n=$2; sub(/\\[.*$/, "", n); '
    'if (n==id) { if ($1=="PASSED") p=1; else f=1 } } '
    'END { print (p && !f) ? "passed" : "failed" }'
)
_GO_STATUS = (
    f'index($0, "{GO_PKG_MARK}")==1 {{ pkg=substr($0, {len(GO_PKG_MARK) + 1}); next }} '
    '/^--- (PASS|FAIL|SKIP): / { if (pkg "::" $3 == id) { if ($2=="PASS:") p=1; else f=1 } } '
    'END { print (p && !f) ? "passed" : "failed" }'
)


def feature_test_ids(spec: TaskSpec) -> list[str]:
    """fail_to_pass ids; they are baked into test.sh and ctrf.json, so only plain characters pass."""
    files = dict(zip(feature_test_paths(spec), spec.feature_tests.values(), strict=True))
    ids = fail_to_pass(spec.target.language, files)
    bad = [i for i in ids if not _SAFE_ID.fullmatch(i)]
    if bad:
        raise ValueError(f"feature test ids with unsupported characters: {bad}")
    return ids


def render_test_sh(spec: TaskSpec, guards: Collection[str] = ()) -> str:
    """guards are feature tests that already pass on base: they count as regressions, not towards the score."""
    paths = feature_test_paths(spec)
    ids = feature_test_ids(spec)
    scored = [i for i in ids if i not in guards]
    kept = [i for i in ids if i in guards]
    workdir = str(PurePosixPath(REPO_ROOT) / spec.target.source_root)
    copies = "\n".join(
        f'mkdir -p "$(dirname {shlex.quote(p)})" && cp /tests/{FEATURE_DIR}/{shlex.quote(p)} {shlex.quote(p)}'
        for p in paths
    )
    removes = "rm -f " + " ".join(shlex.quote(p) for p in paths)
    status = _GO_STATUS if spec.target.language is Language.go else _PY_STATUS
    tests = " ".join(shlex.quote(i) for i in scored)
    guard_ids = " ".join(shlex.quote(i) for i in kept)
    return f"""#!/bin/bash
# runs the feature tests, then the repo suite without them.
# reward: 0 if the repo suite or a guard fails, else the share of tests/fail_to_pass.json that pass.
# guards are feature tests that already pass on base; they sit in tests/pass_to_pass.json
set -u
mkdir -p {LOG_DIR}
cd {shlex.quote(workdir)}

TESTS=({tests})
GUARDS=({guard_ids})
{copies}
feature=0
{feature_command(spec.target.language, paths, ids)}

# the repo suite must pass on its own, so the feature tests are taken out again
{removes}
bash -c {shlex.quote(spec.target.test_command)} > {LOG_DIR}/repo_suite.log 2>&1
suite=$?

status() {{ awk -v id="$1" {shlex.quote(status)} {LOG_DIR}/feature_tests.log; }}
passed=0
results=()
for t in ${{TESTS[@]+"${{TESTS[@]}}"}}; do
  r=$(status "$t")
  results+=("$r")
  [ "$r" = passed ] && passed=$((passed + 1))
done
guards_ok=1
guard_results=()
for t in ${{GUARDS[@]+"${{GUARDS[@]}}"}}; do
  g=$(status "$t")
  guard_results+=("$g")
  [ "$g" = passed ] || guards_ok=0
done
total=${{#TESTS[@]}}
# no test ids could be read from the feature files: fall back to the run's exit code
if [ "$total" -eq 0 ] && [ ${{#GUARDS[@]}} -eq 0 ]; then total=1; passed=$([ "$feature" -eq 0 ] && echo 1 || echo 0); fi
if [ "$total" -eq 0 ]; then total=1; fi
s=$([ "$suite" -eq 0 ] && [ "$guards_ok" -eq 1 ] && echo 1 || echo 0)
f=$(awk -v p="$passed" -v t="$total" 'BEGIN {{ printf "%.4g", p / t }}')
r=$([ "$s" -eq 1 ] && echo "$f" || echo 0)
st() {{ [ "$1" = 1 ] && echo passed || echo failed; }}
fs=$([ "$passed" -eq "$total" ] && echo passed || echo failed)
g_ok=0
for g in ${{guard_results[@]+"${{guard_results[@]}}"}}; do [ "$g" = passed ] && g_ok=$((g_ok + 1)); done
ok=$(( passed + g_ok + s + ($passed == $total ? 1 : 0) ))
n=$(( ${{#results[@]}} + ${{#guard_results[@]}} + 2 ))
now=$(date +%s)000
{{
  printf '{{"results": {{"tool": {{"name": "incidentforge"}},\\n'
  printf '  "summary": {{"tests": %d, "passed": %d, "failed": %d, "pending": 0, "skipped": 0, ' "$n" "$ok" "$((n - ok))"
  printf '"other": 0, "start": %s, "stop": %s}},\\n  "tests": [\\n' "$now" "$now"
  printf '    {{"name": "feature_tests", "status": "%s", "duration": 0}},\\n' "$fs"
  printf '    {{"name": "repo_suite", "status": "%s", "duration": 0}}' "$(st "$s")"
  i=0
  for t in ${{TESTS[@]+"${{TESTS[@]}}"}}; do
    printf ',\\n    {{"name": "%s", "status": "%s", "duration": 0}}' "$t" "${{results[$i]}}"
    i=$((i + 1))
  done
  i=0
  for t in ${{GUARDS[@]+"${{GUARDS[@]}}"}}; do
    printf ',\\n    {{"name": "%s", "status": "%s", "duration": 0}}' "$t" "${{guard_results[$i]}}"
    i=$((i + 1))
  done
  printf ']}}}}\\n'
}} > {LOG_DIR}/ctrf.json
echo "{{\\"reward\\": $r, \\"feature_tests\\": $f, \\"repo_suite\\": $s}}" > {LOG_DIR}/reward.json
echo "feature_tests=$passed/$total repo_suite=$s reward=$r"
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


def write_task(
    spec: TaskSpec,
    tasks_root: Path,
    regression_tests: list[str] | None = None,
    extra_metadata: dict[str, object] | None = None,
    guards: Collection[str] = (),
) -> Path:
    """create tasks_root/<task_id>/ with instruction.md, task.toml, environment/, solution/, tests/.

    regression_tests is the repo suite's pass_to_pass list; when none is given it is collected from the target
    image (cached). guards are feature test ids that pass on base; they move from fail_to_pass to pass_to_pass.
    """
    task_dir = tasks_root / spec.task_id
    paths = feature_test_paths(spec)
    test_sh = render_test_sh(spec, guards)
    ids = feature_test_ids(spec)
    repo = pass_to_pass(spec.target) if regression_tests is None else regression_tests
    if task_dir.exists():
        shutil.rmtree(task_dir)
    task_dir.mkdir(parents=True)

    _write(task_dir / "instruction.md", spec.instruction.rstrip() + FOOTER)
    _write(task_dir / "task.toml", render_task_toml(spec, extra_metadata))

    env_dir = task_dir / "environment"
    shutil.copytree(spec.target.env_template, env_dir)
    dockerfile = env_dir / "Dockerfile"
    if dockerfile.exists():
        dockerfile.write_text(pin_dockerfile(dockerfile.read_text(), spec.target.repo_url, spec.target.commit))

    patch = spec.solution_patch if spec.solution_patch.endswith("\n") else spec.solution_patch + "\n"
    _write(task_dir / "solution" / "reference.patch", patch)
    _write(task_dir / "solution" / "solve.sh", SOLVE_SH, executable=True)

    _write(task_dir / "tests" / "test.sh", test_sh, executable=True)
    f2p = [i for i in ids if i not in guards]
    p2p = sorted({*repo, *(i for i in ids if i in guards)})
    _write(task_dir / "tests" / F2P_FILE, json.dumps(f2p, indent=2) + "\n")
    _write(task_dir / "tests" / P2P_FILE, json.dumps(p2p, indent=2) + "\n")
    for rel, content in zip(paths, spec.feature_tests.values(), strict=True):
        _write(task_dir / "tests" / FEATURE_DIR / rel, content)
    return task_dir


class Rendered(NamedTuple):
    """what a task dir was written from: the spec, foreign metadata, repo pass_to_pass ids and guards."""

    spec: TaskSpec
    extra: dict[str, object]
    regression: list[str] | None
    guards: list[str]


def spec_from_task_dir(task_dir: Path, target: Target) -> Rendered:
    """rebuilds the inputs of write_task from a task dir, so a re-render keeps content and the guard split."""
    meta: dict[str, Any] = tomllib.loads((task_dir / "task.toml").read_text())["metadata"]
    instruction = (task_dir / "instruction.md").read_text().removesuffix(FOOTER)
    feature_root = task_dir / "tests" / FEATURE_DIR
    files = sorted(p for p in feature_root.rglob("*") if p.is_file())
    tests = {p.relative_to(feature_root).as_posix(): p.read_text() for p in files}
    spec = TaskSpec(
        task_id=f"{task_dir.parent.name}/{task_dir.name}",
        family=str(meta["family"]),
        target=target,
        title=str(meta["title"]),
        instruction=instruction,
        solution_patch=(task_dir / "solution" / "reference.patch").read_text(),
        feature_tests=tests,
        fault_cases=[str(f) for f in meta.get("fault_cases") or []],
        difficulty=str(meta.get("difficulty", "medium")),
        origin=str(meta.get("origin", "llm")),
        # every committed pre-click task came from the claude code backend; hand-written ones have none
        generator_backend=meta.get("generator_backend")
        or (None if meta.get("origin") == "hand-written" else "claude-code"),
        generator_model=meta.get("generator_model"),
    )
    owned = set(tomllib.loads(render_task_toml(spec))["metadata"])
    extra = {k: v for k, v in meta.items() if k not in owned}
    f2p_file, p2p_file = task_dir / "tests" / F2P_FILE, task_dir / "tests" / P2P_FILE
    ids = feature_test_ids(spec)
    f2p = set(json.loads(f2p_file.read_text())) if f2p_file.exists() else set(ids)
    guards = [i for i in ids if i not in f2p]
    regression = [i for i in json.loads(p2p_file.read_text()) if i not in guards] if p2p_file.exists() else None
    return Rendered(spec, extra, regression, guards)


def rerender_task(
    task_dir: Path,
    target: Target | None = None,
    regression_tests: list[str] | None = None,
    guards: Collection[str] | None = None,
) -> Path:
    """rewrites a task in the current package format without touching its generated content.

    the existing pass_to_pass list and guard split are kept unless new ones are passed.
    """
    if target is None:
        from incidentforge.targets import load_target

        target = load_target(str(tomllib.loads((task_dir / "task.toml").read_text())["metadata"]["target"]))
    r = spec_from_task_dir(task_dir, target)
    regression = regression_tests if regression_tests is not None else r.regression
    return write_task(r.spec, task_dir.parent.parent, regression, r.extra, r.guards if guards is None else guards)
