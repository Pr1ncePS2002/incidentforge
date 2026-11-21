"""blast radius, difficulty table, patch seeds and clusters on fixture maps."""

from pathlib import Path

import pytest
from failmap_repos import go_repo, py_repo

from incidentforge.failmap import cluster, radius
from incidentforge.failmap.build import build
from incidentforge.failmap.radius import Graph, difficulty, radius_for_patch
from incidentforge.failmap.store import Annotation, MapEdge, MapNode, read_annotations, write_annotations, write_graph
from incidentforge.failmap.tag import tag
from incidentforge.models import Language


@pytest.fixture(scope="module")
def py_map(tmp_path_factory: pytest.TempPathFactory) -> Path:
    d = tmp_path_factory.mktemp("py")
    m = build(py_repo(d / "repo"), Language.python, d / "out").map_path
    tag(m)
    return m


@pytest.mark.parametrize(
    ("files", "depth", "modules", "want"),
    [(1, 0, 1, "easy"), (1, 1, 1, "easy"), (1, 2, 1, "medium"), (2, 0, 1, "medium"), (3, 1, 1, "medium"),
     (4, 0, 1, "hard"), (2, 0, 2, "hard")],
)  # fmt: skip
def test_difficulty_table(files: int, depth: int, modules: int, want: str):
    assert difficulty(files, depth, modules) == want


def test_radius_follows_callers(py_map: Path):
    g = Graph(py_map)
    r = g.radius(["app/core/config.py::worker_count#env:WORKERS"])
    assert r.files == ("app/api/routes.py", "app/core/config.py", "app/core/db.py", "app/crud.py")
    assert r.depth == 2 and r.difficulty == "hard" and r.size == 4
    assert g.radius(["app/export.py::save_config"]).difficulty == "easy"
    # module-level code borrows crg's file impact
    assert "app/crud.py" in g.radius(["app/core/config.py#env:DEBUG"]).files


def test_annotate_writes_difficulty(py_map: Path):
    out = radius.annotate(py_map)
    annots = read_annotations(py_map)
    assert annots["app/crud.py::create_user#handler"].difficulty == out["app/crud.py::create_user#handler"].difficulty
    assert annots["app/export.py::save_config"].blast_radius == 1
    assert annots["app/export.py::save_config"].tags == ["config-round-trip"]


def test_patch_seeds(py_map: Path):
    patch = (
        "diff --git a/app/crud.py b/app/crud.py\n--- a/app/crud.py\n+++ b/app/crud.py\n"
        "@@ -4,2 +4,3 @@ def create_user\n+    pass\n"
        "--- a/app/new.py\n+++ b/app/new.py\n@@ -0,0 +1 @@\n+x = 1\n"
        "--- a/app/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x = 1\n"
    )
    seeds, files = Graph(py_map).seeds_for_patch(patch)
    assert seeds == ["app/crud.py::create_user", "app/new.py"]
    assert files == ("app/crud.py", "app/new.py")
    r = radius_for_patch(py_map, patch)
    assert "app/api/routes.py" in r.files and r.difficulty == "hard"


def test_clusters_on_fixture(tmp_path: Path):
    m = build(go_repo(tmp_path / "r"), Language.go, tmp_path / "o").map_path
    tag(m)
    found = cluster.assign(m)
    assert [c.id for c in found] == ["c001", "c002"]
    assert found[0].files == ("internal/config/options.go", "internal/worker/consumer.go")
    assert "idempotent-consumer" in found[0].families
    annots = read_annotations(m)
    assert annots["internal/config/viper.go::Load#config:region"].cluster == "c002"
    assert cluster.clusters(m) == found
    # no two clusters share a file
    files = [f for c in found for f in c.files]
    assert len(files) == len(set(files))


def _synthetic(tmp_path: Path, n: int) -> Path:
    """n tagged functions chained by calls across two modules, so one component."""
    nodes, edges = [], []
    for i in range(n):
        mod = "a" if i < n // 2 else "b"
        nid = f"pkg/{mod}/f{i}.go::F{i}"
        nodes += [MapNode(f"pkg/{mod}/f{i}.go", "File", "f", f"pkg/{mod}/f{i}.go", 1, 9, "go"),
                  MapNode(nid, "Function", f"F{i}", f"pkg/{mod}/f{i}.go", 2, 3, "go")]  # fmt: skip
        if i:
            edges.append(MapEdge("CALLS", nid, nodes[-3].id, 2))
    m = tmp_path / "map.sqlite"
    write_graph(m, nodes, edges, {"language": "go", "source_root": ".", "repo_root": str(tmp_path)})
    write_annotations(m, [Annotation(n.id, ["fail-fast-config"]) for n in nodes if n.kind == "Function"])
    return m


def test_oversize_component_splits_by_module_then_file(tmp_path: Path):
    m = _synthetic(tmp_path, 6)
    assert len(cluster.compute(m, max_units=10)) == 1
    by_module = cluster.compute(m, max_units=4)
    assert [c.modules for c in by_module] == [("pkg/a",), ("pkg/b",)]
    by_file = cluster.compute(m, max_units=2)
    assert len(by_file) == 6 and all(len(c.files) == 1 for c in by_file)
    assert [c.id for c in by_file] == [f"c00{i}" for i in range(1, 7)]
