"""the only module that imports code_review_graph; everything else reads our fm_* tables."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from code_review_graph.graph import GraphStore
from code_review_graph.incremental import full_build

from incidentforge.failmap import MAP_FILE
from incidentforge.failmap.overlay import overlay
from incidentforge.failmap.store import MapEdge, MapNode, graph_hash, read_meta, write_graph
from incidentforge.models import Language, Surface

CRG_VERSION = "2.3.9"


@dataclass
class BuildResult:
    map_path: Path
    graph_hash: str
    nodes: int
    edges: int
    seconds: float


@contextmanager
def _serial_parse() -> Iterator[None]:
    # the process pool returns files in completion order; serial keeps crg's row order fixed
    old = os.environ.get("CRG_SERIAL_PARSE")
    os.environ["CRG_SERIAL_PARSE"] = "1"
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("CRG_SERIAL_PARSE", None)
        else:
            os.environ["CRG_SERIAL_PARSE"] = old


def _rel(value: str, prefix: str) -> str:
    return value[len(prefix) :] if value.startswith(prefix) else value


def crg_graph(repo: Path, db: Path, language: Language) -> tuple[list[MapNode], list[MapEdge]]:
    """full crg build into db, then nodes/edges of one language with repo-relative ids."""
    root = repo.resolve()
    for suffix in ("", "-wal", "-shm"):
        Path(f"{db}{suffix}").unlink(missing_ok=True)
    with _serial_parse():
        store = GraphStore(db)
        try:
            full_build(root, store)
            # full_build leaves bare cross-file call targets; these two bind them when imports back one candidate
            store.resolve_bare_call_targets()
            store.resolve_bare_tested_by_sources()
            store.refresh_target_resolution()
            raw_nodes = store.get_all_nodes(exclude_files=False)
            raw_edges = store.get_all_edges()
        finally:
            store.close()
    prefix = f"{root}/"
    nodes: dict[str, MapNode] = {}
    for n in raw_nodes:
        if n.language != language.value:
            continue
        nid = _rel(n.qualified_name, prefix)
        nodes[nid] = MapNode(
            id=nid,
            kind=n.kind,
            name=_rel(n.name, prefix),
            file=_rel(n.file_path, prefix),
            line_start=n.line_start,
            line_end=n.line_end,
            language=n.language,
            is_test=bool(n.is_test),
        )
    edges: dict[tuple[str, str, str], int] = {}
    for e in raw_edges:
        src, tgt = _rel(e.source_qualified, prefix), _rel(e.target_qualified, prefix)
        if src in nodes and tgt in nodes and src != tgt:
            key = (e.kind, src, tgt)
            edges[key] = min(edges.get(key, e.line or 0), e.line or 0)
    return list(nodes.values()), [MapEdge(k, s, t, line) for (k, s, t), line in sorted(edges.items())]


def build(
    repo: Path,
    language: Language,
    out_dir: Path,
    source_root: str = ".",
    surfaces: list[Surface] | None = None,
    commit: str = "",
) -> BuildResult:
    """crg base graph plus our config/env/handler overlay, written to out_dir/map.sqlite."""
    started = time.monotonic()
    out_dir.mkdir(parents=True, exist_ok=True)
    db = out_dir / MAP_FILE
    nodes, edges = crg_graph(repo, db, language)
    extra_nodes, extra_edges = overlay(repo, language, nodes, surfaces)
    all_nodes = sorted([*nodes, *extra_nodes], key=lambda n: n.id)
    all_edges = sorted(set(edges) | set(extra_edges))
    digest = graph_hash(all_nodes, all_edges)
    meta = {
        "repo_root": str(repo.resolve()),
        "language": language.value,
        "source_root": source_root,
        "commit": commit,
        "graph_hash": digest,
        "crg_version": CRG_VERSION,
    }
    write_graph(db, all_nodes, all_edges, meta)
    return BuildResult(db, digest, len(all_nodes), len(all_edges), round(time.monotonic() - started, 2))


@contextmanager
def _store(map_path: Path) -> Iterator[tuple[GraphStore, str]]:
    root = read_meta(map_path)["repo_root"]
    store = GraphStore(map_path)
    try:
        yield store, f"{root}/"
    finally:
        store.close()


def impact_files(map_path: Path, files: list[str], max_depth: int = 2, max_nodes: int = 500) -> list[str]:
    """repo-relative files crg reaches from a file-level change, the changed files included."""
    with _store(map_path) as (store, prefix):
        result: dict[str, Any] = store.get_impact_radius(
            [prefix + f for f in files], max_depth=max_depth, max_nodes=max_nodes
        )
    reached = {_rel(str(f), prefix) for f in result.get("impacted_files", [])}
    return sorted(reached | set(files))


def transitive_tests_many(map_path: Path, node_ids: list[str]) -> dict[str, list[str]]:
    """tests crg links to each node directly or through one call hop; one store open for the batch."""
    out: dict[str, list[str]] = {}
    with _store(map_path) as (store, prefix):
        for nid in node_ids:
            rows: list[dict[str, Any]] = store.get_transitive_tests(prefix + nid)
            out[nid] = sorted({_rel(str(r["qualified_name"]), prefix) for r in rows})
    return out
