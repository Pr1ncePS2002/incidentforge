"""generation loop: surface -> family prompt -> TaskSpec -> write -> validate -> keep/retry. owner: phase 2."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
import tomllib
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from incidentforge.backends.base import Backend
from incidentforge.families import Family, load_family, render_prompt
from incidentforge.models import GateResult, Language, Surface, Target, TaskSpec, ValidationReport

TASK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "instruction": {"type": "string"},
        "solution_patch": {"type": "string"},
        "feature_tests": {"type": "object", "additionalProperties": {"type": "string"}},
        "fault_cases": {"type": "array", "items": {"type": "string"}},
        "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
    },
    "required": ["title", "instruction", "solution_patch", "feature_tests", "fault_cases", "difficulty"],
}
PREFIX = {
    "fail-fast-config": "ff",
    "tolerant-typed-config": "tt",
    "cross-field-validation": "cf",
    "idempotent-consumer": "ic",
    "hot-reload-config": "hr",
    "env-aware-naming": "en",
    "resource-aware-defaults": "rd",
    "config-round-trip": "rt",
}
GOLD_LINES = 140
# a full task (instruction, diff, two test files) overflows the 8k default
OUTPUT_TOKENS = 32000
Writer = Callable[[TaskSpec, Path], Path]
Validator = Callable[[Path], ValidationReport]


def _git(repo: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], input=stdin, capture_output=True, text=True, check=False)


def checkout(target: Target, work_root: Path) -> Path:
    """clone once per commit into work/; reused across runs so surfaces and patch checks are cheap."""
    dest = work_root / "checkouts" / f"{target.name}-{target.commit[:12]}"
    if not (dest / ".git").exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", target.repo_url, str(dest)], check=True)
        subprocess.run(["git", "-C", str(dest), "checkout", "--quiet", target.commit], check=True)
    return dest


def find_target_surfaces(repo: Path, target: Target) -> list[Surface]:
    if target.language is Language.go:
        from incidentforge.surfaces.go import find_go_surfaces

        found: list[Surface] = find_go_surfaces(repo, source_root=target.source_root)
        return found
    from incidentforge.surfaces.python import find_python_surfaces

    return find_python_surfaces(repo, source_root=target.source_root)


def surface_key(s: Surface) -> str:
    return f"{s.file}::{s.symbol}::{s.kind}"


def slugify(text: str, words: int = 4) -> str:
    parts = re.findall(r"[a-z0-9]+", text.lower())
    return "-".join(parts[:words]) or "task"


def gold_example(tasks_root: Path, target: Target) -> str:
    """first hand-written task of this target, trimmed, so the generator imitates an accepted shape."""
    base = tasks_root / target.name
    if not base.exists():
        return "none"
    for d in sorted(base.iterdir()):
        toml = d / "task.toml"
        if not toml.exists() or tomllib.loads(toml.read_text()).get("metadata", {}).get("origin") != "hand-written":
            continue
        instruction = (d / "instruction.md").read_text().split("\n---\n")[0].strip()
        patch = (d / "solution" / "reference.patch").read_text()
        tests = "\n\n".join(
            f"# {p.relative_to(d / 'tests' / 'feature')}\n" + "\n".join(p.read_text().splitlines()[:GOLD_LINES])
            for p in sorted((d / "tests" / "feature").rglob("*"))
            if p.is_file()
        )
        return (
            f"### instruction\n{instruction}\n\n### solution_patch\n```diff\n{patch}```\n\n"
            f"### feature_tests\n```\n{tests}\n```"
        )
    return "none"


@dataclass
class Pair:
    family: Family
    surface: Surface
    task_id: str


@dataclass
class Outcome:
    pair: Pair
    report: ValidationReport
    attempts: int
    title: str = ""
    seconds: float = 0.0


@dataclass
class Generator:
    target: Target
    backend: Backend
    repo: Path
    tasks_root: Path
    work_root: Path
    writer: Writer
    validator: Validator
    gold: str = "none"
    log: Callable[[str], None] = print
    jobs_dir: Path = Path("jobs/validation")
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def log_path(self) -> Path:
        return self.work_root / "generate-log.jsonl"

    def history(self) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text().splitlines() if line.strip()]

    def record(self, row: dict[str, Any]) -> None:
        with self._lock:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a") as fh:
                fh.write(json.dumps(row) + "\n")

    def normalise_patch(self, patch: str) -> str:
        """apply with --recount on the clean checkout and re-diff, so model hunk-count slips do not reject a task."""
        with self._lock:
            try:
                res = _git(self.repo, "apply", "--recount", "--whitespace=nowarn", "-", stdin=patch)
                if res.returncode != 0:
                    raise PatchError(res.stderr.strip()[:600] or "git apply failed")
                # stage only what the patch touches; hook installers drop stray files into fresh clones
                stat = _git(self.repo, "apply", "--recount", "--numstat", "-", stdin=patch).stdout
                paths = [line.split("\t", 2)[2] for line in stat.splitlines() if line.count("\t") >= 2]
                _git(self.repo, "add", "--", *paths)
                diff = _git(self.repo, "diff", "--cached", "--no-color", "--", *paths).stdout
            finally:
                _git(self.repo, "reset", "--hard", "--quiet")
                _git(self.repo, "clean", "-fdq")
        if not diff.strip():
            raise PatchError("patch applies but changes nothing")
        return diff

    def prompt(self, pair: Pair, existing: list[str], previous_failure: str) -> str:
        t = self.target
        target = (
            f"{t.name}: {t.repo_url} at commit {t.commit} ({t.language.value}); application code under "
            f"`{t.source_root}`; repo suite runs with `{t.test_command}`"
        )
        values = {
            "target": target,
            "surface": f"{pair.surface.file}::{pair.surface.symbol} ({pair.surface.kind})",
            "excerpt": pair.surface.excerpt,
            "gold_example": self.gold,
            "previous_failure": previous_failure or "none",
            "existing_tasks": "\n".join(f"- {e}" for e in existing) or "none",
            "task_id": pair.task_id,
        }
        return render_prompt(pair.family, values, language=t.language.value)

    def build_spec(self, pair: Pair, data: dict[str, Any]) -> TaskSpec:
        patch = self.normalise_patch(str(data.get("solution_patch", "")))
        tests = data.get("feature_tests") or {}
        if not any("fault" in body for body in tests.values()):
            raise PatchError("feature tests must include test_fault_<id> tests for the injected faults")
        keys = ("title", "instruction", "feature_tests", "fault_cases")
        fields: dict[str, Any] = {k: data[k] for k in keys if k in data}
        fields["difficulty"] = difficulty(patch, len(data.get("fault_cases") or []))
        return TaskSpec(
            task_id=pair.task_id,
            family=pair.family.slug,
            target=self.target,
            surface=pair.surface,
            solution_patch=patch,
            origin="llm",
            **fields,
        )

    def attempt(self, pair: Pair, existing: list[str], previous_failure: str) -> tuple[ValidationReport, str]:
        """one generate -> check -> write -> validate pass; never raises on a bad candidate."""
        prompt = self.prompt(pair, existing, previous_failure)
        try:
            data = self.backend.generate_json(prompt, TASK_SCHEMA, max_output_tokens=OUTPUT_TOKENS, tag=pair.task_id)
            spec = self.build_spec(pair, data)
        except PatchError as exc:
            return _failed(pair.task_id, "patch_apply", str(exc)), ""
        except ValidationError as exc:
            return _failed(pair.task_id, "spec_schema", str(exc)[:600]), ""
        except Exception as exc:  # noqa: BLE001
            # backend outages and timeouts count as a rejected attempt, the run keeps going
            return _failed(pair.task_id, "generator", f"{type(exc).__name__}: {exc}"[:600]), ""
        task_dir = self.writer(spec, self.tasks_root)
        return self.validator(task_dir), spec.title

    def run_pair(self, pair: Pair, existing: list[str]) -> Outcome:
        start = time.monotonic()
        failure = ""
        report = _failed(pair.task_id, "generator", "not run")
        title = ""
        attempts = 0
        for attempts in (1, 2):
            report, title = self.attempt(pair, existing, failure)
            self.record(
                {
                    "task_id": pair.task_id,
                    "family": pair.family.slug,
                    "surface": surface_key(pair.surface),
                    "attempt": attempts,
                    "accepted": report.accepted,
                    "title": title,
                    "failed_gates": [g.gate for g in report.gates if not g.passed],
                    "detail": "; ".join(g.detail[:300] for g in report.gates if not g.passed),
                    "backend": self.backend.name,
                }
            )
            if report.accepted:
                break
            failure = describe_failure(report) + verifier_excerpt(self.jobs_dir, pair.task_id, report)
        self.settle(pair, report)
        return Outcome(pair, report, attempts, title, time.monotonic() - start)

    def settle(self, pair: Pair, report: ValidationReport) -> None:
        """accepted tasks stay in tasks/; rejected ones move to work/rejected/ with their report."""
        task_dir = self.tasks_root / pair.task_id
        if report.accepted:
            return
        dest = self.work_root / "rejected" / pair.task_id
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if task_dir.exists():
            shutil.move(str(task_dir), str(dest))
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "validation.json").write_text(report.model_dump_json(indent=2))


class PatchError(ValueError):
    """the candidate's patch or tests cannot be packaged."""


