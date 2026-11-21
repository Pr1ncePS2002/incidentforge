"""validation gates with a fake harbor runner, plus leak and mutation operators."""

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from incidentforge import cli
from incidentforge import validate as v
from incidentforge.harbor import Trial
from incidentforge.models import Language, Target
from incidentforge.validate import leak, mutation

BASE_SRC = "class S:\n    port: int = 1\n"
POST_SRC = (
    "class S:\n    port: int = 1\n\n"
    "    def check(self, value):\n"
    "        problems = []\n"
    "        if self.port < 1:\n"
    "            problems.append('SMTP_PORT')\n"
    "        if problems:\n"
    "            raise ValueError(problems)\n"
    "        return value\n"
)


def _patch(path: str = "pkg/cfg.py", before: str = BASE_SRC, after: str = POST_SRC) -> str:
    return mutation._diff(path, before, after, new_file=not before)


def _task(tmp_path: Path, instruction: str = "make the port strict") -> Path:
    d = tmp_path / "tasks" / "demo" / "ff-001-x"
    (d / "solution").mkdir(parents=True)
    (d / "tests").mkdir()
    (d / "instruction.md").write_text(instruction)
    (d / "task.toml").write_text('schema_version = "1.4"\n[metadata]\ntarget = "demo"\n')
    (d / "solution" / "reference.patch").write_text(_patch())
    return d


class FakeRunner:
    """returns canned trials per agent; mutants are killed unless listed as survivors."""

    def __init__(self, nop=None, oracle=None, survivors=(), flaky=None):
        self.nop = nop or {"reward": 0, "feature_tests": 0, "repo_suite": 1}
        self.oracle = oracle or {"reward": 1, "feature_tests": 1, "repo_suite": 1}
        self.survivors, self.flaky, self.calls = set(survivors), flaky, []

    def __call__(self, task_path, agent, job_name, extra_args):
        self.calls.append((agent, job_name, extra_args))
        if agent == "nop":
            return [Trial("x", "x__1", task_path, {k: float(x) for k, x in self.nop.items()})]
        if "-mutation-" in job_name:
            return [
                Trial(p.name, f"{p.name}__1", p, {"reward": 1.0 if p.name in self.survivors else 0.0})
                for p in sorted(task_path.iterdir())
            ]
        if "-flaky-" in job_name and self.flaky is not None:
            return [Trial("x", f"x__{i}", task_path, {"reward": r}) for i, r in enumerate(self.flaky)]
        n = int(extra_args[1]) if extra_args[:1] == ["-k"] else 1
        return [Trial("x", f"x__{i}", task_path, {k: float(x) for k, x in self.oracle.items()}) for i in range(n)]


@pytest.fixture
def no_clone(monkeypatch):
    monkeypatch.setattr(v, "load_target", lambda name: name)
    monkeypatch.setattr(v, "base_files", lambda target, files: {f.path: BASE_SRC for f in files})


def _validate(task, tmp_path, runner, gates=v.GATES):
    return v.validate_task(task, gates, jobs_dir=tmp_path / "jobs", reports_dir=tmp_path / "reports", runner=runner)


def test_all_gates_accept(tmp_path, no_clone):
    runner = FakeRunner()
    r = _validate(_task(tmp_path), tmp_path, runner)
    assert r.accepted, r.gates
    assert [g.gate for g in r.gates] == list(v.ORDER)
    assert r.mutants_total >= 3 and r.mutants_killed == r.mutants_total
    assert [c[0] for c in runner.calls].count("oracle") == 3  # oracle, mutants, flaky reuse the first oracle run
    saved = json.loads((tmp_path / "reports" / "demo" / "ff-001-x.json").read_text())
    assert saved["accepted"] is True and saved["task_id"] == "demo/ff-001-x"


def test_tests_that_always_pass_are_rejected_by_fail_on_base(tmp_path, no_clone):
    r = _validate(_task(tmp_path), tmp_path, FakeRunner(nop={"reward": 1, "feature_tests": 1, "repo_suite": 1}))
    assert not r.accepted
    assert [g.gate for g in r.gates] == ["leak", "fail_on_base"] and not r.gates[-1].passed


