"""blast radius of a map node (files a fix would touch) and the difficulty it maps to (D-66)."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from incidentforge.failmap import build
from incidentforge.failmap.store import (
    Annotation,
    MapEdge,
    MapNode,
    module_of,
    read_annotations,
    read_edges,
    read_meta,
    read_nodes,
    write_annotations,
)

DEPENDENCY_EDGES = ("CALLS", "REFERENCES", "INHERITS")
OWNER_EDGES = ("READS_CONFIG", "READS_ENV", "HANDLES")
MAX_DEPTH = 2
# d-66 table: easy = 1 file; medium = 2-3 files or call depth >= 2; hard = 4+ files or > 1 module
MEDIUM_FILES = 2
HARD_FILES = 4
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")


@dataclass(frozen=True)
class Radius:
    files: tuple[str, ...]
    depth: int
    modules: tuple[str, ...]
    difficulty: str

    @property
    def size(self) -> int:
        return len(self.files)


def difficulty(files: int, depth: int, modules: int) -> str:
    if files >= HARD_FILES or modules > 1:
        return "hard"
    if files >= MEDIUM_FILES or depth >= MAX_DEPTH:
        return "medium"
    return "easy"


class Graph:
    """in-memory view of the fm tables for repeated radius queries."""

    def __init__(self, map_path: Path) -> None:
        self.map_path = map_path
        self.nodes: dict[str, MapNode] = read_nodes(map_path)
        self.source_root = read_meta(map_path).get("source_root", ".")
        self.callers: dict[str, set[str]] = defaultdict(set)
        self.children: dict[str, set[str]] = defaultdict(set)
        self.owner: dict[str, str] = {}
        edges: list[MapEdge] = read_edges(map_path)
        for e in edges:
            if e.kind in DEPENDENCY_EDGES:
                self.callers[e.target].add(e.source)
            elif e.kind == "CONTAINS":
                self.children[e.source].add(e.target)
            elif e.kind in OWNER_EDGES:
                self.owner[e.target] = e.source

    def unit(self, node_id: str) -> str:
        """the code a task would edit: overlay nodes resolve to the function/class that owns them."""
        return self.owner.get(node_id, node_id)

    def radius(self, node_ids: list[str], extra_files: tuple[str, ...] = ()) -> Radius:
        units = sorted({self.unit(n) for n in node_ids if self.unit(n) in self.nodes})
        files = set(extra_files) | {self.nodes[u].file for u in units}
        depth = 0
        file_units = [u for u in units if self.nodes[u].kind == "File"]
        if file_units:
            # module-level code has no callers; crg's file impact at one hop stands in for them
            reached = build.impact_files(self.map_path, [self.nodes[u].file for u in file_units], max_depth=1)
            files |= {f for f in reached if f in self.nodes and not self.nodes[f].is_test}
        frontier = set(units)
        for u in units:
            if self.nodes[u].kind == "Class":
                frontier |= self.children[u]
        seen = set(frontier)
        for level in range(1, MAX_DEPTH + 1):
            nxt = {c for n in frontier for c in self.callers[n] if c not in seen and c in self.nodes}
            nxt = {c for c in nxt if not self.nodes[c].is_test}
            if not nxt:
                break
            depth = level
            files |= {self.nodes[c].file for c in nxt}
            seen |= nxt
            frontier = nxt
        modules = sorted({module_of(f, self.source_root) for f in files})
        return Radius(tuple(sorted(files)), depth, tuple(modules), difficulty(len(files), depth, len(modules)))

    def seeds_for_patch(self, patch: str) -> tuple[list[str], tuple[str, ...]]:
        """innermost function/class touched by each hunk of a unified diff, plus the files it edits."""
        seeds: list[str] = []
        files: list[str] = []
        current: str | None = None
        for line in patch.splitlines():
            if line.startswith("+++ "):
                path = line[4:].strip()
                current = None if path == "/dev/null" else path.removeprefix("b/")
                if current is not None:
                    files.append(current)
                continue
            m = _HUNK.match(line)
            if m and current is not None:
                start = int(m.group(1))
                end = start + max(int(m.group(2) or "1") - 1, 0)
                seeds.append(self._innermost(current, start, end))
        return sorted(set(seeds)), tuple(sorted(set(files)))

    def _innermost(self, file: str, start: int, end: int) -> str:
        best: MapNode | None = None
        for n in self.nodes.values():
            if n.file != file or n.kind not in {"Function", "Class"}:
                continue
            if n.line_start <= end and start <= n.line_end and (best is None or n.line_start >= best.line_start):
                best = n
        return best.id if best else file


def radius_for_patch(map_path: Path, patch: str) -> Radius:
    g = Graph(map_path)
    seeds, files = g.seeds_for_patch(patch)
    return g.radius(seeds, extra_files=files)


def annotate(map_path: Path) -> dict[str, Radius]:
    """blast radius and difficulty for every tagged or surface-bearing node, written into fm_annot."""
    g = Graph(map_path)
    annots = read_annotations(map_path)
    out: dict[str, Radius] = {}
    for nid, node in g.nodes.items():
        if not (annots.get(nid) and annots[nid].tags) and "surface_kinds" not in node.attrs:
            continue
        r = g.radius([nid])
        out[nid] = r
        a = annots.get(nid, Annotation(nid))
        a.blast_radius, a.call_depth, a.difficulty = r.size, r.depth, r.difficulty
        annots[nid] = a
    write_annotations(map_path, annots.values())
    return out
