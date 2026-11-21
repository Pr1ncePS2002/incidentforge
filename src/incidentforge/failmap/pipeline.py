"""`forge map build` end to end, the map.json export and the surface annotation v2-parallel reads."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from incidentforge.failmap import JSON_FILE, cluster, coverage, map_dir, radius, tag
from incidentforge.failmap.build import build
from incidentforge.failmap.overlay import surface_node_id
from incidentforge.failmap.store import module_of, read_annotations, read_edges, read_meta, read_nodes
from incidentforge.models import Surface, Target

SCHEMA_VERSION = 1


@dataclass
class MapSummary:
    map_path: Path
    json_path: Path
    graph_hash: str
    nodes: int
    edges: int
    tagged: int
    clusters: int
    coverage: str  # run | cached | static
    timings: dict[str, float] = field(default_factory=dict)


def build_map(
    target: Target, repo: Path, work_root: Path, run_coverage: bool = False, image: str | None = None
) -> MapSummary:
    out_dir = map_dir(work_root, target.name)
    timings: dict[str, float] = {}

    def step(name: str, started: float) -> None:
        timings[name] = round(time.monotonic() - started, 2)

    t = time.monotonic()
    result = build(repo, target.language, out_dir, target.source_root, commit=target.commit)
    step("graph", t)
    t = time.monotonic()
    tagged = tag.tag(result.map_path)
    radius.annotate(result.map_path)
    found = cluster.assign(result.map_path)
    step("tag_radius_cluster", t)
    t = time.monotonic()
    cached = coverage.cache_path(out_dir, target.commit).exists()
    lines = coverage.load_or_run(target, repo, out_dir, image, run_coverage)
    coverage.apply(result.map_path, lines)
    mode = "static" if lines is None else ("cached" if cached else "run")
    step("coverage", t)
    t = time.monotonic()
    json_path = export_json(result.map_path, out_dir / JSON_FILE, target.name, mode)
    step("export", t)
    timings["total"] = round(sum(timings.values()), 2)
    return MapSummary(
        result.map_path,
        json_path,
        result.graph_hash,
        result.nodes,
        result.edges,
        len(tagged),
        len(found),
        mode,
        timings,
    )


def export_json(map_path: Path, out: Path, target: str, coverage_mode: str) -> Path:
    """deterministic json for v2-viz: non-test nodes with their annotations, edges among them, clusters."""
    meta = read_meta(map_path)
    nodes = read_nodes(map_path)
    annots = read_annotations(map_path)
    root = meta.get("source_root", ".")
    kept = {nid for nid, n in nodes.items() if not n.is_test}
    rows: list[dict[str, Any]] = []
    for nid in sorted(kept):
        n = nodes[nid]
        a = annots.get(nid)
        rows.append(
            {
                "id": nid,
                "kind": n.kind,
                "name": n.name,
                "file": n.file,
                "line": n.line_start,
                "module": module_of(n.file, root),
                "families": a.tags if a else [],
                "surface_kinds": n.attrs.get("surface_kinds", []),
                "blast_radius": a.blast_radius if a else None,
                "difficulty": a.difficulty if a else None,
                "covered": a.covered if a else None,
                "risk_score": a.risk_score if a else None,
                "cluster": a.cluster if a else None,
            }
        )
    edges = [
        {"source": e.source, "target": e.target, "kind": e.kind}
        for e in read_edges(map_path)
        if e.source in kept and e.target in kept
    ]
    clusters = [
        {
            "id": c.id,
            "nodes": list(c.nodes),
            "files": list(c.files),
            "modules": list(c.modules),
            "families": list(c.families),
        }
        for c in cluster.clusters(map_path)
    ]
    doc = {
        "schema": SCHEMA_VERSION,
        "target": target,
        "commit": meta.get("commit", ""),
        "language": meta.get("language", ""),
        "source_root": root,
        "graph_hash": meta.get("graph_hash", ""),
        "coverage": coverage_mode,
        "nodes": rows,
        "edges": edges,
        "clusters": clusters,
    }
    out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    return out


def annotate_surfaces(surfaces: list[Surface], map_path: Path) -> list[Surface]:
    """copies of the flat-scan surfaces with node_id, blast_radius, difficulty, covered and risk_score set."""
    nodes = read_nodes(map_path)
    annots = read_annotations(map_path)
    out: list[Surface] = []
    for s in surfaces:
        nid = surface_node_id(s, nodes)
        a = annots.get(nid) if nid else None
        out.append(
            s.model_copy(
                update={
                    "node_id": nid,
                    "blast_radius": a.blast_radius if a else None,
                    "difficulty": a.difficulty if a else None,
                    "covered": a.covered if a else None,
                    "risk_score": a.risk_score if a else None,
                }
            )
        )
    return out
