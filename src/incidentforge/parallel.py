"""parallel generation: one worker per failure-map cluster, a shared docker budget, ids assigned at merge."""

from __future__ import annotations

import fcntl
import json
import math
import os
import re
import shutil
import threading
import time
import tomllib
from collections import deque
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from incidentforge.backends.base import Backend
from incidentforge.failmap.cluster import Cluster
from incidentforge.generate import (
    PatchError,
    Validator,
    family_titles,
    next_number,
    path_lock,
    slugify,
)
from incidentforge.harbor import Trial
from incidentforge.models import Surface, Target, ValidationReport
from incidentforge.validate import GATES, Runner, harbor_runner, validate_task

DEFAULT_MAX_CONTAINERS = 4
# title token overlap at or above this is treated as the same task (D-22: near-duplicates are dropped)
NEAR_DUPLICATE = 0.8
_SLOT_POLL_SEC = 0.05
_DIFF_PATHS = re.compile(r"(?m)^diff --git a/(\S+) b/(\S+)$")
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset({"a", "an", "the", "and", "or", "of", "to", "for", "in", "on", "with", "when", "at", "by"})


def patch_files(patch: str) -> set[str]:
    return {p for m in _DIFF_PATHS.finditer(patch) for p in m.groups()}


class DockerSlots:
    """container budget shared by threads and processes: one flock'd file per slot, taken behind a gate lock."""

    def __init__(self, root: Path, cap: int = DEFAULT_MAX_CONTAINERS) -> None:
        if cap < 1:
            raise ValueError("max containers must be >= 1")
        self.root, self.cap = root, cap
        root.mkdir(parents=True, exist_ok=True)
        self._count = threading.Lock()
        self.in_use = 0
        self.peak = 0

    @classmethod
    def default(cls, cap: int = DEFAULT_MAX_CONTAINERS) -> DockerSlots:
        return cls(Path(os.environ.get("FORGE_DOCKER_SLOTS", ".cache/docker-slots")), cap)

    @contextmanager
    def hold(self, want: int = 1) -> Iterator[int]:
        """block until min(want, cap) slots are free; yields how many were granted."""
        need = max(1, min(want, self.cap))
        with ExitStack() as stack:
            held: list[IO[str]] = []
            gate = stack.enter_context((self.root / "gate.lock").open("a"))
            # only the gate holder takes slots, so two multi-slot holders never deadlock on half a set
            fcntl.flock(gate.fileno(), fcntl.LOCK_EX)
            while len(held) < need:
                for i in range(self.cap):
                    if len(held) == need:
                        break
                    fh = (self.root / f"slot-{i}.lock").open("a")
                    try:
                        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        fh.close()
                        continue
                    held.append(fh)
                    stack.callback(fh.close)
                if len(held) < need:
                    time.sleep(_SLOT_POLL_SEC)
            fcntl.flock(gate.fileno(), fcntl.LOCK_UN)
            with self._count:
                self.in_use += need
                self.peak = max(self.peak, self.in_use)
            try:
                yield need
            finally:
                with self._count:
                    self.in_use -= need


def _concurrency(args: list[str]) -> tuple[int, int | None]:
    """containers a harbor job may start at once (its -n value) and where that value sits in args."""
    for i, a in enumerate(args[:-1]):
        if a in ("-n", "--n-concurrent"):
            return int(args[i + 1]), i + 1
    return 1, None


def capped_runner(run: Runner, slots: DockerSlots) -> Runner:
    """every harbor job takes slots first; a wide job (the mutation gate's -n 4) is narrowed to what it got."""

    def capped(task_path: Path, agent: str, job_name: str, extra_args: list[str]) -> list[Trial]:
        want, at = _concurrency(extra_args)
        with slots.hold(want) as got:
            args = list(extra_args)
            if at is not None:
                args[at] = str(got)
            return run(task_path, agent, job_name, args)

    return capped


