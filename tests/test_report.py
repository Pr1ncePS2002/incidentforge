"""report built from files only: summary shape, findings from data, html escaping."""

import json
from pathlib import Path

from test_evaluate import make_task
from typer.testing import CliRunner

from incidentforge.cli import app
from incidentforge.models import EvalResult, GateResult, ValidationReport
from incidentforge.report import CAUSES, build, classify_failure, failure_cause


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
    out = build(reports / "index.html", tasks, reports)
    page = out.read_text()
    assert "IncidentForge report" in page and "prefers-color-scheme:dark" in page
    assert "make &lt;Settings&gt; fail fast" in page and "<Settings>" not in page
    summary = json.loads((reports / "summary.json").read_text())
    assert set(summary) >= {"generated_at", "tasks_total", "tasks_by_family", "models", "by_family"}
    assert "spend_usd" not in summary and "$70" not in page
    assert summary["tasks_total"] == 2
    hyd = next(m for m in summary["models"] if m["model"].endswith("hydrogen"))
    assert hyd["pass_rate"] == 0.75 and hyd["n"] == 4 and hyd["k"] == 2
    assert summary["validation"] == {"candidates": 3, "accepted": 2, "mutants_total": 12, "mutants_killed": 6}
    var = next(v for v in summary["variance"] if v["model"].endswith("hydrogen"))
    assert var["attempt_pass_rates"] == [1.0, 0.5] and var["unstable_tasks"] == 1
    assert summary["failures"]["gemini/gemini-3.8-flash"]["fault"] == 4
    text = " ".join(summary["findings"])
    assert "2 of 3 tasks with a validation report" in text and "hardest family is cross-field-validation" in text
    assert "injected fault-case test" in text


def test_excluded_models_are_listed(tmp_path: Path) -> None:
    tasks, reports = seed(tmp_path)
    rows = (reports / "eval/results.jsonl").read_text().splitlines()
    paid = json.loads(rows[0]) | {"cost_usd": 0.5, "key": "paid"}
    (reports / "eval/results.jsonl").write_text("\n".join([json.dumps(paid), *rows[1:]]) + "\n")
    note = [
        {"model": "gemini/gemini-4-hydrogen", "agent": "terminus-2", "reason": "empty <completions>", "evidence": "x"}
    ]
    (reports / "eval/excluded.json").write_text(json.dumps(note))
    out = build(reports / "index.html", tasks, reports)
    summary = json.loads((reports / "summary.json").read_text())
    assert summary["excluded_models"] == note
    assert any("gemini-4-hydrogen was left out" in f for f in summary["findings"])
    assert "Models left out" in out.read_text() and "empty &lt;completions&gt;" in out.read_text()


def test_results_for_removed_tasks_are_ignored(tmp_path: Path) -> None:
    tasks, reports = seed(tmp_path)
    gone = EvalResult(task_id="x/removed", family="f", agent="terminus-2", model="m", attempt=1, reward=1.0)
    with (reports / "eval/results.jsonl").open("a") as f:
        f.write(gone.model_dump_json() + "\n")
    build(reports / "index.html", tasks, reports)
    summary = json.loads((reports / "summary.json").read_text())
    assert all(m["model"] != "m" for m in summary["models"])


def test_turn_ablation_is_reported_apart_from_the_main_table(tmp_path: Path) -> None:
    tasks, reports = seed(tmp_path)
    flash = "gemini/gemini-3.8-flash"
    side = [json.loads(x) for x in (reports / "eval/trials.jsonl").read_text().splitlines()]
    for s in side:
        if s["model"] == flash and s["attempt"] == 1:
            s["turns"] = 30 if s["task_id"].endswith("ff-001") else 12
    more = [
        EvalResult(task_id=t, family="f", agent="terminus-2", model=flash, attempt=1, reward=r, max_turns=60)
        for t, r in [("fastapi-template/ff-001", 1.0), ("fastapi-template/cf-001", 0.0)]
    ]
    with (reports / "eval/results.jsonl").open("a") as f:
        f.write("".join(r.model_dump_json() + "\n" for r in more))
    side.append({"task_id": "fastapi-template/ff-001", "model": flash, "attempt": 1, "max_turns": 60, "turns": 40})
    (reports / "eval/trials.jsonl").write_text("".join(json.dumps(s) + "\n" for s in side))
    out = build(reports / "index.html", tasks, reports)
    summary = json.loads((reports / "summary.json").read_text())
    main = next(m for m in summary["models"] if m["model"] == flash)
    assert main["n"] == 4 and main["pass_rate"] == 0.0
    [ab] = summary["turn_ablation"]
    assert (ab["base_pass_rate"], ab["more_pass_rate"], ab["tasks"]) == (0.0, 0.5, 2)
    assert (ab["failures_turn_exhausted"], ab["failures_wrong_code"], ab["failures_no_turn_data"]) == (1, 1, 2)
    assert "turn budget ablation" in out.read_text()
    assert any("with 60 turns instead of 30" in f for f in summary["findings"])


