"""failure map page: reports/map.html from work/<target>/map.json, with a vendored d3 inlined so it works offline."""

from __future__ import annotations

import hashlib
import html
import json
import os
import shutil
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

ASSETS = Path(__file__).parent / "report_assets"
D3_FILE = "d3.v7.9.0.min.js"
# pinned build from the npm tarball d3@7.9.0 (ISC); checked on every render so a swapped file fails loudly
D3_SHA256 = "f2094bbf6141b359722c4fe454eb6c4b0f0e42cc10cc7af921fc158fceb86539"
SNAPSHOT_DIR = "map"
# untagged file nodes would bury the functions; tagged ones stay because they are surfaces too
FILE_KIND = "File"
PAGE = "map.html"

FAMILY_COLOURS = {
    "fail-fast-config": "#2f6fde",
    "tolerant-typed-config": "#1f8a4c",
    "cross-field-validation": "#7c4dce",
    "idempotent-consumer": "#c2410c",
    "hot-reload-config": "#d08b16",
    "env-aware-naming": "#0e8a9e",
    "resource-aware-defaults": "#b8336a",
    "config-round-trip": "#5b6b2f",
}
EXTRA_COLOURS = ("#8c564b", "#17becf", "#bcbd22", "#e377c2")
CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome",
    "chromium",
    "chromium-browser",
)


def d3_source() -> str:
    data = (ASSETS / D3_FILE).read_bytes()
    if hashlib.sha256(data).hexdigest() != D3_SHA256:
        raise RuntimeError(f"{D3_FILE} does not match its pinned sha256")
    return data.decode()


def _str(x: Any, default: str = "") -> str:
    return default if x is None else str(x)


def _int(x: Any) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


def normalise(raw: dict[str, Any]) -> dict[str, Any]:
    """keep only the fields the page reads; tolerate missing ones so a partial map still renders."""
    nodes = []
    for n in raw.get("nodes") or []:
        if not isinstance(n, dict) or not n.get("id"):
            continue
        if n.get("kind") == FILE_KIND and not n.get("families"):
            continue
        nid = str(n["id"])
        file = _str(n.get("file"))
        nodes.append(
            {
                "id": nid,
                "kind": _str(n.get("kind"), "function"),
                "name": _str(n.get("name"), nid.rsplit(".", 1)[-1]),
                "file": file,
                "line": _int(n.get("line")),
                "module": _str(n.get("module")) or ".",
                "families": sorted({str(f) for f in n.get("families") or []}),
                "surface_kinds": sorted({str(k) for k in n.get("surface_kinds") or []}),
                "blast_radius": _int(n.get("blast_radius")),
                "difficulty": _str(n.get("difficulty")),
                "covered": n.get("covered") if isinstance(n.get("covered"), bool) else None,
            }
        )
    ids = {n["id"] for n in nodes}
    edges = [
        {"source": str(e["source"]), "target": str(e["target"]), "kind": _str(e.get("kind"), "edge")}
        for e in raw.get("edges") or []
        if isinstance(e, dict) and e.get("source") in ids and e.get("target") in ids and e["source"] != e["target"]
    ]
    # tasks are not in map.json; snapshot() adds them from task.toml and they round-trip through here
    tasks: dict[str, dict[str, str]] = {}
    for t in raw.get("tasks") or []:
        if isinstance(t, dict) and t.get("task_id"):
            tasks[str(t["task_id"])] = {
                "task_id": str(t["task_id"]),
                "node_id": _str(t.get("node_id")),
                "family": _str(t.get("family")),
                "difficulty": _str(t.get("difficulty")),
            }
    return {
        "target": _str(raw.get("target"), "unknown"),
        "commit": _str(raw.get("commit")),
        "graph_hash": _str(raw.get("graph_hash")),
        "schema": _int(raw.get("schema")),
        "language": _str(raw.get("language")),
        "coverage_mode": _str(raw.get("coverage_mode") or raw.get("coverage")),
        "nodes": nodes,
        "edges": edges,
        "tasks": sorted(tasks.values(), key=lambda t: t["task_id"]),
    }


def tasks_from_dir(target_dir: Path) -> list[dict[str, str]]:
    """tasks whose task.toml metadata names a map node (back-filled or generated from the map)."""
    out = []
    for toml_path in sorted(target_dir.glob("*/task.toml")):
        try:
            meta = tomllib.loads(toml_path.read_text()).get("metadata") or {}
        except tomllib.TOMLDecodeError:
            continue
        # package.render_task_toml writes the node as map_node (F-58)
        if meta.get("map_node"):
            out.append(
                {
                    "task_id": f"{target_dir.name}/{toml_path.parent.name}",
                    "node_id": str(meta["map_node"]),
                    "family": _str(meta.get("family")),
                    "difficulty": _str(meta.get("difficulty")),
                }
            )
    return out


