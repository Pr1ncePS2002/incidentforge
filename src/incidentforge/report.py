"""static html report from validation logs and eval results. owner: phase 4."""

from __future__ import annotations

import html
import json
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from incidentforge import map_render
from incidentforge.budget import cost_usd
from incidentforge.evaluate import (
    DEFAULT_MAX_TURNS,
    TRIALS_NAME,
    ResultsStore,
    TaskInfo,
    bare_model,
    discover_tasks,
)
from incidentforge.models import EvalResult, ValidationReport


@dataclass
class Data:
    tasks: list[TaskInfo]
    validation: list[ValidationReport]
    results: list[EvalResult]
    trials: list[dict[str, Any]]
    instructions: dict[str, str] = field(default_factory=dict)
    excluded: list[dict[str, Any]] = field(default_factory=list)  # models dropped for harness reasons, with why
    ablation: list[EvalResult] = field(default_factory=list)  # runs at a non-default turn cap, kept off the main table
    ablation_trials: list[dict[str, Any]] = field(default_factory=list)
    maps: list[dict[str, Any]] = field(default_factory=list)  # failure map snapshots under reports/map/


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load(tasks_root: Path, reports_root: Path) -> Data:
    tasks = discover_tasks(tasks_root) if tasks_root.exists() else []
    instructions: dict[str, str] = {}
    for t in tasks:
        p = tasks_root / t.task_id / "instruction.md"
        instructions[t.task_id] = p.read_text() if p.exists() else ""
    validation = [
        ValidationReport.model_validate_json(p.read_text())
        for p in sorted((reports_root / "validation").rglob("*.json"))
    ]
    eval_dir = reports_root / "eval"
    results = ResultsStore(eval_dir / "results.jsonl").load()
    trials = _jsonl(eval_dir / TRIALS_NAME)
    if tasks:
        # tasks removed from the dataset after they were evaluated must not count
        known = {t.task_id for t in tasks}
        results = [r for r in results if r.task_id in known]
        trials = [t for t in trials if t.get("task_id") in known]
    excluded_path = eval_dir / "excluded.json"
    excluded = json.loads(excluded_path.read_text()) if excluded_path.exists() else []
    main_caps = {None, DEFAULT_MAX_TURNS}
    ablation = [r for r in results if r.max_turns not in main_caps]
    results = [r for r in results if r.max_turns in main_caps]
    ablation_trials = [t for t in trials if t.get("max_turns") not in main_caps]
    trials = [t for t in trials if t.get("max_turns") in main_caps]
    maps = map_render.load_snapshots(reports_root)
    return Data(tasks, validation, results, trials, instructions, excluded, ablation, ablation_trials, maps)


def classify_failure(test_name: str, feature_files: tuple[str, ...]) -> str:
    """fault | happy | regression | unknown, from the log prefix and the naming contract (test_fault_*)."""
    if test_name.startswith("repo::") or test_name == "repo_suite":
        return "regression"
    if test_name == "feature_tests":
        # coarse ctrf entry with no per-test detail
        return "unknown"
    # match the test function name only: a bare substring would also hit "default"
    func = test_name.rsplit("::", 1)[-1].lower()
    if func.startswith(("test_fault", "testfault")):
        return "fault"
    if test_name.startswith("feature::"):
        return "happy"
    stems = [f.rsplit(".", 1)[0] for f in feature_files]
    if any(s and s in test_name for s in stems):
        return "happy"
    return "regression"


# order matters: the first cause that fits a failed run wins, so every failed run lands in exactly one bucket
CAUSES = ("turn_budget", "regression", "fault_path_missed", "wrong_code")
CAUSE_LABELS = {
    "turn_budget": "used every turn",
    "regression": "broke the repo's own tests",
    "fault_path_missed": "missed an injected fault",
    "wrong_code": "wrong code",
}


