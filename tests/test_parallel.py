"""parallel workers: docker slot pool, merge lock and id assignment, cluster scoping, cli fallback."""

import json
import multiprocessing as mp
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from incidentforge import parallel
from incidentforge.cli import app
from incidentforge.failmap.cluster import Cluster
from incidentforge.generate import PatchError, generate
from incidentforge.harbor import Trial
from incidentforge.models import GateResult, Language, Surface, Target, ValidationReport
from incidentforge.parallel import (
    DockerSlots,
    RunState,
    capped_runner,
    make_validator,
    merge_task,
    near_duplicate,
    patch_files,
    plan_jobs,
    run_parallel,
)

FILES = ("backend/app/a.py", "backend/app/b.py", "backend/app/c.py")
CONFIG = 'from pydantic_settings import BaseSettings\n\n\nclass Settings(BaseSettings):\n    NAME: str = "x"\n'
TESTS = {"test_forge_x.py": "def test_fault_missing():\n    assert True\n"}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def _ctx() -> mp.context.BaseContext:
    # spawn: earlier tests leave worker threads behind, and fork from a threaded process can deadlock
    return mp.get_context("spawn")


@pytest.fixture
def target(tmp_path: Path) -> Target:
    repo = tmp_path / "upstream"
    for f in FILES:
        (repo / f).parent.mkdir(parents=True, exist_ok=True)
        (repo / f).write_text(CONFIG)
    _git(repo.parent, "init", "-q", str(repo))
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    env = tmp_path / "env"
    env.mkdir()
    (env / "Dockerfile").write_text("FROM scratch\nARG REPO_URL=x\nARG REPO_COMMIT=y\n")
    return Target(
        name="fixture",
        repo_url=str(repo),
        commit=_git(repo, "rev-parse", "HEAD").strip(),
        licence="MIT",
        language=Language.python,
        env_template=env,
        test_command="run_tests -q tests/",
        source_root="backend",
    )


def patch_for(target: Target, *files: str, line: str = "    STRICT: bool = True\n") -> str:
    repo = Path(target.repo_url)
    for f in files:
        p = repo / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text((p.read_text() if p.exists() else CONFIG) + line)
    _git(repo, "add", "-N", ".")
    diff = _git(repo, "diff")
    _git(repo, "reset", "-q")
    _git(repo, "checkout", "--", ".")
    _git(repo, "clean", "-fdq")
    return diff


def answer(patch: str, title: str) -> dict[str, Any]:
    return {
        "title": title,
        "instruction": "add a strict flag",
        "solution_patch": patch,
        "feature_tests": TESTS,
        "fault_cases": ["missing: STRICT unset"],
        "difficulty": "easy",
    }


class FileBackend:
    """answers by the surface file named in the prompt; thread safe."""

    name = "replay"

    def __init__(self, answers: dict[str, list[dict[str, Any]]]) -> None:
        self.answers = answers
        self.prompts: list[str] = []
        self._lock = threading.Lock()

    def generate_json(
        self, prompt: str, schema: dict[str, Any], max_output_tokens: int = 8192, tag: str = ""
    ) -> dict[str, Any]:
        file = re.search(r"(backend/app/\w+\.py)::", prompt)
        assert file is not None
        with self._lock:
            self.prompts.append(prompt)
            queue = self.answers[file.group(1)]
            return dict(queue.pop(0) if len(queue) > 1 else queue[0])


class Gauge:
    """fake harbor: every trial passes the gates it is asked for; records container concurrency."""

    def __init__(self, sleep: float = 0.02) -> None:
        self.sleep, self.live, self.peak, self.calls = sleep, 0, 0, []
        self._lock = threading.Lock()

    def __call__(self, task_path: Path, agent: str, job_name: str, extra_args: list[str]) -> list[Trial]:
        n = int(extra_args[extra_args.index("-n") + 1]) if "-n" in extra_args else 1
        with self._lock:
            self.live += n
            self.peak = max(self.peak, self.live)
            self.calls.append((agent, list(extra_args)))
        time.sleep(self.sleep)
        with self._lock:
            self.live -= n
        if agent == "nop":
            rewards = {"reward": 0.0, "feature_tests": 0.0, "repo_suite": 1.0}
        else:
            rewards = {"reward": 1.0, "feature_tests": 1.0, "repo_suite": 1.0}
        k = int(extra_args[extra_args.index("-k") + 1]) if "-k" in extra_args else 1
        return [Trial(task_path.name, f"t{i}", task_path, rewards) for i in range(k)]


