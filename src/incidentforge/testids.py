"""swe-bench style test ids: fail_to_pass from the feature test sources, pass_to_pass from the target's own suite."""

from __future__ import annotations

import ast
import json
import re
import shlex
import subprocess
from pathlib import Path, PurePosixPath

from incidentforge.models import Language, Target

P2P_CACHE = Path(".cache/p2p")
_GO_TEST = re.compile(r"^func (Test\w*)\(\s*\w+\s+\*testing\.T\s*\)", re.MULTILINE)


def python_test_names(source: str) -> list[str]:
    """`func` and `Class::method` names pytest collects from one file; empty when it does not parse."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out: list[str] = []
    funcs = (ast.FunctionDef, ast.AsyncFunctionDef)
    for node in tree.body:
        if isinstance(node, funcs) and node.name.startswith("test"):
            out.append(node.name)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            out += [f"{node.name}::{m.name}" for m in node.body if isinstance(m, funcs) and m.name.startswith("test")]
    return out


def go_test_names(source: str) -> list[str]:
    return _GO_TEST.findall(source)


def go_package(path: str) -> str:
    """package dir of a go test file, `.` for the module root."""
    return str(PurePosixPath(path).parent)


def fail_to_pass(language: Language, files: dict[str, str]) -> list[str]:
    """feature test ids keyed by path relative to the source root: `path::name` (python), `pkg::TestX` (go)."""
    out: list[str] = []
    for path, source in files.items():
        if language is Language.go:
            out += [f"{go_package(path)}::{n}" for n in go_test_names(source)]
        else:
            out += [f"{path}::{n}" for n in python_test_names(source)]
    return list(dict.fromkeys(out))


def collect_command(target: Target) -> str:
    """lists the repo suite's test ids at the base commit, inside the target image."""
    if target.language is Language.go:
        # the module line maps import paths in the listing back to package dirs
        return "grep -m1 '^module ' /app/go.mod; run_tests -list . ./..."
    # a second -q would switch pytest to per-file counts
    args = [a for a in shlex.split(target.test_command)[1:] if a not in ("-q", "--quiet")]
    return shlex.join(["run_tests", "--collect-only", "-q", "-p", "no:cacheprovider", *args])


def parse_collected(language: Language, output: str) -> list[str]:
    """test ids from collect_command output; go benchmarks are left out since go test never runs them."""
    ids: list[str] = []
    if language is Language.go:
        module, names = "", list[str]()
        for line in output.splitlines():
            parts = line.split()
            if line.startswith("module ") and len(parts) > 1:
                module = parts[1]
            elif parts and parts[0] == "ok" and len(parts) > 1:
                pkg = parts[1].removeprefix(module).lstrip("/") or "."
                ids += [f"{pkg}::{n}" for n in names if not n.startswith("Benchmark")]
                names = []
            elif len(parts) == 1 and re.fullmatch(r"(Test|Example|Fuzz|Benchmark)\w*", parts[0]):
                names.append(parts[0])
        return sorted(set(ids))
    # node ids start at column 0; indented lines are warning bodies
    return sorted({line.rstrip() for line in output.splitlines() if "::" in line and line[:1] not in ("", " ", "\t")})


def image_name(target: Target) -> str:
    return f"incidentforge/{target.name}-env:{target.commit[:12]}"


def collect_pass_to_pass(target: Target) -> list[str]:
    """one collect-only run of the repo suite inside the target image; needs docker."""
    from incidentforge.failmap.coverage import ensure_image

    image = image_name(target)
    ensure_image(target, image)
    proc = subprocess.run(
        ["docker", "run", "--rm", image, "bash", "-lc", collect_command(target)],
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )
    ids = parse_collected(target.language, proc.stdout)
    if proc.returncode != 0 or not ids:
        raise RuntimeError(f"collecting {target.name} tests failed: {(proc.stdout + proc.stderr)[-1500:]}")
    return ids


def pass_to_pass(target: Target, cache_dir: Path = P2P_CACHE) -> list[str]:
    """repo suite ids at the target commit, cached per target and commit so docker runs once."""
    cache = cache_dir / f"{target.name}-{target.commit[:12]}.json"
    if cache.exists():
        data: list[str] = json.loads(cache.read_text())
        return data
    ids = collect_pass_to_pass(target)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(ids, indent=1) + "\n")
    return ids
