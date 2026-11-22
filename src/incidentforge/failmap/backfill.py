"""adds map node, blast radius, fix scope and fault-based difficulty to tasks that predate the map (D-60, D-98)."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from incidentforge.failmap.difficulty import difficulty_from_faults, fix_scope
from incidentforge.failmap.radius import Graph
from incidentforge.failmap.store import MapNode, read_annotations

MAP_KEYS = ("map_node", "blast_radius", "fix_scope")


@dataclass(frozen=True)
class Backfill:
    task_id: str
    difficulty: str
    map_node: str | None
    blast_radius: int | None
    fix_scope: str | None
    mapped: bool = True  # false when the target had no map, so map keys were not recomputed


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _short(node_id: str) -> str:
    # backend/app/core/config.py::Settings.ACCESS_TOKEN_EXPIRE_MINUTES#env:X -> ACCESS_TOKEN_EXPIRE_MINUTES
    return node_id.split("::")[-1].split("#")[0].rsplit(".", 1)[-1]


def pick_node(
    task_name: str, family: str, seeds: list[str], files: tuple[str, ...], graph: Graph, tags: dict[str, list[str]]
) -> str | None:
    """the family-tagged node in the patched files that the task is about, so it is visible and pinned on the map."""
    subject = _norm(re.sub(r"^[a-z]+-\d+-", "", task_name))
    cands = [n for n in graph.nodes.values() if n.file in files and family in tags.get(n.id, [])]

    def rank(node: MapNode) -> tuple[bool, bool, bool, str]:
        short = _norm(_short(node.id))
        named = bool(short) and (short.startswith(subject) or subject.startswith(short))
        touched = any(s == node.id or s.startswith(node.id + ".") or node.id.startswith(s + ".") for s in seeds)
        return (not named, not touched, node.kind != "Class", node.id)

    if cands:
        return sorted(cands, key=rank)[0].id
    existing = [s for s in seeds if s in graph.nodes]
    if existing:
        return existing[0]
    # a patch that only adds files: the slug names the surface it came from, so look in the same package (F-61)
    dirs = {f.rpartition("/")[0] for f in files}
    near = [n for n in graph.nodes.values() if n.file.rpartition("/")[0] in dirs and rank(n)[0] is False]
    if not near:
        return None
    return sorted(near, key=lambda n: (_norm(_short(n.id)) != subject, family not in tags.get(n.id, []), *rank(n)))[
        0
    ].id


def plan(task_dir: Path, graph: Graph | None, tags: dict[str, list[str]]) -> Backfill:
    meta = tomllib.loads((task_dir / "task.toml").read_text())["metadata"]
    task_id = f"{task_dir.parent.name}/{task_dir.name}"
    level = difficulty_from_faults(len(meta.get("fault_cases") or []))
    patch_file = task_dir / "solution" / "reference.patch"
    if graph is None:
        return Backfill(task_id, level, None, None, None, mapped=False)
    if not patch_file.exists():
        return Backfill(task_id, level, None, None, None)
    seeds, files = graph.seeds_for_patch(patch_file.read_text())
    if not seeds:
        return Backfill(task_id, level, None, None, None)
    r = graph.radius(seeds, extra_files=files)
    node = pick_node(task_dir.name, str(meta.get("family", "")), seeds, files, graph, tags)
    return Backfill(task_id, level, node, r.size, fix_scope(r.size))


def apply(task_dir: Path, b: Backfill) -> bool:
    """rewrites only [metadata] lines so the rest of task.toml stays byte-identical; true if it changed."""
    text = (task_dir / "task.toml").read_text()
    # never drop map keys that could not be recomputed (F-60)
    strip = [k for k in MAP_KEYS if b.mapped and (k != "map_node" or b.map_node is not None)]
    lines = [ln for ln in text.splitlines() if not (strip and re.match(rf"^({'|'.join(strip)}) = ", ln))]
    out: list[str] = []
    for ln in lines:
        if ln.startswith("difficulty = "):
            ln = f"difficulty = {json.dumps(b.difficulty)}"
        out.append(ln)
        if ln.startswith("fault_cases = ") and b.mapped:
            extra = {"map_node": b.map_node, "blast_radius": b.blast_radius, "fix_scope": b.fix_scope}
            out += [f"{k} = {json.dumps(v)}" for k, v in extra.items() if v is not None]
    new = "\n".join(out) + ("\n" if text.endswith("\n") else "")
    if new == text:
        return False
    (task_dir / "task.toml").write_text(new)
    return True


def backfill(tasks_root: Path, work_root: Path) -> list[Backfill]:
    done: list[Backfill] = []
    for target_dir in sorted(p for p in tasks_root.iterdir() if p.is_dir()):
        map_path = work_root / target_dir.name / "map.sqlite"
        graph = Graph(map_path) if map_path.exists() else None
        tags = {k: a.tags for k, a in read_annotations(map_path).items()} if graph else {}
        for task_dir in sorted(p for p in target_dir.iterdir() if (p / "task.toml").exists()):
            b = plan(task_dir, graph, tags)
            apply(task_dir, b)
            done.append(b)
    return done