def clusters_for(*groups: tuple[str, ...], fams: tuple[str, ...] = ("fail-fast-config",)) -> list[Cluster]:
    return [Cluster(f"c{i:03d}", (g[0],), (g[0],), g, ("app",), fams) for i, g in enumerate(groups, 1)]


def use_map(monkeypatch: pytest.MonkeyPatch, cl: list[Cluster]) -> None:
    monkeypatch.setattr("incidentforge.failmap.cluster.clusters", lambda _p, *a: cl)
    monkeypatch.setattr("incidentforge.failmap.pipeline.annotate_surfaces", lambda s, _p: list(s))


def test_patch_files() -> None:
    p = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\ndiff --git a/old.py b/new.py\n"
    assert patch_files(p) == {"x.py", "old.py", "new.py"}


def test_slots_cap_threads_and_wide_jobs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    slots = DockerSlots(tmp_path / "slots", cap=3)
    live, peak = [0], [0]
    lock = threading.Lock()

    def hold(want: int) -> None:
        with slots.hold(want) as got:
            assert got == min(want, 3)
            with lock:
                live[0] += got
                peak[0] = max(peak[0], live[0])
            time.sleep(0.01)
            with lock:
                live[0] -= got

    threads = [threading.Thread(target=hold, args=(w,)) for w in (1, 2, 4, 1, 3, 2, 1, 1) * 2]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert peak[0] <= 3 and slots.peak <= 3 and slots.in_use == 0
    with pytest.raises(ValueError):
        DockerSlots(tmp_path / "x", cap=0)
    monkeypatch.setenv("FORGE_DOCKER_SLOTS", str(tmp_path / "env-slots"))
    assert DockerSlots.default(2).root == tmp_path / "env-slots"


def _slot_proc(root: str, cap: int, log: str, want: int) -> None:
    slots = DockerSlots(Path(root), cap)
    for _ in range(4):
        with slots.hold(want) as got:
            start = time.time()
            time.sleep(0.01)
            with open(log, "a") as fh:
                fh.write(json.dumps([start, time.time(), got]) + "\n")