def make_validator(
    slots: DockerSlots,
    *,
    jobs_dir: Path = Path("jobs/validation"),
    reports_dir: Path = Path("reports/validation"),
    runner: Runner | None = None,
    gates: tuple[str, ...] = GATES,
) -> Validator:
    """the usual six gates, with every harbor job inside the shared container budget."""
    run = capped_runner(runner or harbor_runner(jobs_dir.resolve()), slots)

    def check(task_dir: Path) -> ValidationReport:
        return validate_task(task_dir, gates, jobs_dir=jobs_dir, reports_dir=reports_dir, runner=run)

    return check


def _tokens(title: str) -> set[str]:
    return {w for w in _WORD.findall(title.lower()) if w not in _STOP}


def near_duplicate(title: str, existing: list[str], threshold: float = NEAR_DUPLICATE) -> str | None:
    """the first kept title whose word set overlaps this one by at least threshold (jaccard)."""
    mine = _tokens(title)
    for other in existing:
        theirs = _tokens(other)
        union = mine | theirs
        if union and len(mine & theirs) / len(union) >= threshold:
            return other
    return None


def kept_titles(tasks_root: Path, target: str, family: str, peers: tuple[Path, ...] = ()) -> list[str]:
    """kept titles of the family here and in peer tasks roots (other worktrees generating the same target)."""
    return [t for root in (tasks_root, *peers) for t in family_titles(root, target, family)]


def merge_lock_path(tasks_root: Path, target: str) -> Path:
    # beside the target dir, not inside it, so harbor never sees it as a task
    return tasks_root / f".{target}.merge.lock"


@contextmanager
def merge_lock(tasks_root: Path, target: str) -> Iterator[None]:
    """exclusive cross-process lock over tasks/<target>/ (same pattern as the spend ledger, D-47)."""
    path = merge_lock_path(tasks_root, target)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _meta(task_dir: Path) -> dict[str, object]:
    meta: dict[str, object] = tomllib.loads((task_dir / "task.toml").read_text()).get("metadata", {})
    return meta


@dataclass
class Merged:
    task_id: str | None  # final id, none when dropped as a near-duplicate
    duplicate_of: str | None = None


def merge_task(
    staged: Path,
    *,
    target: str,
    prefix: str,
    slug: str,
    tasks_root: Path,
    work_root: Path,
    reports_dir: Path = Path("reports/validation"),
    peers: tuple[Path, ...] = (),
) -> Merged:
    """move one accepted staged task into tasks/<target>/ under the next free number for its prefix."""
    meta = _meta(staged)
    title, family = str(meta.get("title", "")), str(meta.get("family", ""))
    staged_id = f"{target}/{staged.name}"
    with merge_lock(tasks_root, target):
        dup = near_duplicate(title, kept_titles(tasks_root, target, family, peers))
        if dup is not None:
            dest = work_root / "duplicates" / target / staged.name
            if dest.exists():
                shutil.rmtree(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staged), str(dest))
            return Merged(None, dup)
        # numbers kept in a peer worktree count too, so two branches never ship the same id
        nums = [next_number(p, p / ".none", target, prefix, set()) for p in peers]
        num = max([next_number(tasks_root, work_root, target, prefix, set()), *nums])
        final = f"{prefix}-{num:03d}-{slug}"
        dest = tasks_root / target / final
        dest.parent.mkdir(parents=True, exist_ok=True)
        # one rename, so an unlocked reader sees the whole task or nothing
        os.rename(staged, dest)
        old_report = reports_dir / f"{staged_id}.json"
        if old_report.exists():
            report = ValidationReport.model_validate_json(old_report.read_text())
            new_report = reports_dir / target / f"{final}.json"
            renamed = report.model_copy(update={"task_id": f"{target}/{final}"})
            new_report.write_text(renamed.model_dump_json(indent=2) + "\n")
            old_report.unlink()
    return Merged(f"{target}/{final}")


@dataclass
class ClusterJob:
    cluster: Cluster
    surfaces: list[Surface]
    families: list[str]


def plan_jobs(clusters: list[Cluster], ranked: list[Surface], families: list[str]) -> list[ClusterJob]:
    """clusters that hold a ranked surface and a wanted family, riskiest first; files never shared."""
    owner = {f: c for c in clusters for f in c.files}
    by_cluster: dict[str, list[Surface]] = {}
    order: list[Cluster] = []
    for s in ranked:
        c = owner.get(s.file)
        if c is None:
            continue
        if c.id not in by_cluster:
            by_cluster[c.id] = []
            order.append(c)
        by_cluster[c.id].append(s)
    jobs = []
    for c in order:
        fams = [f for f in families if f in c.families]
        if fams:
            jobs.append(ClusterJob(c, by_cluster[c.id], fams))
    return jobs