def coverage(m: dict[str, Any]) -> dict[str, Any]:
    """tagged surfaces vs tasks, per family and per module; covered means the repo's own tests reach the node."""
    nodes = {n["id"]: n for n in m["nodes"]}
    placed = [t for t in m["tasks"] if t["node_id"] in nodes]
    pairs = {(t["node_id"], t["family"]) for t in placed}
    with_any = {t["node_id"] for t in placed}
    tagged = [n for n in nodes.values() if n["families"]]

    def row(surfaces: list[dict[str, Any]], has_task: set[str], tasks: list[dict[str, str]]) -> dict[str, int]:
        return {
            "surfaces": len(surfaces),
            "with_task": sum(n["id"] in has_task for n in surfaces),
            "tasks": len(tasks),
            "covered": sum(n["covered"] is True for n in surfaces),
            "uncovered": sum(n["covered"] is False for n in surfaces),
        }

    families = sorted({f for n in tagged for f in n["families"]} | {t["family"] for t in placed if t["family"]})
    by_family = {}
    for f in families:
        fam_nodes = [n for n in tagged if f in n["families"]]
        by_family[f] = row(
            fam_nodes, {n["id"] for n in fam_nodes if (n["id"], f) in pairs}, [t for t in placed if t["family"] == f]
        )
    modules = sorted({n["module"] for n in tagged} | {nodes[t["node_id"]]["module"] for t in placed})
    by_module = {}
    for mod in modules:
        mod_nodes = [n for n in tagged if n["module"] == mod]
        by_module[mod] = row(mod_nodes, with_any, [t for t in placed if nodes[t["node_id"]]["module"] == mod])
    return {
        "nodes": len(nodes),
        "total": row(tagged, with_any, placed),
        "unplaced_tasks": len(m["tasks"]) - len(placed),
        "by_family": by_family,
        "by_module": by_module,
    }


def snapshot(map_json: Path, reports_root: Path, tasks_root: Path | None = None) -> Path:
    """copy the map into reports/map/<target>.json (committed) so a clean clone can rebuild the page."""
    m = normalise(json.loads(map_json.read_text()))
    if tasks_root is not None and (tasks_root / m["target"]).is_dir():
        known = {t["task_id"]: t for t in m["tasks"]}
        for t in tasks_from_dir(tasks_root / m["target"]):
            known.setdefault(t["task_id"], t)
        m["tasks"] = sorted(known.values(), key=lambda t: t["task_id"])
    out = reports_root / SNAPSHOT_DIR / f"{m['target']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    # one node or edge per line keeps the committed snapshot small but still diffable
    out.write_text(_lines_json(m))
    return out


def _lines_json(m: dict[str, Any]) -> str:
    def block(rows: list[Any]) -> str:
        return "[\n" + ",\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in rows) + "\n]"

    head = {k: v for k, v in m.items() if not isinstance(v, list)}
    parts = [f"{json.dumps(k)}:{json.dumps(v)}" for k, v in sorted(head.items())]
    parts += [f"{json.dumps(k)}:{block(m[k])}" for k in sorted(k for k, v in m.items() if isinstance(v, list))]
    text = "{\n" + ",\n".join(parts) + "\n}\n"
    assert json.loads(text) == m
    return text


def load_snapshots(reports_root: Path) -> list[dict[str, Any]]:
    return [normalise(json.loads(p.read_text())) for p in sorted((reports_root / SNAPSHOT_DIR).glob("*.json"))]