def _failed(task_id: str, gate: str, detail: str) -> ValidationReport:
    return ValidationReport(task_id=task_id, accepted=False, gates=[GateResult(gate=gate, passed=False, detail=detail)])


def difficulty(patch: str, faults: int) -> str:
    """measured, not the model's guess: files touched and fault count (agreed with p3)."""
    files = len(re.findall(r"(?m)^diff --git ", patch))
    if files >= 3 or faults >= 4:
        return "hard"
    if files <= 1 and faults <= 2:
        return "easy"
    return "medium"


EXCERPT_LINES = 60


def verifier_excerpt(jobs_dir: Path, task_id: str, report: ValidationReport) -> str:
    """tail of the verifier log behind the failing gate; gate details alone are only reward numbers."""
    bad = {g.gate for g in report.gates if not g.passed}
    if "fail_on_base" in bad:
        agent, log = "nop", "feature_tests.log"
    elif "regression" in bad:
        agent, log = "oracle", "repo_suite.log"
    elif bad & {"pass_on_reference", "flakiness"}:
        agent, log = "oracle", "feature_tests.log"
    else:
        return ""
    slug = task_id.replace("/", "--")
    logs = sorted(jobs_dir.glob(f"{slug}-{agent}-*/**/verifier/{log}"), key=lambda p: p.stat().st_mtime)
    if not logs:
        return ""
    tail = "\n".join(logs[-1].read_text(errors="replace").splitlines()[-EXCERPT_LINES:])
    return f"\n\nlast lines of {log} from the {agent} run:\n```\n{tail}\n```"