@dataclass
class RunState:
    """what workers share: the docker budget, file ownership and the merge counters."""

    target: Target
    tasks_root: Path
    work_root: Path
    reports_dir: Path
    clusters: list[Cluster]
    slots: DockerSlots
    peers: tuple[Path, ...] = ()
    _lock: threading.Lock = field(default_factory=threading.Lock)
    owner: dict[str, str] = field(default_factory=dict)  # file -> cluster id that may edit it
    edited: dict[str, str] = field(default_factory=dict)  # file -> merged task id that edits it

    def __post_init__(self) -> None:
        self.owner = {f: c.id for c in self.clusters for f in c.files}

    def claim(self, cluster_id: str, patch: str) -> None:
        """a patch may edit its own cluster's files or files no cluster owns yet; the first claim wins."""
        files = patch_files(patch)
        with self._lock:
            taken = sorted(f for f in files if f in self.edited)
            if taken:
                raise PatchError(f"files already edited by another task in this run: {taken}; leave them unchanged")
            foreign = sorted(f for f in files if self.owner.get(f, cluster_id) != cluster_id)
            if foreign:
                mine = sorted(f for f, c in self.owner.items() if c == cluster_id)
                raise PatchError(f"edit only these files or new ones: {mine}; not {foreign} (another worker owns them)")
            for f in files:
                self.owner[f] = cluster_id

    def mark_edited(self, task_id: str, patch: str) -> None:
        with self._lock:
            for f in patch_files(patch):
                self.edited[f] = task_id


@dataclass
class ClusterScope:
    """generate.Scope for one cluster: its surfaces only, provisional ids, titles read under the merge lock."""

    job: ClusterJob
    state: RunState
    tasks_root: Path
    surfaces: list[Surface] = field(default_factory=list)
    names: dict[str, tuple[str, str]] = field(default_factory=dict)  # provisional id -> (prefix, slug)

    def __post_init__(self) -> None:
        self.surfaces = list(self.job.surfaces)

    def task_id(self, prefix: str, surface: Surface) -> str:
        slug = slugify(surface.symbol.split(".")[-1], 3)
        # provisional, never a final number: ids are handed out once, at merge
        tid = f"{self.state.target.name}/{prefix}-{self.job.cluster.id}-{len(self.names) + 1:02d}-{slug}"
        self.names[tid] = (prefix, slug)
        return tid

    def titles(self, family: str) -> list[str]:
        with merge_lock(self.tasks_root, self.state.target.name):
            return kept_titles(self.tasks_root, self.state.target.name, family, self.state.peers)

    def check_patch(self, patch: str) -> None:
        self.state.claim(self.job.cluster.id, patch)


def _log_merge(work_root: Path, row: dict[str, object]) -> None:
    path = work_root / "merge-log.jsonl"
    with path_lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(json.dumps(row) + "\n")