def failure_cause(trial: dict[str, Any] | None, max_turns: int | None, feature_files: tuple[str, ...]) -> str:
    """one cause per failed run, checked in CAUSES order; a run with no trial data falls through to wrong_code."""
    t = trial or {}
    turns = t.get("turns")
    if max_turns and turns is not None and int(turns) >= max_turns:
        return "turn_budget"
    kinds = {classify_failure(str(n), feature_files) for n in t.get("failed_tests") or []}
    parts = t.get("parts") or {}
    if "regression" in kinds or float(parts.get("repo_suite", 1.0)) < 1.0:
        return "regression"
    if kinds == {"fault"}:
        return "fault_path_missed"
    return "wrong_code"


def _has_detail(trial: dict[str, Any] | None, feature_files: tuple[str, ...]) -> bool:
    tests = (trial or {}).get("failed_tests") or []
    return any(classify_failure(str(n), feature_files) in {"fault", "happy"} for n in tests)


def failure_causes(data: Data) -> dict[str, Any]:
    """failed runs per cause, by model and by family; no_detail counts wrong_code runs we could not look inside."""
    feature = {t.task_id: t.feature_tests for t in data.tasks}
    family = _family_of(data)
    # same join as failure_breakdown: older trial rows carry no agent
    trials = {(t.get("task_id"), t.get("model"), t.get("attempt")): t for t in data.trials}
    by_model: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(CAUSES, 0))
    by_family: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(CAUSES, 0))
    no_detail: dict[str, int] = defaultdict(int)
    for r in data.results:
        if r.reward >= 1.0:
            continue
        tr = trials.get((r.task_id, r.model, r.attempt))
        files = feature.get(r.task_id, ())
        cause = failure_cause(tr, r.max_turns, files)
        by_model[r.model][cause] += 1
        by_family[family.get(r.task_id, r.family)][cause] += 1
        if cause == "wrong_code" and not _has_detail(tr, files):
            no_detail[r.model] += 1
    return {
        "causes": list(CAUSES),
        "by_model": {m: by_model[m] for m in sorted(by_model)},
        "by_family": {f: by_family[f] for f in sorted(by_family)},
        "no_detail": {m: no_detail[m] for m in sorted(no_detail)},
    }


def _rate(rs: list[EvalResult]) -> float:
    return sum(r.reward >= 1.0 for r in rs) / len(rs) if rs else 0.0


def _family_of(data: Data) -> dict[str, str]:
    fam = {t.task_id: t.family for t in data.tasks}
    for r in data.results:
        fam.setdefault(r.task_id, r.family)
    return fam


def model_label(r: EvalResult) -> str:
    return r.model if r.agent in {"terminus-2", "", r.model} else f"{r.agent}:{r.model}"


def summarize(data: Data) -> dict[str, Any]:
    """machine-readable summary read by scripts/readme_results.py."""
    fam_count: dict[str, int] = defaultdict(int)
    for t in data.tasks:
        fam_count[t.family] += 1
    by_model: dict[tuple[str, str], list[EvalResult]] = defaultdict(list)
    by_fam: dict[tuple[str, str], list[EvalResult]] = defaultdict(list)
    for r in data.results:
        by_model[(r.model, r.agent)].append(r)
        by_fam[(r.family, r.model)].append(r)
    models = []
    for (m, a), rs in sorted(by_model.items()):
        models.append(
            {
                "model": m,
                "agent": a,
                "k": max(r.attempt for r in rs),
                "pass_rate": round(_rate(rs), 4),
                "n": len(rs),
                "tasks": len({r.task_id for r in rs}),
                "input_tokens": sum(r.input_tokens for r in rs),
                "output_tokens": sum(r.output_tokens for r in rs),
            }
        )
    accepted = sum(v.accepted for v in data.validation)
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "tasks_total": len(data.tasks),
        "tasks_by_family": dict(sorted(fam_count.items())),
        "validation": {
            "candidates": len(data.validation),
            "accepted": accepted,
            "mutants_total": sum(v.mutants_total for v in data.validation),
            "mutants_killed": sum(v.mutants_killed for v in data.validation),
        },
        "models": models,
        "by_family": [
            {"family": f, "model": m, "pass_rate": round(_rate(rs), 4), "n": len(rs)}
            for (f, m), rs in sorted(by_fam.items())
        ],
        "failures": failure_breakdown(data),
        "failure_causes": failure_causes(data),
        "variance": variance(data),
        "turn_ablation": turn_ablation(data),
        "excluded_models": data.excluded,
        "findings": findings(data),
        "map_coverage": map_render.by_target(data.maps),
    }