def test_broken_repo_suite_on_base_is_rejected(tmp_path, no_clone):
    r = _validate(_task(tmp_path), tmp_path, FakeRunner(nop={"reward": 0, "feature_tests": 0, "repo_suite": 0}))
    assert r.gates[-1].gate == "fail_on_base" and not r.accepted


def test_regression_gate_reads_ctrf(tmp_path, no_clone):
    task = _task(tmp_path)

    class Ctrf(FakeRunner):
        def __call__(self, task_path, agent, job_name, extra_args):
            trials = super().__call__(task_path, agent, job_name, extra_args)
            if agent == "oracle" and job_name.endswith(job_name.split("-oracle-")[-1]) and "-oracle-" in job_name:
                ver = tmp_path / "trial" / "verifier"
                ver.mkdir(parents=True, exist_ok=True)
                tests = [{"name": "feature_tests", "status": "passed"}, {"name": "repo_suite", "status": "failed"}]
                (ver / "ctrf.json").write_text(json.dumps({"results": {"tests": tests}}))
                trials[0].path = tmp_path / "trial"
            return trials

    r = _validate(task, tmp_path, Ctrf(), gates=("pass_on_reference", "regression"))
    assert [g.passed for g in r.gates] == [True, False]


def test_surviving_mutants_are_reported(tmp_path, no_clone):
    task = _task(tmp_path)
    names = [f"ff-001-x-m{i:02d}" for i in range(1, 7)]
    r = _validate(task, tmp_path, FakeRunner(survivors=names[1:]), gates=("mutation",))
    assert r.accepted and r.mutants_killed == 1
    assert "survived" in r.gates[0].detail
    r = _validate(task, tmp_path, FakeRunner(survivors=names), gates=("mutation",))
    assert not r.accepted and r.mutants_killed == 0


def test_flaky_oracle_rejected(tmp_path, no_clone):
    r = _validate(_task(tmp_path), tmp_path, FakeRunner(flaky=[1.0, 0.0]), gates=("flakiness",))
    assert not r.accepted and "runs" in r.gates[0].detail


def test_leak_rejected_and_gate_crash_is_a_rejection(tmp_path, no_clone):
    leaky = _task(tmp_path, instruction="do this:\n        raise ValueError(problems)\n")
    r = _validate(leaky, tmp_path, FakeRunner())
    assert [g.gate for g in r.gates] == ["leak"] and not r.accepted

    def boom(*a):
        raise RuntimeError("docker down")

    r = _validate(_task(tmp_path / "b"), tmp_path, boom, gates=("pass_on_reference",))
    assert not r.accepted and "docker down" in r.gates[0].detail


def test_unknown_gate(tmp_path):
    with pytest.raises(ValueError):
        v.validate_task(tmp_path, ("nope",))


def test_find_task_dirs(tmp_path):
    t = _task(tmp_path)
    assert v.find_task_dirs([tmp_path / "tasks"]) == [t]
    assert v.find_task_dirs([t]) == [t]


def test_cli_validate(tmp_path, monkeypatch):
    t = _task(tmp_path)
    from incidentforge.models import GateResult, ValidationReport

    def fake(d):
        ok = d == t
        return ValidationReport(task_id="demo/x", accepted=ok, gates=[GateResult(gate="leak", passed=ok, detail="d")])

    monkeypatch.setattr(v, "validate_task", fake)
    res = CliRunner().invoke(cli.app, ["validate", str(t)])
    assert res.exit_code == 0 and "1/1 accepted" in res.output
    other = tmp_path / "o" / "a" / "b"
    other.mkdir(parents=True)
    (other / "task.toml").write_text("")
    res = CliRunner().invoke(cli.app, ["validate", str(other)])
    assert res.exit_code == 1 and "leak: d" in res.output
    assert CliRunner().invoke(cli.app, ["validate", str(tmp_path / "empty")]).exit_code == 1


