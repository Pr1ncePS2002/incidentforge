"""build the solution deck: html slides from repo data, printed to pdf with headless chrome."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from html import escape
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DECK = ROOT / "deck"
REPO_URL = "https://github.com/Pr1ncePS2002/incidentforge"
MAX_PDF_BYTES = 5 * 1024 * 1024
CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "chromium",
    "chromium-browser",
]

FAMILIES = [
    ("fail-fast-config", "refuse to start on missing or blank required settings"),
    ("tolerant-typed-config", "parse settings in the formats operators write, reject garbage"),
    ("cross-field-validation", "reject impossible combinations (start after end, min > max)"),
    ("idempotent-consumer", "apply duplicate or retried messages once"),
    ("hot-reload-config", "dynamic values take effect without a restart"),
    ("env-aware-naming", "cache/queue keys stay correct across environments"),
    ("resource-aware-defaults", "pool/worker sizes follow container limits"),
    ("config-round-trip", "regenerated config never drops or defaults a field"),
]

TBD = '<span class="tbd">TBD</span>'


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _pick(summary: dict[str, Any], key: str, fallback: int) -> int | None:
    """summary value when the key exists (zero included); otherwise the raw-log count, None when there are none."""
    if key in summary and summary[key] is not None:
        return int(summary[key])
    return fallback or None


def load_data(root: Path = ROOT) -> dict[str, Any]:
    """collect real numbers from reports/ and tasks/; anything missing stays None and renders as TBD."""
    summary = _load_json(root / "reports" / "summary.json") or {}
    # task ids contain the target dir, so reports nest one level down
    validations = [_load_json(p) for p in sorted((root / "reports" / "validation").rglob("*.json"))]
    validations = [v for v in validations if isinstance(v, dict)]
    accepted = [v for v in validations if v.get("accepted")]
    gold = sorted((root / "tasks" / "fastapi-template").glob("ff-001-*/instruction.md"))
    task_dirs = [p.parent for p in (root / "tasks").glob("*/*/instruction.md")]
    # report.summarize is the source of truth once it exists; raw logs are the fallback
    sv = summary.get("validation") or {}
    return {
        "summary": summary,
        "validated": _pick(sv, "candidates", len(validations)),
        "accepted": _pick(sv, "accepted", len(accepted)),
        "mutants_total": _pick(sv, "mutants_total", sum(int(v.get("mutants_total", 0)) for v in accepted)),
        "mutants_killed": _pick(sv, "mutants_killed", sum(int(v.get("mutants_killed", 0)) for v in accepted)),
        "tasks_total": _pick(summary, "tasks_total", len(task_dirs)),
        "targets": sorted({p.parent.name for p in task_dirs}) or None,
        "gold_instruction": gold[0].read_text() if gold else None,
    }


def _v(value: Any, fmt: str = "{}") -> str:
    return TBD if value is None else escape(fmt.format(value))


def _bars(rows: list[tuple[str, float]], width: int = 760, bar_h: int = 30) -> str:
    """horizontal bar chart of pass rates in [0, 1] as inline svg."""
    label_w, gap = 260, 12
    h = len(rows) * (bar_h + gap) + 10
    out = [f'<svg viewBox="0 0 {width} {h}" width="{width}" height="{h}" font-family="inherit">']
    for i, (label, rate) in enumerate(rows):
        y = i * (bar_h + gap) + 5
        w = max(2.0, (width - label_w - 70) * rate)
        out.append(
            f'<text x="{label_w - 10}" y="{y + bar_h * 0.68}" text-anchor="end" font-size="16" '
            f'fill="#1f2933">{escape(label)}</text>'
        )
        out.append(f'<rect x="{label_w}" y="{y}" width="{w:.1f}" height="{bar_h}" rx="4" fill="#1565c0"/>')
        out.append(
            f'<text x="{label_w + w + 8:.1f}" y="{y + bar_h * 0.68}" font-size="16" fill="#1f2933">{rate:.0%}</text>'
        )
    out.append("</svg>")
    return "".join(out)


def _short(model: Any) -> str:
    return str(model).removeprefix("gemini/")


def _pct(x: Any) -> str:
    return TBD if x is None else f"{float(x):.0%}"


def _family_table(by_family: list[dict[str, Any]]) -> str:
    """families as rows, models as columns, cells shaded by pass rate."""
    models = sorted({str(f.get("model")) for f in by_family})
    cell = {(str(f.get("family")), str(f.get("model"))): f for f in by_family}
    fams = sorted({str(f.get("family")) for f in by_family})
    head = "".join(f"<th>{escape(_short(m))}</th>" for m in models)
    rows = []
    for fam in fams:
        tds = []
        for m in models:
            f = cell.get((fam, m))
            if f is None:
                tds.append("<td></td>")
                continue
            r = float(f.get("pass_rate", 0))
            # tint scales with pass rate so weak families stand out at a glance
            shade = f"rgba(21,101,192,{0.08 + 0.6 * r:.2f})"
            tds.append(f"<td style='background: {shade}'>{r:.0%} <span>({f.get('n')})</span></td>")
        rows.append(f"<tr><td><code>{escape(fam)}</code></td>{''.join(tds)}</tr>")
    return (
        "<p class='label'>pass rate per family and model (runs)</p>"
        f"<table class='grid heat'><tr><th>family</th>{head}</tr>{''.join(rows)}</table>"
    )


def _svg_file(name: str) -> str:
    path = ROOT / "docs" / "img" / f"{name}.svg"
    if not path.exists():
        return f"<p>{TBD}: run scripts/diagrams.py</p>"
    svg = path.read_text()
    # let the slide css size the diagram instead of its fixed pixel size
    return svg.replace("<svg ", '<svg class="diagram" ', 1)


def slide(title: str, body: str, cls: str = "") -> str:
    head = f"<h1>{escape(title)}</h1>" if title else ""
    return f'<section class="slide {cls}"><div class="content">{head}{body}</div><div class="foot"></div></section>'


def build_html(d: dict[str, Any]) -> str:
    s = d["summary"]
    models = s.get("models") or []
    by_family = s.get("by_family") or []
    slides: list[str] = []

    slides.append(
        '<section class="slide title"><div class="content">'
        '<p class="kicker">Innodata AI Hackathon 2026 · Track 1: Coding Task Factory</p>'
        "<h1>IncidentForge</h1>"
        '<p class="tagline">Coding tasks forged from what actually breaks in production</p>'
        '<table class="meta"><tr><td>Team</td><td>CHAOS</td></tr>'
        "<tr><td>Team leader</td><td>Prince Singh</td></tr>"
        "<tr><td>Problem statement</td><td>Coding Task Factory: generate validated feature-development tasks "
        "from a pinned repository to evaluate AI coding systems</td></tr></table>"
        '</div><div class="foot"></div></section>'
    )
    slides.append(
        slide(
            "The problem",
            "<ul>"
            "<li>Generated coding benchmarks mostly ask a model to <b>invent a feature</b>: generic tasks that test "
            "the happy path.</li>"
            "<li>Real outages come from a few <b>recurring failure classes</b>: missing settings, configs in an "
            "unexpected format, impossible combinations, reloads that never apply, duplicate messages.</li>"
            "<li>These failure paths are exactly where AI-written code is weakest, and no benchmark measures it.</li>"
            "<li>Hand-written tasks do not scale; unvalidated generated tasks are noisy (unsolvable, already "
            "solved, or weakly tested).</li></ul>",
        )
    )
    slides.append(
        slide(
            "Solution and USP",
            "<p class='lead'>A factory that turns <b>any repo + commit</b> into Harbor tasks, each asking the model "
            "to add the protection that would have prevented a real class of production outage.</p>"
            "<ul><li><b>Incident-grounded:</b> 8 task families from recurring failure classes in a large e-commerce "
            "microservice fleet.</li>"
            "<li><b>Fault-injection tests:</b> every task recreates the failure, not only the happy path.</li>"
            "<li><b>Validated, not trusted:</b> 6 automatic gates incl. mutation testing; rejected tasks retried "
            "once with the reason.</li>"
            "<li><b>Repo-agnostic:</b> one command per target; shown on Python and Go.</li></ul>",
        )
    )
    slides.append(
        slide(
            "How it is different",
            "<table class='grid'><tr><th></th><th>Typical generated benchmark</th><th>IncidentForge</th></tr>"
            "<tr><td>Task source</td><td>LLM invents a feature</td><td>production failure classes, weighted by "
            "frequency</td></tr>"
            "<tr><td>Tests</td><td>happy path</td><td>happy path + injected faults</td></tr>"
            "<tr><td>Quality control</td><td>manual spot checks</td><td>6 gates incl. mutation, leak and flakiness"
            "</td></tr>"
            "<tr><td>Repeatability</td><td>one-off scripts</td><td>pinned commits, Docker, Harbor format, CI re-runs"
            "</td></tr>"
            "<tr><td>Signal</td><td>can it code?</td><td>does its code survive production failures?</td></tr>"
            "</table>",
        )
    )
    fam = "".join(f"<tr><td><code>{escape(a)}</code></td><td>{escape(b)}</td></tr>" for a, b in FAMILIES)
    slides.append(
        slide(
            "Features",
            "<div class='cols'><div><ul>"
            "<li>Surface finder for Python and Go code</li>"
            "<li>Pluggable generators: Claude Code headless, Gemini</li>"
            "<li>6 validation gates, JSON log per task</li>"
            "<li>Harbor packaging; oracle 1.0 / no-op 0.0 checked in CI</li>"
            "<li>Model evaluation + static HTML report</li>"
            "<li>Hard spend cap on paid API usage</li></ul></div>"
            f"<div><table class='grid small'><tr><th>Family</th><th>The model must…</th></tr>{fam}</table></div></div>",
        )
    )
    slides.append(slide("Process flow", _svg_file("pipeline"), "fig"))
    slides.append(slide("Architecture", _svg_file("architecture"), "fig"))
    gold = d["gold_instruction"]
    if gold:
        excerpt = escape(gold.strip()[:900])
        gold_html = f"<pre class='instr'>{excerpt}</pre>"
    else:
        gold_html = f"<p>{TBD}: gold task instruction from <code>tasks/fastapi-template/ff-001-*</code></p>"
    slides.append(
        slide(
            "Task example: fail-fast config",
            "<div class='cols'><div>"
            f"<p class='label'>instruction.md (what the agent sees)</p>{gold_html}</div><div>"
            "<p class='label'>package</p><ul class='tight'>"
            "<li><code>environment/</code> repo at pinned commit, Postgres inside</li>"
            "<li><code>solution/</code> reference patch (oracle)</li>"
            "<li><code>tests/</code> feature + fault-injection tests + repo suite</li></ul>"
            "<p class='label'>verified</p><ul class='tight'><li>oracle reward 1.0</li><li>no-op reward 0.0</li>"
            "</ul></div></div>",
        )
    )
    mut = (
        f"{d['mutants_killed']} / {d['mutants_total']}"
        if d["mutants_killed"] is not None and d["mutants_total"] is not None
        else None
    )
    slides.append(
        slide(
            "Validation evidence",
            "<div class='kpis'>"
            f"<div><b>{_v(d['validated'])}</b><span>tasks validated</span></div>"
            f"<div><b>{_v(d['accepted'])}</b><span>accepted</span></div>"
            f"<div><b>{_v(mut)}</b><span>mutants killed</span></div>"
            f"<div><b>{_v(d['tasks_total'])}</b><span>tasks in dataset</span></div>"
            "</div><table class='grid small'><tr><th>Gate</th><th>Proves</th></tr>"
            "<tr><td>fail on base</td><td>the feature is really missing</td></tr>"
            "<tr><td>pass with reference</td><td>the task is solvable</td></tr>"
            "<tr><td>regression</td><td>the repo's own suite stays green</td></tr>"
            "<tr><td>mutation</td><td>tests catch plausible wrong solutions</td></tr>"
            "<tr><td>leak</td><td>instruction does not give away the code</td></tr>"
            "<tr><td>flakiness</td><td>3 reruns agree</td></tr></table>",
        )
    )
    if models:
        rows = [(f"{_short(m.get('model'))} · {m.get('agent', '')}", float(m.get("pass_rate", 0))) for m in models]
        k = escape(str(max(int(m.get("k", 1)) for m in models)))
        runs = escape(str(models[0].get("n", "")))
        res = f"<p class='label'>pass rate per model · {runs} runs each (k=1 on all tasks, k={k} on a subset)</p>"
        res += _bars(rows, width=1000)
        if len({m.get("agent") for m in models}) > 1:
            res += "<p class='note'>agents differ (claude-code vs terminus-2): compare models within one agent.</p>"
    else:
        res = f"<p>{TBD}: per-model pass rates from <code>reports/summary.json</code></p>"
    failures = s.get("failures") or {}
    if failures:
        frows = "".join(
            f"<tr><td>{escape(_short(m))}</td><td><b>{c.get('fault', 0)}</b></td><td>{c.get('happy', 0)}</td>"
            f"<td>{c.get('regression', 0)}</td></tr>"
            for m, c in sorted(failures.items())
        )
        res += (
            "<p class='label'>failed runs by kind of failing test</p><table class='grid small'><tr><th>model</th>"
            f"<th>fault-injection tests</th><th>happy-path tests</th><th>repo suite</th></tr>{frows}</table>"
        )
        fault = sum(int(c.get("fault", 0)) for c in failures.values())
        happy = sum(int(c.get("happy", 0)) for c in failures.values())
        if fault > happy:
            res += (
                f"<p class='lead'>Failed runs broke on an injected fault <b>{fault}</b> times versus <b>{happy}</b> "
                "on the happy path: models build the feature but miss the failure modes.</p>"
            )
    slides.append(slide("Results", res))
    if by_family:
        slides.append(slide("Results by family", _family_table(by_family)))
    ablation = s.get("turn_ablation") or []
    excluded = s.get("excluded_models") or []
    if ablation or excluded:
        body = ""
        if ablation:
            arows = "".join(
                f"<tr><td>{escape(_short(a.get('model')))}</td><td>{_pct(a.get('base_pass_rate'))}</td>"
                f"<td><b>{_pct(a.get('more_pass_rate'))}</b></td>"
                f"<td>{a.get('failures_turn_exhausted', 0)} of {a.get('base_failures', 0)}</td></tr>"
                for a in ablation
            )
            n_tasks = escape(str(ablation[0].get("tasks", "")))
            body += (
                f"<p class='label'>turn budget ablation · terminus-2 · {n_tasks}-task subset</p>"
                "<table class='grid'><tr><th>model</th><th>30 turns</th><th>60 turns</th>"
                f"<th>main-run failures that used every turn</th></tr>{arows}</table>"
                "<p class='note'>part of the gap is the harness turn budget, not only the model: quote pass rates "
                "with the budget they were measured at.</p>"
            )
        if excluded:
            items = "".join(
                f"<li><code>{escape(_short(e.get('model')))}</code>: {escape(str(e.get('reason', '')))}</li>"
                for e in excluded
            )
            body += f"<p class='label'>left out of scoring</p><ul class='tight'>{items}</ul>"
        slides.append(slide("What else the evaluation showed", body))
    slides.append(
        slide(
            "Tech stack",
            "<ul><li><b>Python 3.12</b>, uv, typer, pydantic, PyYAML</li>"
            "<li><b>Harbor</b> task format and runner; <b>Docker</b> images per target repo</li>"
            "<li><b>Claude Code</b> (headless) and <b>Gemini</b> API as generation backends</li>"
            "<li>Evaluated: Harbor's Claude Code agent; gemini-2.5-flash and gemini-3.8-flash through Harbor's "
            "terminus-2 agent</li>"
            "<li>pytest + mutation gate; go test for Go targets</li>"
            "<li>GitHub Actions: ruff, mypy strict, coverage ≥ 75%, secret scan, dependency audit, Docker "
            "integration nightly and before release</li></ul>",
        )
    )
    spend = s.get("spend_usd")
    slides.append(
        slide(
            "Cost",
            "<ul><li>Generation on a Claude Code subscription and the Gemini free tier: <b>$0</b> marginal.</li>"
            f"<li>Paid Gemini fallback only under a <b>$70 hard cap</b>, checked before every call; "
            f"total paid spend for generation and evaluation: <b>{_v(spend, '${:.2f}')}</b>.</li>"
            "<li>Everything else is open source and runs on one laptop.</li></ul>",
        )
    )
    slides.append(
        slide(
            "Deliverables",
            f"<ul><li>Public repo (MIT): <code>{REPO_URL}</code></li>"
            f"<li>Dataset: {_v(d['tasks_total'])} validated Harbor tasks across "
            f"8 families and {_v(len(d['targets']) if d['targets'] else None)} target repos</li>"
            "<li>Validation log per task (<code>reports/validation/</code>)</li>"
            "<li>Evaluation report (<code>reports/index.html</code>)</li>"
            "<li>Docs: architecture, task format, families, finale playbook</li>"
            "<li>Demo video</li></ul>",
        )
    )
    slides.append(
        '<section class="slide title end"><div class="content"><h1>Thank you</h1>'
        f'<p class="tagline">IncidentForge · Team CHAOS</p><p class="kicker">{REPO_URL}</p>'
        '</div><div class="foot"></div></section>'
    )
    css = (DECK / "deck.css").read_text()
    return (
        '<!doctype html><html><head><meta charset="utf-8"><title>IncidentForge deck</title>'
        f"<style>{css}</style></head><body>{''.join(slides)}</body></html>"
    )


def find_chrome() -> str:
    for c in [os.environ.get("CHROME", ""), *CHROME_CANDIDATES]:
        if c and (Path(c).exists() or shutil.which(c)):
            return c
    raise SystemExit("chrome/chromium not found; set CHROME to its path")


def main() -> None:
    html_path = DECK / "deck.html"
    pdf_path = DECK / "IncidentForge-deck.pdf"
    data = load_data()
    html_path.write_text(build_html(data))
    subprocess.run(
        [
            find_chrome(),
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ],
        check=True,
        capture_output=True,
    )
    size = pdf_path.stat().st_size
    print(f"{pdf_path} {size / 1024:.0f} KB")
    if size > MAX_PDF_BYTES:
        sys.exit("deck pdf is over the 5 MB form limit")
    if "TBD" in html_path.read_text():
        print("note: deck still has TBD placeholders")


if __name__ == "__main__":
    main()