def test_empty_inputs_still_render(tmp_path: Path) -> None:
    out = build(tmp_path / "r/index.html", tmp_path / "none", tmp_path / "r")
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


FEAT = ("test_ff_001.py",)


def test_failure_cause_each_bucket() -> None:
    assert failure_cause({"turns": 30, "failed_tests": ["feature::t.py::test_x"]}, 30, FEAT) == "turn_budget"
    assert failure_cause({"failed_tests": ["repo::app/test_users.py::test_create"]}, 30, FEAT) == "regression"
    assert failure_cause({"failed_tests": [], "parts": {"repo_suite": 0.0}}, None, FEAT) == "regression"
    assert failure_cause({"failed_tests": ["repo_suite"]}, None, FEAT) == "regression"
    fault = ["feature::t.py::test_fault_a", "feature::t.py::TestFaultB"]
    assert failure_cause({"turns": 12, "failed_tests": fault}, 30, FEAT) == "fault_path_missed"
    assert failure_cause({"failed_tests": [*fault, "feature::t.py::test_ok"]}, 30, FEAT) == "wrong_code"
    assert failure_cause({"failed_tests": ["feature_tests"]}, 30, FEAT) == "wrong_code"


def test_failure_cause_order_and_missing_data() -> None:
    # turn budget beats a repo break, which beats a missed fault
    both = {"turns": 31, "failed_tests": ["repo::x.py::test_y", "feature::t.py::test_fault_a"]}
    assert failure_cause(both, 30, FEAT) == "turn_budget"
    both["turns"] = 5
    assert failure_cause(both, 30, FEAT) == "regression"
    # no cap (subscription agent), no turns recorded, or no trial row at all
    assert failure_cause({"turns": 99, "failed_tests": ["feature::t.py::test_fault_a"]}, None, FEAT) == (
        "fault_path_missed"
    )
    assert failure_cause({"failed_tests": ["feature::t.py::test_fault_a"]}, 30, FEAT) == "fault_path_missed"
    assert failure_cause(None, 30, FEAT) == "wrong_code"
    assert failure_cause({}, None, ()) == "wrong_code"


def test_failure_causes_cover_every_failed_run(tmp_path: Path) -> None:
    tasks, reports = seed(tmp_path)
    flash = "gemini/gemini-3.8-flash"
    side = [json.loads(x) for x in (reports / "eval/trials.jsonl").read_text().splitlines()]
    for s in side:
        if s["model"] == flash and s["task_id"].endswith("cf-001"):
            s["turns"], s["max_turns"] = (30, 30) if s["attempt"] == 1 else (3, 30)
            s["failed_tests"] = [] if s["attempt"] == 1 else ["repo::tests/test_api.py::test_login"]
    # one failed run has no trial row at all
    side = [s for s in side if not (s["model"] == flash and s["task_id"].endswith("ff-001") and s["attempt"] == 2)]
    (reports / "eval/trials.jsonl").write_text("".join(json.dumps(s) + "\n" for s in side))
    out = build(reports / "index.html", tasks, reports)
    summary = json.loads((reports / "summary.json").read_text())
    fc = summary["failure_causes"]
    assert fc["causes"] == list(CAUSES)
    assert fc["by_model"][flash] == {"turn_budget": 1, "regression": 1, "fault_path_missed": 1, "wrong_code": 1}
    assert fc["by_model"]["gemini/gemini-4-hydrogen"] == dict.fromkeys(CAUSES, 0) | {"fault_path_missed": 1}
    failed = sum(1 for r in (reports / "eval/results.jsonl").read_text().splitlines() if '"reward":0.0' in r)
    assert sum(sum(c.values()) for c in fc["by_model"].values()) == failed
    assert sum(sum(c.values()) for c in fc["by_family"].values()) == failed
    assert fc["by_family"]["cross-field-validation"]["turn_budget"] == 1
    assert fc["no_detail"] == {flash: 1}
    page = out.read_text()
    assert "Why failed runs failed" in page and 'class="stack"' in page and "c-turn_budget" in page
    assert "without per-test detail" in page
    assert any(f.startswith("each of the 5 failed runs has one cause") for f in summary["findings"])


def test_deck_mentions_failure_causes() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_deck", Path(__file__).parent.parent / "deck/build_deck.py")
    assert spec and spec.loader
    deck = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(deck)
    d = deck.load_data(Path(__file__).parent.parent)
    d["summary"] = {
        "models": [{"model": "m", "agent": "terminus-2", "pass_rate": 0.5, "n": 2}],
        "failure_causes": {"by_model": {"m": {"turn_budget": 2, "fault_path_missed": 3}}},
    }
    assert "<b>2</b> failed runs used every turn and <b>3</b> passed the normal cases" in deck.build_html(d)