def run_parallel(
    target: Target,
    families: list[str],
    n: int,
    backend: Backend,
    *,
    map_path: Path,
    workers: int = 4,
    max_containers: int = DEFAULT_MAX_CONTAINERS,
    tasks_root: Path = Path("tasks"),
    work_root: Path = Path("work"),
    reports_dir: Path = Path("reports/validation"),
    validator: Validator | None = None,
    slots: DockerSlots | None = None,
    seed: int = 0,
    skip_files: tuple[str, ...] = (),
    peers: tuple[Path, ...] = (),
    log: Callable[[str], None] = print,
) -> list[ValidationReport]:
    """riskiest clusters first, one worker per cluster, at most one live job per cluster, n merged tasks."""
    from incidentforge.failmap.cluster import clusters as load_clusters
    from incidentforge.failmap.pipeline import annotate_surfaces
    from incidentforge.families import load_family
    from incidentforge.families.sampling import rank_surfaces
    from incidentforge.generate import checkout, find_target_surfaces, generate

    repo = checkout(target, work_root)
    ranked = rank_surfaces(annotate_surfaces(find_target_surfaces(repo, target), map_path), seed)
    fams = [f for f in families if target.language.value in load_family(f).languages]
    cl = load_clusters(map_path)
    # clusters holding a skipped file are left to whoever else is working on that code
    jobs = [j for j in plan_jobs(cl, ranked, fams) if not set(j.cluster.files) & set(skip_files)]
    slots = slots or DockerSlots.default(max_containers)
    state = RunState(target, tasks_root, work_root, reports_dir, cl, slots, peers)
    if validator is None:
        from incidentforge.validate.mutation import repo_checkout

        # the mutation gate clones on first use; do it once here, not racing in every worker
        repo_checkout(target)
    check = validator or make_validator(slots, reports_dir=reports_dir)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log(
        f"{target.name}: {len(ranked)} surfaces in {len(jobs)} usable clusters of {len(cl)}, "
        f"{workers} workers, {slots.cap} containers, want {n} accepted"
    )
    if not jobs:
        return []

    # a cluster may come round again when n exceeds the clusters, but only once its last job ended
    rounds = math.ceil(n / len(jobs))
    queue: deque[ClusterJob] = deque(j for _ in range(rounds) for j in jobs)
    busy: set[str] = set()
    dead: set[str] = set()
    guard = threading.Condition()
    counts = {"accepted": 0, "inflight": 0}
    results: list[ValidationReport] = []

    def take() -> ClusterJob | None:
        with guard:
            while True:
                if counts["accepted"] + counts["inflight"] >= n:
                    if counts["inflight"] == 0:
                        return None
                    guard.wait()
                    continue
                live = [j for j in queue if j.cluster.id not in dead]
                if not live:
                    return None
                pick = next((j for j in live if j.cluster.id not in busy), None)
                if pick is None:
                    guard.wait()
                    continue
                queue.remove(pick)
                busy.add(pick.cluster.id)
                counts["inflight"] += 1
                return pick

    def one(job: ClusterJob) -> list[ValidationReport]:
        cid = job.cluster.id
        scope = ClusterScope(job, state, tasks_root)
        staging = work_root / "staging" / stamp / cid

        def say(msg: str) -> None:
            log(f"[{cid}] {msg}")

        reports = generate(
            target,
            job.families,
            1,
            backend,
            tasks_root=staging,
            work_root=work_root,
            validator=check,
            jobs=1,
            log=say,
            scope=scope,
        )
        out: list[ValidationReport] = []
        for r in reports:
            if not r.accepted:
                out.append(r)
                continue
            prefix, slug = scope.names[r.task_id]
            staged = staging / r.task_id
            patch = (staged / "solution" / "reference.patch").read_text()
            m = merge_task(
                staged,
                target=target.name,
                prefix=prefix,
                slug=slug,
                tasks_root=tasks_root,
                work_root=work_root,
                reports_dir=reports_dir,
                peers=peers,
            )
            _log_merge(work_root, {"staged": r.task_id, "task_id": m.task_id, "duplicate_of": m.duplicate_of})
            if m.task_id is None:
                say(f"{r.task_id}: dropped as a near-duplicate of {m.duplicate_of!r}")
                out.append(r.model_copy(update={"accepted": False}))
                continue
            state.mark_edited(m.task_id, patch)
            say(f"{r.task_id} merged as {m.task_id}")
            out.append(r.model_copy(update={"task_id": m.task_id}))
        return out

    def worker() -> None:
        while (job := take()) is not None:
            got: list[ValidationReport] = []
            try:
                got = one(job)
            finally:
                ok = sum(r.accepted for r in got)
                with guard:
                    results.extend(got)
                    counts["accepted"] += ok
                    counts["inflight"] -= 1
                    busy.discard(job.cluster.id)
                    if not ok:
                        # nothing left that this cluster can give; later rounds skip it
                        dead.add(job.cluster.id)
                    guard.notify_all()

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for fut in [pool.submit(worker) for _ in range(max(1, workers))]:
            fut.result()
    log(f"merged {counts['accepted']}/{n} tasks; peak containers {slots.peak}/{slots.cap}")
    return results