def failure_breakdown(data: Data) -> dict[str, dict[str, int]]:
    """model -> count of failed runs whose failing tests hit fault / happy / regression paths."""
    feature = {t.task_id: t.feature_tests for t in data.tasks}
    out: dict[str, dict[str, int]] = defaultdict(lambda: {"fault": 0, "happy": 0, "regression": 0, "unknown": 0})
    for tr in data.trials:
        tests = tr.get("failed_tests") or []
        model = str(tr.get("model", ""))
        if not tests:
            continue
        kinds = {classify_failure(name, feature.get(str(tr.get("task_id")), ())) for name in tests}
        for kind in kinds:
            out[model][kind] += 1
    # failed runs without ctrf detail are counted so the totals stay honest
    with_detail = {(t.get("task_id"), t.get("model"), t.get("attempt")) for t in data.trials if t.get("failed_tests")}
    for r in data.results:
        if r.reward < 1.0 and (r.task_id, r.model, r.attempt) not in with_detail:
            out[r.model]["unknown"] += 1
    return {m: dict(v) for m, v in sorted(out.items())}


def variance(data: Data) -> list[dict[str, Any]]:
    """per model: pass rate of each attempt over the tasks that have more than one attempt."""
    multi: dict[str, dict[str, dict[int, float]]] = defaultdict(lambda: defaultdict(dict))
    for r in data.results:
        multi[r.model][r.task_id][r.attempt] = r.reward
    out = []
    for model, per_task in sorted(multi.items()):
        tasks = {t: a for t, a in per_task.items() if len(a) > 1}
        if not tasks:
            continue
        k = max(len(a) for a in tasks.values())
        rates = []
        for attempt in range(1, k + 1):
            vals = [a[attempt] >= 1.0 for a in tasks.values() if attempt in a]
            if vals:
                rates.append(sum(vals) / len(vals))
        flips = sum(len({v >= 1.0 for v in a.values()}) > 1 for a in tasks.values())
        out.append(
            {
                "model": model,
                "tasks": len(tasks),
                "k": k,
                "attempt_pass_rates": [round(x, 4) for x in rates],
                "stdev": round(statistics.pstdev(rates), 4) if len(rates) > 1 else 0.0,
                "unstable_tasks": flips,
            }
        )
    return out


def turn_ablation(data: Data) -> list[dict[str, Any]]:
    """per model and larger cap: pass rate at the default cap vs the larger one on the same tasks, attempt 1,
    plus how many default-cap failures used up every turn versus stopped before the cap."""
    turns = {
        (t.get("task_id"), t.get("model"), t.get("attempt")): int(t.get("turns") or 0)
        for t in data.trials
        if t.get("turns") is not None
    }
    out = []
    caps = sorted({(r.model, r.max_turns or 0) for r in data.ablation})
    for model, cap in caps:
        big = {r.task_id: r for r in data.ablation if r.model == model and r.max_turns == cap and r.attempt == 1}
        base = {r.task_id: r for r in data.results if r.model == model and r.attempt == 1 and r.task_id in big}
        common = sorted(set(big) & set(base))
        if not common:
            continue
        fails = [r for r in data.results if r.model == model and r.reward < 1.0]
        known = [r for r in fails if (r.task_id, r.model, r.attempt) in turns]
        exhausted = sum(turns[(r.task_id, r.model, r.attempt)] >= DEFAULT_MAX_TURNS for r in known)
        out.append(
            {
                "model": model,
                "tasks": len(common),
                "base_turns": DEFAULT_MAX_TURNS,
                "more_turns": cap,
                "base_pass_rate": round(_rate([base[t] for t in common]), 4),
                "more_pass_rate": round(_rate([big[t] for t in common]), 4),
                "base_failures": len(fails),
                "failures_turn_exhausted": exhausted,
                "failures_wrong_code": len(known) - exhausted,
                "failures_no_turn_data": len(fails) - len(known),
            }
        )
    return out