def describe_failure(report: ValidationReport) -> str:
    bad = [g for g in report.gates if not g.passed]
    lines = [f"- gate `{g.gate}` failed: {g.detail[:800]}" for g in bad] or ["- rejected without a failing gate"]
    if report.mutants_total and report.mutants_killed == 0:
        lines.append(f"- tests killed 0 of {report.mutants_total} mutants; assert the exact protected behaviour")
    return "the previous candidate was rejected:\n" + "\n".join(lines) + "\nfix these problems in the new candidate."


def next_number(tasks_root: Path, work_root: Path, target: str, prefix: str, taken: set[str]) -> int:
    """highest used number for this prefix across kept, rejected and in-flight ids, plus one."""
    nums = [0]
    for base in (tasks_root / target, work_root / "rejected" / target):
        if base.exists():
            nums += [int(m.group(1)) for d in base.iterdir() if (m := re.match(rf"{prefix}-(\d+)", d.name))]
    nums += [int(m.group(1)) for t in taken if (m := re.match(rf".*/{prefix}-(\d+)", t))]
    return max(nums) + 1


def plan_pairs(
    families: list[Family], surfaces: list[Surface], used: set[tuple[str, str]]
) -> Iterator[tuple[Family, Surface]]:
    """round-robin over families; each family walks its kinds in preference order, skipping used pairs."""
    queues: dict[str, list[Surface]] = {}
    for fam in families:
        rank = {k: i for i, k in enumerate(fam.surface_kinds)}
        cands = [s for s in surfaces if s.kind in rank and (fam.slug, surface_key(s)) not in used]
        queues[fam.slug] = sorted(cands, key=lambda s: rank[s.kind])
    while any(queues.values()):
        for fam in families:
            q = queues[fam.slug]
            if q:
                s = q.pop(0)
                if (fam.slug, surface_key(s)) not in used:
                    used.add((fam.slug, surface_key(s)))
                    yield fam, s