def test_slots_cap_across_processes(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    ctx = _ctx()
    procs = [ctx.Process(target=_slot_proc, args=(str(tmp_path / "s"), 2, str(log), w)) for w in (1, 2, 1, 1, 2)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    spans = [json.loads(x) for x in log.read_text().splitlines()]
    assert len(spans) == 20
    # at every start instant the slots held by overlapping spans stay within the cap
    for s, _e, _g in spans:
        assert sum(g for a, b, g in spans if a <= s < b) <= 2


def test_capped_runner_narrows_mutation_width(tmp_path: Path) -> None:
    gauge = Gauge(sleep=0)
    run = capped_runner(gauge, DockerSlots(tmp_path / "s", cap=2))
    run(tmp_path, "oracle", "j", ["-n", "4"])
    run(tmp_path, "oracle", "j", ["-k", "2", "-n", "2"])
    run(tmp_path, "nop", "j", [])
    assert [c[1] for c in gauge.calls] == [["-n", "2"], ["-k", "2", "-n", "2"], []]


def test_validator_shares_the_cap_with_the_gates(tmp_path: Path) -> None:
    gauge = Gauge()
    slots = DockerSlots(tmp_path / "s", cap=2)
    check = make_validator(
        slots,
        jobs_dir=tmp_path / "jobs",
        reports_dir=tmp_path / "reports",
        runner=gauge,
        gates=("fail_on_base", "pass_on_reference", "regression", "flakiness"),
    )
    dirs = []
    for i in range(4):
        d = tmp_path / "tasks" / "fixture" / f"t{i}"
        d.mkdir(parents=True)
        dirs.append(d)
    out: list[ValidationReport] = []
    threads = [threading.Thread(target=lambda d=d: out.append(check(d))) for d in dirs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert all(r.accepted for r in out) and len(out) == 4
    assert gauge.peak <= 2
    assert (tmp_path / "reports" / "fixture" / "t0.json").exists()


def stage(root: Path, target: str, name: str, title: str, family: str = "fail-fast-config") -> Path:
    d = root / target / name
    d.mkdir(parents=True)
    (d / "task.toml").write_text(f'[metadata]\ntitle = "{title}"\nfamily = "{family}"\n')
    return d


def _merge_proc(root: str, worker: int, count: int, start: Any) -> None:
    base = Path(root)
    start.wait()
    for k in range(count):
        name = f"ff-c{worker:03d}-{k:02d}-x"
        staged = stage(base / "staging" / str(worker), "fixture", name, f"title{worker}x{k} unique{worker * 100 + k}")
        report = base / "reports" / "fixture" / f"{name}.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(ValidationReport(task_id=f"fixture/{name}", accepted=True, gates=[]).model_dump_json())
        m = merge_task(
            staged,
            target="fixture",
            prefix="ff",
            slug="x",
            tasks_root=base / "tasks",
            work_root=base / "work",
            reports_dir=base / "reports",
        )
        assert m.task_id is not None


def test_concurrent_merges_assign_each_number_once(tmp_path: Path) -> None:
    # a kept task and a rejected one already hold numbers
    (tmp_path / "tasks" / "fixture" / "ff-001-gold").mkdir(parents=True)
    (tmp_path / "work" / "rejected" / "fixture" / "ff-002-bad").mkdir(parents=True)
    ctx = _ctx()
    start = ctx.Event()
    procs = [ctx.Process(target=_merge_proc, args=(str(tmp_path), w, 5, start)) for w in range(6)]
    for p in procs:
        p.start()
    start.set()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    names = sorted(d.name for d in (tmp_path / "tasks" / "fixture").iterdir())
    nums = sorted(int(n.split("-")[1]) for n in names)
    assert nums == list(range(1, 2)) + list(range(3, 33))
    reports = sorted((tmp_path / "reports" / "fixture").iterdir())
    assert len(reports) == 30 and all(re.match(r"ff-\d{3}-x\.json$", r.name) for r in reports)
    ids = {json.loads(r.read_text())["task_id"] for r in reports}
    assert ids == {f"fixture/{n}" for n in names if n != "ff-001-gold"}
    assert not (tmp_path / "tasks" / ".fixture.merge.lock").read_text()


def test_near_duplicate_is_dropped_at_merge(tmp_path: Path) -> None:
    assert near_duplicate("Fail fast on a missing SMTP host", ["fail fast on missing smtp host"]) is not None
    assert near_duplicate("strict pool size", ["fail fast on missing smtp host"]) is None
    assert near_duplicate("", [""]) is None
    tasks = tmp_path / "tasks"
    kept = stage(tasks, "fixture", "ff-001-smtp", "fail fast on missing smtp host")
    assert kept.exists()
    staged = stage(tmp_path / "staging", "fixture", "ff-c001-01-smtp", "Fail fast when the SMTP host is missing")
    m = merge_task(staged, target="fixture", prefix="ff", slug="smtp", tasks_root=tasks, work_root=tmp_path / "w")
    assert m.task_id is None and m.duplicate_of == "fail fast on missing smtp host"
    assert (tmp_path / "w" / "duplicates" / "fixture" / "ff-c001-01-smtp" / "task.toml").exists()
    # same title in another family is not a duplicate; a stale duplicate copy is replaced
    other = stage(tmp_path / "staging2", "fixture", "ff-c001-01-smtp", "fail fast on missing smtp host", "x")
    m2 = merge_task(other, target="fixture", prefix="ff", slug="smtp", tasks_root=tasks, work_root=tmp_path / "w")
    assert m2.task_id == "fixture/ff-002-smtp"
    again = stage(tmp_path / "staging3", "fixture", "ff-c001-01-smtp", "fail fast on missing smtp host")
    assert (
        merge_task(again, target="fixture", prefix="ff", slug="s", tasks_root=tasks, work_root=tmp_path / "w").task_id
        is None
    )


def test_plan_jobs_never_shares_files() -> None:
    cl = clusters_for(("a.py",), ("b.py", "b2.py"), ("c.py",), fams=("fail-fast-config",))
    cl[2] = Cluster("c003", ("c.py",), ("c.py",), ("c.py",), ("app",), ("idempotent-consumer",))
    ranked = [
        Surface(file="b2.py", symbol="S", kind="settings-class"),
        Surface(file="a.py", symbol="S", kind="settings-class"),
        Surface(file="zzz.py", symbol="S", kind="settings-class"),
        Surface(file="b.py", symbol="T", kind="settings-class"),
        Surface(file="c.py", symbol="S", kind="consumer"),
    ]
    jobs = plan_jobs(cl, ranked, ["fail-fast-config"])
    assert [j.cluster.id for j in jobs] == ["c002", "c001"]
    assert [s.file for s in jobs[0].surfaces] == ["b2.py", "b.py"]
    seen: set[str] = set()
    for j in jobs:
        assert not seen & set(j.cluster.files)
        seen |= set(j.cluster.files)
        assert {s.file for s in j.surfaces} <= set(j.cluster.files)


def test_claims_keep_workers_on_their_own_files(target: Target, tmp_path: Path) -> None:
    state = RunState(target, tmp_path, tmp_path, tmp_path, clusters_for(*[(f,) for f in FILES]), DockerSlots(tmp_path))
    state.claim("c001", patch_for(target, FILES[0], "backend/app/new.py"))
    with pytest.raises(PatchError, match="another worker owns"):
        state.claim("c002", patch_for(target, FILES[1], "backend/app/new.py"))
    with pytest.raises(PatchError, match="another worker owns"):
        state.claim("c002", patch_for(target, FILES[0]))
    state.mark_edited("fixture/ff-001-x", patch_for(target, FILES[0]))
    with pytest.raises(PatchError, match="already edited"):
        state.claim("c001", patch_for(target, FILES[0]))


def run_fixture(
    target: Target, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: FileBackend, **kw: Any
) -> tuple[list[ValidationReport], Gauge, DockerSlots]:
    cl = kw.pop("clusters", clusters_for(*[(f,) for f in FILES]))
    if cl is not None:
        use_map(monkeypatch, cl)
    gauge = Gauge()
    slots = DockerSlots(tmp_path / "slots", cap=kw.pop("cap", 2))
    check = make_validator(
        slots,
        jobs_dir=tmp_path / "jobs",
        reports_dir=tmp_path / "reports",
        runner=gauge,
        gates=("leak", "fail_on_base", "pass_on_reference", "regression", "flakiness"),
    )
    reports = run_parallel(
        target,
        ["fail-fast-config"],
        kw.pop("n", 3),
        backend,
        map_path=tmp_path / "map.sqlite",
        workers=kw.pop("workers", 3),
        tasks_root=tmp_path / "tasks",
        work_root=tmp_path / "work",
        reports_dir=tmp_path / "reports",
        validator=check,
        slots=slots,
        log=lambda _m: None,
        **kw,
    )
    return reports, gauge, slots


def test_parallel_run_merges_one_task_per_cluster(
    target: Target, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = FileBackend({f: [answer(patch_for(target, f), f"strict flag in {f[-4]}")] for f in FILES})
    reports, gauge, slots = run_fixture(target, tmp_path, monkeypatch, backend)
    assert sorted(r.task_id for r in reports if r.accepted) == [f"fixture/ff-00{i}-settings" for i in (1, 2, 3)]
    tasks = sorted((tmp_path / "tasks" / "fixture").iterdir())
    edited = [patch_files((t / "solution" / "reference.patch").read_text()) for t in tasks]
    assert len(set().union(*edited)) == sum(len(e) for e in edited) == 3
    assert gauge.peak <= 2 and slots.peak <= 2
    assert all("-c00" not in t.name for t in tasks)
    for t in tasks:
        report = json.loads((tmp_path / "reports" / "fixture" / f"{t.name}.json").read_text())
        assert report["task_id"] == f"fixture/{t.name}"
    # the prompt carried a provisional id, never a final number
    assert all(re.search(r"Task id: fixture/ff-c00\d-01-settings", p) for p in backend.prompts)
    merges = [json.loads(x) for x in (tmp_path / "work" / "merge-log.jsonl").read_text().splitlines()]
    assert len(merges) == 3 and all(m["staged"].startswith("fixture/ff-c00") for m in merges)


def test_parallel_run_rejects_cross_cluster_edits_and_shares_titles(
    target: Target, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = FILES[0], FILES[1]
    # c002's first answer edits c001's file: refused with feedback, the retry stays home
    backend = FileBackend(
        {
            a: [answer(patch_for(target, a), "strict flag a")],
            b: [answer(patch_for(target, a, b), "strict flag b"), answer(patch_for(target, b), "strict flag b")],
        }
    )
    reports, _g, _s = run_fixture(
        target, tmp_path, monkeypatch, backend, clusters=clusters_for((a,), (b,)), n=2, workers=1
    )
    assert sum(r.accepted for r in reports) == 2
    # whichever cluster ran first, the edit to a.py is refused once and the reason is fed back
    retry = [p for p in backend.prompts if "another worker owns" in p or "already edited" in p]
    assert len(retry) == 1 and "backend/app/a.py" in retry[0]
    # the second worker's prompt lists the title the first merged
    assert "- strict flag a" in backend.prompts[-1] or "- strict flag b" in backend.prompts[-1]


def test_parallel_run_stops_when_clusters_run_dry(
    target: Target, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = FILES[0]
    # n above the cluster count: the second round may only add new files, and this answer edits a.py again
    backend = FileBackend({f: [answer(patch_for(target, a), "strict flag")] for f in FILES})
    twin = Surface(file=a, symbol="Settings.NAME", kind="settings-class")
    monkeypatch.setattr("incidentforge.failmap.pipeline.annotate_surfaces", lambda s, _p: [*s, twin])
    monkeypatch.setattr("incidentforge.failmap.cluster.clusters", lambda _p, *x: clusters_for((a,)))
    reports, _g, _s = run_fixture(target, tmp_path, monkeypatch, backend, clusters=None, n=2)
    assert sum(r.accepted for r in reports) == 1
    assert any(g.detail.startswith("files already edited") for r in reports for g in r.gates)


def test_parallel_run_drops_merge_duplicates_and_handles_no_jobs(
    target: Target, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage(tmp_path / "tasks", "fixture", "ff-009-old", "strict flag")
    backend = FileBackend({f: [answer(patch_for(target, f), "strict flag")] for f in FILES})
    reports, _g, _s = run_fixture(target, tmp_path, monkeypatch, backend, clusters=clusters_for((FILES[0],)), n=1)
    assert [r.accepted for r in reports] == [False]
    assert (tmp_path / "work" / "duplicates" / "fixture" / "ff-c001-01-settings").exists()
    none, _g, _s = run_fixture(target, tmp_path, monkeypatch, backend, clusters=clusters_for(("other.py",)))
    assert none == []


def test_worker_crash_surfaces_after_others_finish(
    target: Target, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: Any, **_k: Any) -> list[ValidationReport]:
        raise RuntimeError("worker died")

    monkeypatch.setattr("incidentforge.generate.generate", boom)
    with pytest.raises(RuntimeError, match="worker died"):
        run_fixture(target, tmp_path, monkeypatch, FileBackend({}))


def _tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class AcceptAll:
    def __call__(self, task_dir: Path) -> ValidationReport:
        gate = GateResult(gate="leak", passed=True)
        return ValidationReport(task_id=f"{task_dir.parent.name}/{task_dir.name}", accepted=True, gates=[gate])


def cli_env(monkeypatch: pytest.MonkeyPatch, target: Target, backend: FileBackend) -> None:
    monkeypatch.setattr("incidentforge.targets.load_target", lambda _n: target)
    monkeypatch.setattr("incidentforge.backends.base.get_backend", lambda _n: backend)
    monkeypatch.setattr("incidentforge.validate.validate_task", AcceptAll())


def test_workers_1_is_byte_identical_to_the_old_call(
    target: Target, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = {f: [answer(patch_for(target, f), f"strict flag in {f[-4]}")] for f in FILES}
    cli_env(monkeypatch, target, FileBackend(json.loads(json.dumps(answers))))
    new = tmp_path / "new"
    (new / "work" / "fixture").mkdir(parents=True)
    # a map is present, yet one worker must not take the parallel path
    (new / "work" / "fixture" / "map.sqlite").write_text("")
    monkeypatch.setattr(parallel, "run_parallel", lambda *_a, **_k: pytest.fail("parallel path used"))
    monkeypatch.chdir(new)
    res = CliRunner().invoke(app, ["run", "--target", "fixture", "--family", "fail-fast-config", "--n", "2"])
    assert res.exit_code == 0, res.output
    old = tmp_path / "old"
    old.mkdir()
    monkeypatch.chdir(old)
    generate(target, ["fail-fast-config"], 2, FileBackend(answers), tasks_root=Path("tasks"), log=lambda _m: None)
    assert _tree(new / "tasks") == _tree(old / "tasks") != {}
    # two pairs validate at once (jobs=2), so log rows may land in either order
    rows = [sorted((d / "work" / "generate-log.jsonl").read_text().splitlines()) for d in (new, old)]
    assert rows[0] == rows[1] != []


def test_cli_workers_use_the_map_or_fall_back(target: Target, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    answers = {f: [answer(patch_for(target, f), f"strict flag in {f[-4]}")] for f in FILES}
    cli_env(monkeypatch, target, FileBackend(answers))
    monkeypatch.chdir(tmp_path)
    args = ["run", "--target", "fixture", "--family", "fail-fast-config", "--n", "1", "--workers", "4"]
    res = CliRunner().invoke(app, args)
    assert res.exit_code == 0 and "no failure map" in res.output
    seen: dict[str, Any] = {}

    def fake(*a: Any, **k: Any) -> list[ValidationReport]:
        seen.update(k)
        return [ValidationReport(task_id="fixture/ff-002-x", accepted=True, gates=[])]

    monkeypatch.setattr(parallel, "run_parallel", fake)
    (tmp_path / "work" / "fixture").mkdir(parents=True, exist_ok=True)
    (tmp_path / "work" / "fixture" / "map.sqlite").write_text("")
    extra = ["--max-containers", "3", "--skip-file", "backend/app/core/db.py", "--peer-tasks", "../wt/tasks"]
    res = CliRunner().invoke(app, [*args, *extra])
    assert res.exit_code == 0, res.output
    assert seen["workers"] == 4 and seen["max_containers"] == 3
    assert seen["skip_files"] == ("backend/app/core/db.py",) and seen["peers"] == (Path("../wt/tasks"),)


def test_default_validator_clones_the_mutation_repo_once_up_front(
    target: Target, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cloned: list[str] = []
    monkeypatch.setattr("incidentforge.validate.mutation.repo_checkout", lambda t: cloned.append(t.name))
    use_map(monkeypatch, clusters_for(("other.py",)))
    out = run_parallel(
        target,
        ["fail-fast-config"],
        1,
        FileBackend({}),
        map_path=tmp_path / "map.sqlite",
        tasks_root=tmp_path / "tasks",
        work_root=tmp_path / "work",
        slots=DockerSlots(tmp_path / "s", 1),
        log=lambda _m: None,
    )
    assert out == [] and cloned == ["fixture"]


def test_peer_roots_count_for_ids_and_titles(tmp_path: Path) -> None:
    peer = tmp_path / "peer"
    stage(peer, "fixture", "ff-005-engine", "derive pool size from the connection budget")
    stage(tmp_path / "tasks", "fixture", "ff-002-x", "something else")
    a = stage(tmp_path / "s1", "fixture", "ff-c001-01-a", "reject blank smtp host")
    m = merge_task(
        a,
        target="fixture",
        prefix="ff",
        slug="a",
        tasks_root=tmp_path / "tasks",
        work_root=tmp_path / "w",
        peers=(peer,),
    )
    assert m.task_id == "fixture/ff-006-a"
    b = stage(tmp_path / "s2", "fixture", "ff-c002-01-b", "Derive the pool size from the connection budget")
    m = merge_task(
        b,
        target="fixture",
        prefix="ff",
        slug="b",
        tasks_root=tmp_path / "tasks",
        work_root=tmp_path / "w",
        peers=(peer,),
    )
    assert m.task_id is None and m.duplicate_of == "derive pool size from the connection budget"


def test_skip_files_drop_their_clusters_and_peer_titles_reach_prompts(
    target: Target, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    peer = tmp_path / "peer"
    stage(peer, "fixture", "ff-001-peer", "peer title here")
    backend = FileBackend({f: [answer(patch_for(target, f), f"strict flag in {f[-4]}")] for f in FILES})
    reports, _g, _s = run_fixture(target, tmp_path, monkeypatch, backend, skip_files=(FILES[0],), peers=(peer,))
    assert sum(r.accepted for r in reports) == 2
    assert not any(FILES[0] + "::" in p for p in backend.prompts)
    assert all("- peer title here" in p for p in backend.prompts)
    assert sorted(d.name for d in (tmp_path / "tasks" / "fixture").iterdir()) == ["ff-002-settings", "ff-003-settings"]
