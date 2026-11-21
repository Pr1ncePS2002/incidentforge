"""our own tables inside map.sqlite (fm_*), kept next to crg's tables so one file holds the whole map."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

# kinds crg emits plus the ones our overlay pass adds
OVERLAY_KINDS = ("config_read", "env_read", "handler")
UNIT_KINDS = ("File", "Class", "Function", "Test", "Type")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS fm_nodes (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, file TEXT NOT NULL,
  line_start INTEGER NOT NULL, line_end INTEGER NOT NULL, language TEXT NOT NULL,
  is_test INTEGER NOT NULL, attrs TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fm_edges (
  kind TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL, line INTEGER NOT NULL,
  PRIMARY KEY (kind, source, target)
);
CREATE TABLE IF NOT EXISTS fm_annot (
  node_id TEXT PRIMARY KEY, tags TEXT NOT NULL DEFAULT '[]', blast_radius INTEGER, call_depth INTEGER,
  difficulty TEXT, covered INTEGER, risk_score REAL, cluster TEXT
);
CREATE TABLE IF NOT EXISTS fm_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@dataclass
class MapNode:
    id: str
    kind: str
    name: str
    file: str
    line_start: int
    line_end: int
    language: str
    is_test: bool = False
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def is_overlay(self) -> bool:
        return self.kind in OVERLAY_KINDS


@dataclass(frozen=True, order=True)
class MapEdge:
    kind: str
    source: str
    target: str
    line: int = 0


@dataclass
class Annotation:
    node_id: str
    tags: list[str] = field(default_factory=list)
    blast_radius: int | None = None
    call_depth: int | None = None
    difficulty: str | None = None
    covered: bool | None = None
    risk_score: float | None = None
    cluster: str | None = None


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def write_graph(path: Path, nodes: Iterable[MapNode], edges: Iterable[MapEdge], meta: dict[str, str]) -> None:
    with connect(path) as c:
        c.execute("DELETE FROM fm_nodes")
        c.execute("DELETE FROM fm_edges")
        c.execute("DELETE FROM fm_annot")
        c.executemany(
            "INSERT INTO fm_nodes VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (n.id, n.kind, n.name, n.file, n.line_start, n.line_end, n.language, int(n.is_test), _dump(n.attrs))
                for n in nodes
            ],
        )
        c.executemany("INSERT INTO fm_edges VALUES (?,?,?,?)", [(e.kind, e.source, e.target, e.line) for e in edges])
        c.executemany("INSERT OR REPLACE INTO fm_meta VALUES (?,?)", sorted(meta.items()))


def read_nodes(path: Path) -> dict[str, MapNode]:
    with connect(path) as c:
        rows = c.execute("SELECT * FROM fm_nodes ORDER BY id").fetchall()
    return {r[0]: MapNode(r[0], r[1], r[2], r[3], r[4], r[5], r[6], bool(r[7]), json.loads(r[8])) for r in rows}


def read_edges(path: Path) -> list[MapEdge]:
    with connect(path) as c:
        rows = c.execute("SELECT kind, source, target, line FROM fm_edges ORDER BY kind, source, target").fetchall()
    return [MapEdge(*r) for r in rows]


def read_meta(path: Path) -> dict[str, str]:
    with connect(path) as c:
        return dict(c.execute("SELECT key, value FROM fm_meta").fetchall())


def set_meta(path: Path, **values: str) -> None:
    with connect(path) as c:
        c.executemany("INSERT OR REPLACE INTO fm_meta VALUES (?,?)", sorted(values.items()))


def read_annotations(path: Path) -> dict[str, Annotation]:
    with connect(path) as c:
        rows = c.execute("SELECT * FROM fm_annot ORDER BY node_id").fetchall()
    return {
        r[0]: Annotation(r[0], json.loads(r[1]), r[2], r[3], r[4], None if r[5] is None else bool(r[5]), r[6], r[7])
        for r in rows
    }


def write_annotations(path: Path, annots: Iterable[Annotation]) -> None:
    """upsert; callers pass the full annotation so later stages never drop earlier fields."""
    with connect(path) as c:
        c.executemany(
            "INSERT OR REPLACE INTO fm_annot VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    a.node_id,
                    json.dumps(sorted(a.tags)),
                    a.blast_radius,
                    a.call_depth,
                    a.difficulty,
                    None if a.covered is None else int(a.covered),
                    a.risk_score,
                    a.cluster,
                )
                for a in annots
            ],
        )


def graph_hash(nodes: Iterable[MapNode], edges: Iterable[MapEdge]) -> str:
    """sha256 over sorted node and edge content; no timestamps, ids or absolute paths go in."""
    h = hashlib.sha256()
    for n in sorted(nodes, key=lambda n: n.id):
        row = [n.id, n.kind, n.name, n.file, n.line_start, n.line_end, n.language, n.is_test, n.attrs]
        h.update(_dump(row).encode() + b"\n")
    for e in sorted(edges):
        h.update(_dump([e.kind, e.source, e.target, e.line]).encode() + b"\n")
    return h.hexdigest()


def module_of(file: str, source_root: str = ".") -> str:
    """first two directories under the source root: a go package or a python subpackage; root files are '.'."""
    path = PurePosixPath(file)
    root = PurePosixPath(source_root)
    if str(root) != "." and path.is_relative_to(root):
        path = path.relative_to(root)
    return "/".join(path.parts[:-1][:2]) or "."


def _dump(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))
