"""report built from files only: summary shape, findings from data, html escaping."""

import json
from pathlib import Path

from test_evaluate import make_task
from typer.testing import CliRunner

from incidentforge.budget import Ledger
from incidentforge.cli import app
from incidentforge.models import EvalResult, GateResult, ValidationReport
from incidentforge.report import build, classify_failure


def seed(tmp: Path) -> tuple[Path, Path]:
    tasks = tmp / "tasks"
    make_task(tasks, "fastapi-template", "ff-001", "fail-fast-config")
    make_task(tasks, "fastapi-template", "cf-001", "cross-field-validation")
    (tasks / "fastapi-template/ff-001/instruction.md").write_text("make <Settings> fail fast")
    reports = tmp / "reports"
    (reports / "validation").mkdir(parents=True)
    for tid, ok in [("fastapi-template/ff-001", True), ("fastapi-template/cf-001", True), ("x/rejected", False)]:
        rep = ValidationReport(
            task_id=tid,
            accepted=ok,
            gates=[GateResult(gate="fail_on_base", passed=True), GateResult(gate="mutation", passed=ok)],
            mutants_total=4,
            mutants_killed=3 if ok else 0,
        )
        (reports / "validation" / f"{tid.replace('/', '__')}.json").write_text(rep.model_dump_json())
    rows, side = [], []
    for model in ["gemini/gemini-3.8-flash", "gemini/gemini-4-hydrogen"]:
        for tid, fam in [
            ("fastapi-template/ff-001", "fail-fast-config"),
            ("fastapi-template/cf-001", "cross-field-validation"),
        ]:
            for attempt in (1, 2):
                ok = model.endswith("hydrogen") and (fam == "fail-fast-config" or attempt == 1)
                rows.append(
                    EvalResult(
                        task_id=tid,
                        family=fam,
                        agent="terminus-2",
                        model=model,
                        attempt=attempt,
                        reward=1.0 if ok else 0.0,
                        input_tokens=1000,
                        output_tokens=100,
                    )
                )
                failed = [] if ok else ["tests/test_ff_001.py::test_fault_missing_from"]
                side.append({"task_id": tid, "model": model, "attempt": attempt, "failed_tests": failed})
    (reports / "eval").mkdir()
    (reports / "eval/results.jsonl").write_text("".join(r.model_dump_json() + "\n" for r in rows))
    (reports / "eval/trials.jsonl").write_text("".join(json.dumps(s) + "\n" for s in side))
    return tasks, reports


def test_build_writes_html_and_summary(tmp_path: Path) -> None:
    tasks, reports = seed(tmp_path)
    ledger = Ledger(tmp_path / "l.jsonl")
    out = build(reports / "index.html", tasks, reports, ledger)
    page = out.read_text()
    assert "IncidentForge report" in page and "prefers-color-scheme:dark" in page
    assert "make &lt;Settings&gt; fail fast" in page and "<Settings>" not in page
    summary = json.loads((reports / "summary.json").read_text())
    assert set(summary) >= {"generated_at", "tasks_total", "tasks_by_family", "models", "by_family", "spend_usd"}
    assert summary["tasks_total"] == 2
    hyd = next(m for m in summary["models"] if m["model"].endswith("hydrogen"))
    assert hyd["pass_rate"] == 0.75 and hyd["n"] == 4 and hyd["k"] == 2
    assert summary["validation"] == {"candidates": 3, "accepted": 2, "mutants_total": 12, "mutants_killed": 6}
    var = next(v for v in summary["variance"] if v["model"].endswith("hydrogen"))
    assert var["attempt_pass_rates"] == [1.0, 0.5] and var["unstable_tasks"] == 1
    assert summary["failures"]["gemini/gemini-3.8-flash"]["fault"] == 4
    text = " ".join(summary["findings"])
    assert "2 of 3 task candidates" in text and "hardest family is cross-field-validation" in text
    assert "injected fault case" in text


def test_excluded_models_and_spend_without_a_ledger(tmp_path: Path) -> None:
    tasks, reports = seed(tmp_path)
    rows = (reports / "eval/results.jsonl").read_text().splitlines()
    paid = json.loads(rows[0]) | {"cost_usd": 0.5, "key": "paid"}
    (reports / "eval/results.jsonl").write_text("\n".join([json.dumps(paid), *rows[1:]]) + "\n")
    note = [
        {"model": "gemini/gemini-4-hydrogen", "agent": "terminus-2", "reason": "empty <completions>", "evidence": "x"}
    ]
    (reports / "eval/excluded.json").write_text(json.dumps(note))
    out = build(reports / "index.html", tasks, reports, Ledger(tmp_path / "missing.jsonl"))
    summary = json.loads((reports / "summary.json").read_text())
    assert summary["spend_usd"] == 0.5 and summary["excluded_models"] == note
    assert any("gemini-4-hydrogen was left out" in f for f in summary["findings"])
    assert "Models left out" in out.read_text() and "empty &lt;completions&gt;" in out.read_text()


def test_empty_inputs_still_render(tmp_path: Path) -> None:
    out = build(tmp_path / "r/index.html", tmp_path / "none", tmp_path / "r", Ledger(tmp_path / "l.jsonl"))
    assert "no results yet" in out.read_text()
    assert json.loads((tmp_path / "r/summary.json").read_text())["models"] == []


def test_classify_failure() -> None:
    feat = ("test_email_config.py",)
    assert classify_failure("tests/test_email_config.py::test_fault_tls_and_ssl", feat) == "fault"
    assert classify_failure("TestFaultMissingEnv", ()) == "fault"
    assert classify_failure("tests/test_email_config.py::test_no_smtp_unchanged", feat) == "happy"
    assert classify_failure("app/tests/api/test_users.py::test_create", feat) == "regression"
    assert classify_failure("feature::tests/x.py::test_fault_a", ()) == "fault"
    assert classify_failure("feature::tests/x.py::test_default_kept", ()) == "happy"
    assert classify_failure("repo::tests/test_fault_tolerance.py::test_x", ()) == "regression"
    assert classify_failure("feature_tests", ()) == "unknown"


def test_cli_report_and_eval(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _tasks, reports = seed(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORGE_LEDGER", str(tmp_path / "l.jsonl"))
    r = CliRunner().invoke(app, ["report", "--out", "reports/index.html"])
    assert r.exit_code == 0, r.output
    assert (reports / "index.html").exists()
    calls: dict[str, object] = {}

    def fake_run_eval(root, models, agent, k, subset, **kw):  # type: ignore[no-untyped-def]
        calls.update(models=models, k=k, subset=subset, env=kw["env"])
        return []

    monkeypatch.setattr("incidentforge.evaluate.run_eval", fake_run_eval)
    monkeypatch.setenv("GEMINI_API_KEY", "f")
    r = CliRunner().invoke(app, ["eval", "--tasks", "tasks", "--k", "3", "--subset", "1"])
    assert r.exit_code == 0, r.output
    assert calls["k"] == 3 and len(calls["subset"]) == 1  # type: ignore[arg-type]
    assert calls["models"] == ["gemini/gemini-3.8-flash"]