def findings(data: Data) -> list[str]:
    """headline findings computed from the data; empty when there is nothing to say."""
    out: list[str] = []
    if data.validation:
        acc = sum(v.accepted for v in data.validation)
        mt = sum(v.mutants_total for v in data.validation)
        mk = sum(v.mutants_killed for v in data.validation)
        line = f"{acc} of {len(data.validation)} tasks with a validation report passed every gate"
        if mt:
            line += f"; accepted tasks' tests killed {mk} of {mt} injected mutants ({mk / mt:.0%})"
        out.append(line + ".")
    by_model: dict[str, list[EvalResult]] = defaultdict(list)
    for r in data.results:
        by_model[model_label(r)].append(r)
    if by_model:
        ranked = sorted(by_model.items(), key=lambda kv: _rate(kv[1]), reverse=True)
        parts = [f"{m} {_rate(rs):.0%} ({len(rs)} runs)" for m, rs in ranked]
        agents = sorted({r.agent for r in data.results})
        note = f" (agents differ: {', '.join(agents)}; compare models within one agent)" if len(agents) > 1 else ""
        out.append("pass rate by model: " + ", ".join(parts) + note + ".")
        by_fam: dict[str, list[EvalResult]] = defaultdict(list)
        for r in data.results:
            by_fam[r.family].append(r)
        if len(by_fam) > 1:
            hard = min(by_fam.items(), key=lambda kv: _rate(kv[1]))
            easy = max(by_fam.items(), key=lambda kv: _rate(kv[1]))
            out.append(
                f"hardest family is {hard[0]} ({_rate(hard[1]):.0%} of {len(hard[1])} runs across all models); "
                f"easiest is {easy[0]} ({_rate(easy[1]):.0%} of {len(easy[1])} runs)."
            )
    fb = failure_breakdown(data)
    fault = sum(v.get("fault", 0) for v in fb.values())
    happy = sum(v.get("happy", 0) for v in fb.values())
    if fault + happy:
        out.append(
            f"of failed runs with per-test detail, {fault} failed at least one injected fault-case test and "
            f"{happy} at least one happy-path test."
        )
    fc = failure_causes(data)
    totals = {c: sum(v[c] for v in fc["by_model"].values()) for c in CAUSES}
    if any(totals.values()):
        split = ", ".join(f"{totals[c]} {CAUSE_LABELS[c]}" for c in CAUSES)
        out.append(f"each of the {sum(totals.values())} failed runs has one cause: {split}.")
    for x in data.excluded:
        out.append(f"{x.get('model', '?')} was left out of scoring: {x.get('reason', 'no reason given')}.")
    for a in turn_ablation(data):
        out.append(
            f"{a['model']} with {a['more_turns']} turns instead of {a['base_turns']}: "
            f"{a['base_pass_rate']:.0%} -> {a['more_pass_rate']:.0%} on {a['tasks']} tasks; of its "
            f"{a['base_failures']} main-run failures, {a['failures_turn_exhausted']} used every turn and "
            f"{a['failures_wrong_code']} stopped before the cap."
        )
    return out


def _esc(s: object) -> str:
    return html.escape(str(s))


def _bar(rate: float) -> str:
    return f'<span class="bar"><span style="width:{rate * 100:.1f}%"></span></span> {rate:.0%}'