def colours(maps: list[dict[str, Any]]) -> dict[str, str]:
    fams = sorted({f for m in maps for n in m["nodes"] for f in n["families"]} | set(FAMILY_COLOURS))
    extra = iter(EXTRA_COLOURS * (len(fams) // len(EXTRA_COLOURS) + 1))
    return {f: FAMILY_COLOURS.get(f) or next(extra) for f in fams}


def _esc(s: object) -> str:
    return html.escape(str(s))


def _cov_table(title: str, rows: dict[str, dict[str, int]]) -> str:
    head = "".join(
        f"<th>{h}</th>" for h in [title, "tagged surfaces", "with a task", "tasks", "test-covered", "uncovered"]
    )
    body = "".join(
        f"<tr><td>{_esc(k)}</td><td>{r['surfaces']}</td><td>{r['with_task']}</td><td>{r['tasks']}</td>"
        f"<td>{r['covered']}</td><td>{r['uncovered']}</td></tr>"
        for k, r in rows.items()
    )
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def coverage_html(m: dict[str, Any], cov: dict[str, Any]) -> str:
    """coverage block shared by map.html and the main report."""
    t = cov["total"]
    out = [
        f"<p><b>{_esc(m['target'])}</b> <span class='muted'>@ {_esc(m['commit'][:7])} · graph "
        f"{_esc(m['graph_hash'][:19])}</span>: {cov['nodes']} nodes, {t['surfaces']} tagged with a failure family, "
        f"{t['with_task']} of them have a task ({t['tasks']} tasks); {t['covered']} test-covered, "
        f"{t['uncovered']} uncovered.</p>"
    ]
    if cov["unplaced_tasks"]:
        out.append(f"<p class='muted'>{cov['unplaced_tasks']} task(s) point at nodes missing from this map.</p>")
    out.append(_cov_table("family", cov["by_family"]))
    out.append(_cov_table("module", cov["by_module"]))
    return "\n".join(out)


def _json_script(element_id: str, data: Any) -> str:
    # "</" would end the script element early
    text = json.dumps(data, sort_keys=True).replace("</", "<\\/")
    return f'<script type="application/json" id="{element_id}">{text}</script>'


def render(maps: list[dict[str, Any]]) -> str:
    covs = "".join(
        f'<section class="cov" {"hidden" if i else ""}>{coverage_html(m, coverage(m))}</section>'
        for i, m in enumerate(maps)
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>IncidentForge failure map</title><style>{(ASSETS / 'map.css').read_text()}</style></head><body><main>"
        '<h1>Failure map</h1><p class="intro muted">repo → modules → functions; colour = failure family, '
        'size = blast radius (fix scope), squares = generated tasks. <a href="index.html">back to the report</a></p>'
        '<div class="bar"><select id="target" aria-label="target"></select>'
        '<input id="q" placeholder="search name or file" aria-label="search">'
        '<select id="fam" aria-label="family"></select><select id="kind" aria-label="kind"></select>'
        '<label><input type="checkbox" id="unc"> uncovered only</label>'
        '<label><input type="checkbox" id="all"> show untagged functions</label>'
        '<span id="count" class="muted"></span></div><div id="legend" class="legend"></div>'
        '<div class="wrap"><svg id="graph" role="img" aria-label="failure map graph"></svg>'
        '<aside id="detail"><p class="muted">click a node for details.</p></aside></div>'
        f"<h2 class='cov-h intro'>Coverage</h2>{covs}</main>"
        f"{_json_script('map-data', maps)}{_json_script('map-colours', colours(maps))}"
        f"<script>{d3_source()}</script><script>{(ASSETS / 'map.js').read_text()}</script></body></html>"
    )


def render_all(reports_root: Path = Path("reports")) -> Path | None:
    """rebuild reports/map.html from every committed snapshot; none when no map was rendered yet."""
    maps = load_snapshots(reports_root)
    if not maps:
        return None
    out = reports_root / PAGE
    out.write_text(render(maps))
    return out


def find_chrome() -> str:
    for c in [os.environ.get("CHROME", ""), *CHROME_CANDIDATES]:
        if c and (Path(c).exists() or shutil.which(c)):
            return c
    raise RuntimeError("chrome/chromium not found; set CHROME to its path")


Runner = Callable[[list[str]], Any]


def _run(cmd: list[str]) -> Any:
    return subprocess.run(cmd, check=True, capture_output=True, timeout=120)


def export_png(page: Path, png: Path, run: Runner = _run, chrome: str | None = None) -> Path:
    """headless chrome screenshot of the page in png mode (controls hidden)."""
    png.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            chrome or find_chrome(),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-prefers-reduced-motion",
            "--window-size=1600,1000",
            "--virtual-time-budget=10000",
            f"--screenshot={png.resolve()}",
            page.resolve().as_uri() + "?png=1",
        ]
    )
    if not png.exists():
        raise RuntimeError(f"chrome did not write {png}")
    return png


def build(
    target: str,
    work_root: Path = Path("work"),
    reports_root: Path = Path("reports"),
    tasks_root: Path = Path("tasks"),
) -> Path:
    """snapshot work/<target>/map.json and rebuild reports/map.html."""
    src = work_root / target / "map.json"
    if not src.exists():
        raise FileNotFoundError(f"{src} not found; run `forge map build --target {target}` first")
    snapshot(src, reports_root, tasks_root)
    page = render_all(reports_root)
    assert page is not None  # the snapshot just written guarantees one map
    return page


def by_target(maps: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """coverage per target, for summary.json."""
    return {m["target"]: coverage(m) for m in maps}