def generate(
    target: Target,
    families: list[str],
    n: int,
    backend: Backend,
    *,
    tasks_root: Path = Path("tasks"),
    work_root: Path = Path("work"),
    writer: Writer | None = None,
    validator: Validator | None = None,
    jobs: int = 2,
    max_pairs: int | None = None,
    log: Callable[[str], None] = print,
) -> list[ValidationReport]:
    """keep generating (family, surface) pairs until n tasks are accepted or pairs run out."""
    from incidentforge.package import write_task
    from incidentforge.validate import validate_task

    write: Writer = writer or write_task
    check: Validator = validator or validate_task
    repo = checkout(target, work_root)
    gold = gold_example(tasks_root, target)
    gen = Generator(target, backend, repo, tasks_root, work_root, write, check, gold, log)
    surfaces = find_target_surfaces(repo, target)
    fams = [load_family(f) for f in families]
    fams = [f for f in fams if target.language.value in f.languages]
    history = gen.history()
    used = {(r["family"], r["surface"]) for r in history}
    # titles are shared per family and file, so a sibling surface in the same class does not repeat a task
    existing: dict[tuple[str, str], list[str]] = {}
    for r in history:
        if r.get("accepted") and r.get("title"):
            existing.setdefault((r["family"], r["surface"].split("::")[0]), []).append(r["title"])
    pairs = plan_pairs(fams, surfaces, used)
    limit = max_pairs if max_pairs is not None else max(3 * n, n + 4)
    log(f"{target.name}: {len(surfaces)} surfaces, families {[f.slug for f in fams]}, want {n} accepted")

    outcomes: list[Outcome] = []
    taken: set[str] = set()
    accepted = 0
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        while accepted < n and len(outcomes) < limit:
            batch: list[Pair] = []
            for fam, s in pairs:
                prefix = PREFIX.get(fam.slug, slugify(fam.slug, 1)[:2])
                num = next_number(tasks_root, work_root, target.name, prefix, taken)
                tid = f"{target.name}/{prefix}-{num:03d}-{slugify(s.symbol.split('.')[-1], 3)}"
                taken.add(tid)
                batch.append(Pair(fam, s, tid))
                if len(batch) >= min(jobs, n - accepted, limit - len(outcomes)):
                    break
            if not batch:
                break
            futures = [
                pool.submit(gen.run_pair, p, list(existing.get((p.family.slug, p.surface.file), []))) for p in batch
            ]
            for fut in futures:
                o = fut.result()
                outcomes.append(o)
                accepted += o.report.accepted
                if o.report.accepted and o.title:
                    existing.setdefault((o.pair.family.slug, o.pair.surface.file), []).append(o.title)
                verdict = "accepted" if o.report.accepted else "rejected"
                log(f"  {o.pair.task_id}: {verdict} after {o.attempts} attempt(s) in {o.seconds:.0f}s {o.title}")

    attempts = sum(o.attempts for o in outcomes)
    rate = accepted / attempts if attempts else 0.0
    log(f"accepted {accepted}/{len(outcomes)} pairs, {attempts} generations, acceptance {rate:.0%} of attempts")
    return [o.report for o in outcomes]