CSS = """
:root{--bg:#fbfbfa;--fg:#1d1d1f;--muted:#6b6b70;--line:#e2e2e0;--card:#fff;--accent:#2f6fde;--ok:#1f8a4c;--bad:#c2410c}
@media (prefers-color-scheme:dark){:root{--bg:#111214;--fg:#e8e8ea;--muted:#9a9aa2;--line:#2a2b2f;--card:#18191c;
--accent:#6f9cf0;--ok:#4cc38a;--bad:#f0875a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}h1{font-size:26px;margin:0 0 4px}
h2{font-size:19px;margin:36px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}
h3{font-size:16px;margin:24px 0 8px}
.muted{color:var(--muted)}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.card b{display:block;font-size:22px}.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;background:var(--card);font-size:14px}
th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{font-weight:600}.bar{display:inline-block;width:90px;height:8px;background:var(--line);border-radius:4px;
vertical-align:middle}.bar span{display:block;height:100%;background:var(--accent);border-radius:4px}
.ok{color:var(--ok)}.bad{color:var(--bad)}details{background:var(--card);border:1px solid var(--line);
border-radius:8px;margin:6px 0;padding:6px 10px}summary{cursor:pointer}
pre{white-space:pre-wrap;font-size:13px;background:var(--bg);padding:8px;border-radius:6px}
.stack{display:flex;width:100%;max-width:520px;height:14px;border-radius:4px;overflow:hidden;background:var(--line)}
.stack span{display:block;height:100%}.key{display:inline-block;width:10px;height:10px;border-radius:2px;
margin:0 4px 0 10px;vertical-align:middle}.c-turn_budget{background:#d08b16}.c-regression{background:#c2410c}
.c-fault_path_missed{background:#7c4dce}.c-wrong_code{background:#8a8a90}
@media (prefers-color-scheme:dark){.c-turn_budget{background:#e9a93c}.c-regression{background:#f0875a}
.c-fault_path_missed{background:#a98be8}.c-wrong_code{background:#6c6c74}}
input{padding:6px 8px;width:100%;max-width:360px;margin:6px 0;background:var(--card);color:var(--fg);
border:1px solid var(--line);border-radius:6px}
"""

JS = """
document.getElementById('q').addEventListener('input',e=>{const q=e.target.value.toLowerCase();
document.querySelectorAll('#tasks details').forEach(d=>{
d.style.display=d.textContent.toLowerCase().includes(q)?'':'none'})});
"""