# leak


def test_leak_checks():
    patch = _patch()
    assert leak.check_leak("make the port strict and list every bad variable", patch)[0]
    ok, detail = leak.check_leak("copy this: problems.append('SMTP_PORT')", patch)
    assert not ok and "patch line" in detail
    tokens = " ".join(leak.added_lines(patch))
    assert not leak.check_leak(tokens.replace("\n", " "), patch)[0]
    assert leak.check_leak("x", "+++ b/x\n+a\n") == (True, "no 8-grams in patch")


# mutation


def test_parse_patch_and_post_image():
    patch = _patch()
    [f] = mutation.parse_patch(patch)
    assert f.path == "pkg/cfg.py" and not f.new_file
    assert min(f.added) == 3 and max(f.added) == 10
    assert mutation.post_image({"pkg/cfg.py": BASE_SRC}, patch) == {"pkg/cfg.py": POST_SRC}
    [nf] = mutation.parse_patch(_patch(before=""))
    assert nf.new_file and mutation.post_image({"pkg/cfg.py": ""}, _patch(before=""))["pkg/cfg.py"] == POST_SRC


def test_python_mutants_cover_every_operator():
    added = set(range(3, 11))
    ops = {op for op, _, _ in mutation.python_mutants(POST_SRC, added)}
    assert ops == {"negate_if", "drop_raise", "drop_call", "flip_compare", "return_early"}
    for _, _, src in mutation.python_mutants(POST_SRC, added):
        compile(src, "m", "exec")
    # code outside the added lines is never touched
    assert mutation.python_mutants(POST_SRC, set()) == []


def test_make_mutants_round_robin_and_apply():
    ms = mutation.make_mutants(_patch(), {"pkg/cfg.py": BASE_SRC}, max_n=5)
    assert len({m.op for m in ms}) == 5
    for m in ms:
        post = mutation.post_image({"pkg/cfg.py": BASE_SRC}, m.patch)["pkg/cfg.py"]
        assert post != POST_SRC


def test_line_mutants_for_other_languages():
    src = "package x\n\nfunc f(n int) error {\n\tif n <= 0 {\n\t\treturn errBad\n\t}\n\treturn nil\n}\n"
    muts = mutation.line_mutants(src, {4, 5})
    assert {op for op, _, _ in muts} == {"negate_if", "flip_compare"}
    assert any("if !(n <= 0) {" in s for _, _, s in muts)
    assert any("if n < 0 {" in s for _, _, s in muts)
    before = "package x\n"
    ms = mutation.make_mutants(mutation._diff("x.go", before, src, False), {"x.go": before})
    assert ms and all(m.file == "x.go" for m in ms)


def test_no_newline_at_eof_diff_applies():
    patch = mutation._diff("a.txt", "x\n", "x\ny", False)
    assert "\\ No newline at end of file" in patch
    assert mutation.post_image({"a.txt": "x\n"}, patch)["a.txt"] == "x\ny"


def test_repo_checkout_and_base_files(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=src, check=True)
    (src / "pkg").mkdir()
    (src / "pkg" / "cfg.py").write_text(BASE_SRC)
    subprocess.run(["git", "add", "."], cwd=src, check=True)
    subprocess.run(["git", "commit", "-qm", "base", "--no-verify"], cwd=src, check=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=src, capture_output=True, text=True).stdout.strip()
    monkeypatch.setenv("FORGE_REPO_CACHE", str(tmp_path / "cache"))
    target = Target(
        name="demo", repo_url=str(src), commit=sha, language=Language.python, env_template=tmp_path, test_command="t"
    )
    files = mutation.parse_patch(_patch() + _patch(path="pkg/new.py", before=""))
    base = mutation.base_files(target, files)
    assert base == {"pkg/cfg.py": BASE_SRC, "pkg/new.py": ""}
    assert mutation.base_files(target, files[:1]) == {"pkg/cfg.py": BASE_SRC}  # cached clone reused
