"""feature 3 (D-65): static test edges plus one real coverage run per target, merged into covered/risk_score."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from incidentforge.failmap import build
from incidentforge.failmap.radius import Graph
from incidentforge.failmap.store import Annotation, read_annotations, write_annotations
from incidentforge.models import Language, Target

CONTAINER_ROOT = "/app"  # both env templates clone the target repo here
_GO_BLOCK = re.compile(r"^(?P<file>.+\.go):(?P<l1>\d+)\.\d+,(?P<l2>\d+)\.\d+ \d+ (?P<count>\d+)$")

LineMap = dict[str, dict[str, list[int]]]  # repo-relative file -> {"executed": [...], "missing": [...]}


@dataclass(frozen=True)
class Coverage:
    covered: bool
    risk_score: float
    static_tests: int


def cache_path(out_dir: Path, commit: str) -> Path:
    return out_dir / f"coverage-{commit[:12]}.json"


def parse_python(data: dict[str, Any]) -> LineMap:
    """coverage.py json report written from the container repo root, so paths are already repo-relative."""
    out: LineMap = {}
    for path, info in data.get("files", {}).items():
        rel = path.removeprefix(f"{CONTAINER_ROOT}/")
        out[rel] = {
            "executed": sorted(info.get("executed_lines", [])),
            "missing": sorted(info.get("missing_lines", [])),
        }
    return out


def go_module(repo: Path) -> str:
    for line in (repo / "go.mod").read_text().splitlines():
        if line.startswith("module "):
            return line.split()[1]
    raise ValueError("go.mod has no module line")


def parse_go(profile: str, module: str) -> LineMap:
    """go coverprofile blocks; a line is executed when any block covering it ran."""
    executed: dict[str, set[int]] = {}
    seen: dict[str, set[int]] = {}
    for raw in profile.splitlines():
        m = _GO_BLOCK.match(raw.strip())
        if not m:
            continue
        rel = m.group("file").removeprefix(f"{module}/")
        lines = set(range(int(m.group("l1")), int(m.group("l2")) + 1))
        seen.setdefault(rel, set()).update(lines)
        if int(m.group("count")) > 0:
            executed.setdefault(rel, set()).update(lines)
    return {
        f: {"executed": sorted(executed.get(f, set())), "missing": sorted(seen[f] - executed.get(f, set()))}
        for f in sorted(seen)
    }


def coverage_command(target: Target) -> str:
    """the target's own test command with coverage switched on; outputs land in /out."""
    args = shlex.split(target.test_command)[1:]
    if target.language is Language.go:
        return shlex.join(["run_tests", "-coverprofile=/out/cover.out", *args])
    # run_tests ends in `exec python -m pytest`; swap in coverage run so its config in the repo is honoured
    # older images lack the venv on a login shell PATH
    return (
        f"export PATH={CONTAINER_ROOT}/.venv/bin:$PATH; "
        "sed -E 's/^exec (python -m )?pytest/COVERAGE_FILE=\\/out\\/.coverage coverage run -m pytest/' "
        f"/usr/local/bin/run_tests > /tmp/rt; bash /tmp/rt {shlex.join(args)}; "
        f"cd {CONTAINER_ROOT} && coverage json -q --data-file=/out/.coverage -o /out/coverage.json"
    )


def ensure_image(target: Target, image: str) -> None:
    probe = subprocess.run(["docker", "image", "inspect", image], capture_output=True, check=False)
    if probe.returncode != 0:
        subprocess.run(["docker", "build", "-q", "-t", image, str(target.env_template)], check=True, timeout=1800)


def run_coverage(target: Target, repo: Path, out_dir: Path, image: str) -> LineMap:
    """one coverage run of the repo suite inside the target image; the suite may fail, the profile still counts."""
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ensure_image(target, image)
    proc = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{out_dir}:/out", image, "bash", "-lc", coverage_command(target)],
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )
    report = out_dir / ("cover.out" if target.language is Language.go else "coverage.json")
    if not report.exists():
        raise RuntimeError(f"coverage run wrote no {report.name}: {(proc.stdout + proc.stderr)[-1500:]}")
    if target.language is Language.go:
        return parse_go(report.read_text(), go_module(repo))
    return parse_python(json.loads(report.read_text()))


def load_or_run(target: Target, repo: Path, out_dir: Path, image: str | None, run: bool) -> LineMap | None:
    """cached by commit; a fresh run only when asked, so map builds stay docker-free by default."""
    cache = cache_path(out_dir, target.commit)
    if cache.exists():
        data: LineMap = json.loads(cache.read_text())
        return data
    if not run:
        return None
    lines = run_coverage(target, repo, out_dir, image or f"incidentforge/{target.name}-env:map")
    cache.write_text(json.dumps(lines, sort_keys=True))
    return lines


def score(executed: list[int], missing: list[int], start: int, end: int, static_tests: int) -> Coverage:
    ran = sum(start <= x <= end for x in executed)
    left = sum(start <= x <= end for x in missing)
    covered = ran > 0
    uncovered = left / (ran + left) if ran + left else (0.0 if covered else 1.0)
    # uncovered lines weigh up to +1, no static test edge another +0.5: range 1.0..2.5
    return Coverage(covered, round(1.0 + uncovered + (0.0 if static_tests else 0.5), 3), static_tests)


def apply(map_path: Path, lines: LineMap | None) -> dict[str, Coverage]:
    """covered/risk_score for every annotated node; real coverage wins over static edges when present."""
    g = Graph(map_path)
    annots = read_annotations(map_path)
    ids = sorted(n for n in annots if n in g.nodes)
    units = sorted({g.unit(n) for n in ids})
    tests = build.transitive_tests_many(map_path, [u for u in units if g.nodes[u].kind != "File"])
    out: dict[str, Coverage] = {}
    for nid in ids:
        unit = g.nodes[g.unit(nid)]
        static = len(tests.get(unit.id, []))
        if lines is None:
            cov = Coverage(static > 0, round(1.0 + (0.0 if static else 1.5), 3), static)
        else:
            info = lines.get(unit.file, {"executed": [], "missing": []})
            cov = score(info["executed"], info["missing"], unit.line_start, unit.line_end, static)
        out[nid] = cov
        a = annots.get(nid, Annotation(nid))
        a.covered, a.risk_score = cov.covered, cov.risk_score
        annots[nid] = a
    write_annotations(map_path, annots.values())
    return out