def _table(head: list[str], rows: list[list[str]]) -> str:
    th = "".join(f"<th>{_esc(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="scroll"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def _stack(counts: dict[str, int]) -> str:
    total = sum(counts.values()) or 1
    segs = "".join(
        f'<span class="c-{c}" style="width:{counts[c] / total * 100:.1f}%" title="{_esc(CAUSE_LABELS[c])}: '
        f'{counts[c]}"></span>'
        for c in CAUSES
        if counts.get(c)
    )
    return f'<div class="stack" role="img" aria-label="failure causes">{segs}</div>'


def _causes_html(fc: dict[str, Any]) -> str:
    if not fc["by_model"]:
        return ""
    legend = "".join(f'<span class="key c-{c}"></span>{_esc(CAUSE_LABELS[c])}' for c in CAUSES)
    head = ["model", "failed runs", "causes", *(CAUSE_LABELS[c] for c in CAUSES)]
    rows = [[_esc(m), str(sum(c.values())), _stack(c), *(str(c[k]) for k in CAUSES)] for m, c in fc["by_model"].items()]
    fam_rows = [[_esc(f), str(sum(c.values())), *(str(c[k]) for k in CAUSES)] for f, c in fc["by_family"].items()]
    out = [
        "<h3 id='causes'>Why failed runs failed</h3>",
        "<p>every failed run gets exactly one cause, checked in this order: used every turn, broke the repo's own "
        "tests, missed an injected fault (normal-case tests passed), otherwise wrong code.</p>",
        f'<p class="muted">{legend}</p>',
        _table(head, rows),
    ]
    if fc["no_detail"]:
        n = ", ".join(f"{_esc(m)} {k}" for m, k in fc["no_detail"].items())
        out.append(f'<p class="muted">wrong code without per-test detail in the verifier logs: {n}.</p>')
    out += ["<p>failure causes per family (all models):</p>", _table(["family", "failed runs", *head[3:]], fam_rows)]
    return "\n".join(out)


def render_html(data: Data, summary: dict[str, Any]) -> str:
    s: list[str] = []
    v = summary["validation"]
    acc_rate = f"{v['accepted'] / v['candidates']:.0%}" if v["candidates"] else "-"
    mut = f"{v['mutants_killed']}/{v['mutants_total']}" if v["mutants_total"] else "-"
    runs = len(data.results)
    s.append('<div class="cards">')
    for label, val in [
        ("tasks", summary["tasks_total"]),
        ("families", len(summary["tasks_by_family"])),
        ("acceptance", acc_rate),
        ("mutants killed", mut),
        ("eval runs", runs),
    ]:
        s.append(f'<div class="card"><span class="muted">{_esc(label)}</span><b>{_esc(val)}</b></div>')
    s.append("</div>")

    s.append("<h2>Headline findings</h2>")
    if summary["findings"]:
        s.append("<ul>" + "".join(f"<li>{_esc(f)}</li>" for f in summary["findings"]) + "</ul>")
    else:
        s.append('<p class="muted">no results yet.</p>')

    if data.excluded:
        s.append("<h2>Models left out</h2>")
        s.append(
            _table(
                ["model", "agent", "why", "evidence"],
                [
                    [
                        _esc(x.get("model", "")),
                        _esc(x.get("agent", "")),
                        _esc(x.get("reason", "")),
                        _esc(x.get("evidence", "")),
                    ]
                    for x in data.excluded
                ],
            )
        )

    s.append("<h2>Dataset</h2>")
    dims: dict[str, dict[str, int]] = {"family": {}, "language/target": {}, "difficulty": {}, "origin": {}}
    for t in data.tasks:
        for dim, val in [
            ("family", t.family),
            ("language/target", t.target or t.dataset.name),
            ("difficulty", t.difficulty),
            ("origin", t.origin),
        ]:
            dims[dim][val] = dims[dim].get(val, 0) + 1
    rows = [[_esc(d), ", ".join(f"{_esc(k)}: {n}" for k, n in sorted(c.items())) or "-"] for d, c in dims.items()]
    s.append(_table(["dimension", "tasks"], rows))
    gate_stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for vr in data.validation:
        for g in vr.gates:
            gate_stats[g.gate][0] += int(g.passed)
            gate_stats[g.gate][1] += 1
    if gate_stats:
        s.append("<p>validation gates over all task candidates:</p>")
        s.append(
            _table(
                ["gate", "passed", "rate"],
                [[_esc(g), f"{p}/{n}", _bar(p / n)] for g, (p, n) in sorted(gate_stats.items())],
            )
        )

    s.append("<h2>Results</h2>")
    models = summary["models"]
    if models:
        rows = []
        for m in models:
            listed = cost_usd(bare_model(m["model"]), m["input_tokens"], m["output_tokens"])
            rows.append(
                [
                    _esc(m["model"]),
                    _esc(m["agent"]),
                    str(m["tasks"]),
                    str(m["n"]),
                    _bar(m["pass_rate"]),
                    f"{m['input_tokens']:,} / {m['output_tokens']:,}",
                    f"${listed:.2f}",
                ]
            )
        s.append(_table(["model", "agent", "tasks", "runs", "pass rate", "tokens in / out", "at list price"], rows))
        fams = sorted({r["family"] for r in summary["by_family"]})
        mnames = sorted({r["model"] for r in summary["by_family"]})
        cell = {(r["family"], r["model"]): r for r in summary["by_family"]}
        rows = []
        for f in fams:
            row = [_esc(f)]
            for m in mnames:
                c = cell.get((f, m))
                row.append(f"{_bar(c['pass_rate'])} <span class='muted'>n={c['n']}</span>" if c else "-")
            rows.append(row)
        s.append("<p>pass rate per model and family:</p>")
        s.append(_table(["family", *mnames], rows))
        s.append(_causes_html(summary["failure_causes"]))
        if summary["turn_ablation"]:
            s.append("<p>turn budget ablation (same tasks, first attempt):</p>")
            rows = [
                [
                    _esc(x["model"]),
                    str(x["tasks"]),
                    f"{x['base_pass_rate']:.0%} at {x['base_turns']}",
                    f"{x['more_pass_rate']:.0%} at {x['more_turns']}",
                    f"{x['failures_turn_exhausted']} hit the cap / {x['failures_wrong_code']} stopped before the cap"
                    + (f" / {x['failures_no_turn_data']} no data" if x["failures_no_turn_data"] else ""),
                ]
                for x in summary["turn_ablation"]
            ]
            s.append(_table(["model", "tasks", "pass rate", "with more turns", "main-run failures"], rows))
        if summary["variance"]:
            s.append("<p>repeat runs on the fixed subset (variance):</p>")
            rows = [
                [
                    _esc(x["model"]),
                    str(x["tasks"]),
                    str(x["k"]),
                    ", ".join(f"{r:.0%}" for r in x["attempt_pass_rates"]),
                    f"{x['stdev']:.3f}",
                    str(x["unstable_tasks"]),
                ]
                for x in summary["variance"]
            ]
            s.append(_table(["model", "tasks", "k", "pass rate per attempt", "stdev", "tasks that flip"], rows))
    else:
        s.append('<p class="muted">no eval results yet; run <code>forge eval</code>.</p>')

    if data.maps:
        s.append("<h2 id='map'>Failure map</h2>")
        s.append(
            f'<p><a href="{map_render.PAGE}">open the failure map</a>: repo, modules and functions coloured by '
            "failure family, with generated tasks pinned to the code they change.</p>"
        )
        s += [map_render.coverage_html(m, map_render.coverage(m)) for m in data.maps]

    s.append("<h2>Task browser</h2>")
    s.append('<input id="q" placeholder="filter tasks" aria-label="filter tasks">')
    s.append('<div id="tasks">')
    vrep = {r.task_id: r for r in data.validation}
    outcome: dict[str, list[EvalResult]] = defaultdict(list)
    for r in data.results:
        outcome[r.task_id].append(r)
    for t in data.tasks:
        rep = vrep.get(t.task_id)
        gates = (
            ", ".join(f"<span class='{'ok' if g.passed else 'bad'}'>{_esc(g.gate)}</span>" for g in rep.gates)
            if rep
            else "<span class='muted'>no validation report</span>"
        )
        outs = (
            ", ".join(
                f"<span class='{'ok' if r.reward >= 1.0 else 'bad'}'>{_esc(model_label(r))}#{r.attempt}"
                f" {'pass' if r.reward >= 1.0 else 'fail'}</span>"
                for r in sorted(outcome[t.task_id], key=lambda r: (r.model, r.attempt))
            )
            or "<span class='muted'>not evaluated</span>"
        )
        faults = "".join(f"<li>{_esc(f)}</li>" for f in t.fault_cases)
        s.append(
            f"<details><summary><b>{_esc(t.task_id)}</b> <span class='muted'>{_esc(t.family)} · "
            f"{_esc(t.difficulty)}</span></summary><p>gates: {gates}</p><p>outcomes: {outs}</p>"
            + (f"<p>fault cases:</p><ul>{faults}</ul>" if faults else "")
            + f"<pre>{_esc(data.instructions.get(t.task_id, ''))}</pre></details>"
        )
    s.append("</div>")
    body = "\n".join(s)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>IncidentForge report</title><style>{CSS}</style></head><body><main>"
        "<h1>IncidentForge report</h1>"
        f'<p class="muted">generated {_esc(summary["generated_at"])} from files under reports/ and tasks/</p>'
        f"{body}</main><script>{JS}</script></body></html>"
    )


def build(
    out: Path = Path("reports/index.html"),
    tasks_root: Path = Path("tasks"),
    reports_root: Path = Path("reports"),
) -> Path:
    """regenerate index.html and summary.json from files only."""
    data = load(tasks_root, reports_root)
    summary = summarize(data)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(data, summary))
    (out.parent / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    map_render.render_all(reports_root)
    return out
