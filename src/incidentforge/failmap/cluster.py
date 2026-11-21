"""group tagged nodes so two parallel tasks never edit the same code; consumed by v2-parallel."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from incidentforge.failmap.radius import DEPENDENCY_EDGES, Graph
from incidentforge.failmap.store import module_of, read_annotations, read_edges, write_annotations

MAX_UNITS = 12  # above this a component is split by module, then by file


@dataclass(frozen=True)
class Cluster:
    """tagged map nodes sharing code; units are the functions/classes/files a task would edit."""

    id: str
    nodes: tuple[str, ...]
    units: tuple[str, ...]
    files: tuple[str, ...]
    modules: tuple[str, ...]
    families: tuple[str, ...]


class _UnionFind:
    def __init__(self, items: list[str]) -> None:
        self.parent = {i: i for i in items}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # smaller id wins so roots do not depend on union order
            lo, hi = sorted((ra, rb))
            self.parent[hi] = lo


def _split(units: list[str], key: dict[str, str]) -> list[list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for u in units:
        groups[key[u]].append(u)
    return [sorted(groups[k]) for k in sorted(groups)]


def compute(map_path: Path, max_units: int = MAX_UNITS) -> list[Cluster]:
    g = Graph(map_path)
    annots = read_annotations(map_path)
    tagged = sorted(nid for nid, a in annots.items() if a.tags and nid in g.nodes)
    by_unit: dict[str, list[str]] = defaultdict(list)
    for nid in tagged:
        by_unit[g.unit(nid)].append(nid)
    units = sorted(u for u in by_unit if u in g.nodes)
    uf = _UnionFind(units)
    first_in_file: dict[str, str] = {}
    for u in units:
        f = g.nodes[u].file
        if f in first_in_file:
            uf.union(first_in_file[f], u)
        else:
            first_in_file[f] = u
    unit_set = set(units)
    for e in read_edges(map_path):
        if (e.kind in DEPENDENCY_EDGES or e.kind == "CONTAINS") and e.source in unit_set and e.target in unit_set:
            uf.union(e.source, e.target)
    comps: dict[str, list[str]] = defaultdict(list)
    for u in units:
        comps[uf.find(u)].append(u)
    files = {u: g.nodes[u].file for u in units}
    modules = {u: module_of(files[u], g.source_root) for u in units}
    parts: list[list[str]] = []
    for root in sorted(comps):
        comp = sorted(comps[root])
        if len(comp) <= max_units:
            parts.append(comp)
            continue
        for mod_group in _split(comp, modules):
            # a file is never split, so oversize single-file groups stay whole
            parts.extend([mod_group] if len(mod_group) <= max_units else _split(mod_group, files))
    parts.sort(key=lambda p: (min(files[u] for u in p), p[0]))
    out: list[Cluster] = []
    for i, part in enumerate(parts, 1):
        nodes = sorted(n for u in part for n in by_unit[u])
        fams = sorted({t for n in nodes for t in annots[n].tags})
        out.append(
            Cluster(
                id=f"c{i:03d}",
                nodes=tuple(nodes),
                units=tuple(part),
                files=tuple(sorted({files[u] for u in part})),
                modules=tuple(sorted({modules[u] for u in part})),
                families=tuple(fams),
            )
        )
    return out


def assign(map_path: Path, max_units: int = MAX_UNITS) -> list[Cluster]:
    """compute clusters and store each tagged node's cluster id in fm_annot."""
    result = compute(map_path, max_units)
    annots = read_annotations(map_path)
    for a in annots.values():
        a.cluster = None
    for c in result:
        for n in c.nodes:
            annots[n].cluster = c.id
    write_annotations(map_path, annots.values())
    return result


def clusters(map_path: Path, max_units: int = MAX_UNITS) -> list[Cluster]:
    """deterministic, so this equals what `forge map build` stored in fm_annot for the same map."""
    return compute(map_path, max_units)
