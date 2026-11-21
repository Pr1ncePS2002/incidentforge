"""crg base graph plus our overlay on tiny fixture repos; the graph hash must be stable."""

import shutil
from pathlib import Path

import pytest
from failmap_repos import go_repo, py_repo

from incidentforge.failmap import build as build_mod
from incidentforge.failmap.build import build, impact_files, transitive_tests_many
from incidentforge.failmap.overlay import is_test_path, surface_node_id
from incidentforge.failmap.store import MapNode, graph_hash, module_of, read_edges, read_meta, read_nodes
from incidentforge.models import Language, Surface


@pytest.fixture(scope="module")
def py_map(tmp_path_factory: pytest.TempPathFactory) -> Path:
    d = tmp_path_factory.mktemp("py")
    return build(py_repo(d / "repo"), Language.python, d / "out", commit="abc").map_path


@pytest.fixture(scope="module")
def go_map(tmp_path_factory: pytest.TempPathFactory) -> Path:
    d = tmp_path_factory.mktemp("go")
    return build(go_repo(d / "repo"), Language.go, d / "out").map_path


def test_python_overlay_nodes(py_map: Path):
    nodes = read_nodes(py_map)
    db = nodes["app/core/config.py::Settings.DATABASE_URL"]
    assert db.kind == "config_read" and db.attrs["has_default"] is False and db.attrs["validated"] is False
    assert nodes["app/core/config.py::Settings.SECRET_KEY"].attrs["placeholder_default"] is True
    assert nodes["app/core/config.py::Settings.PROJECT_NAME"].attrs["validated"] is True
    pool = nodes["app/core/config.py::Settings.DB_POOL_SIZE"]
    assert pool.attrs["pool"] and pool.attrs["typed"] and pool.attrs["surface_kinds"] == ["pool-config"]
    env = nodes["app/core/config.py::worker_count#env:WORKERS"]
    assert env.attrs == {"key": "WORKERS", "has_default": False, "parsed": True}
    assert nodes["app/core/config.py#env:DEBUG"].attrs["has_default"] is True
    assert nodes["app/crud.py::upsert_item#handler"].attrs["dedupe"] is True
    assert nodes["app/crud.py::create_user#handler"].attrs["dedupe"] is False
    assert nodes["app/core/db.py"].attrs["surface_kinds"] == ["pool-config"]
    assert not any(n.file.startswith("tests/") and n.is_overlay for n in nodes.values())


def test_python_edges_and_meta(py_map: Path):
    edges = {(e.kind, e.source, e.target) for e in read_edges(py_map)}
    assert ("CALLS", "app/api/routes.py::handle_signup", "app/crud.py::create_user") in edges
    assert ("TESTED_BY", "app/crud.py::create_user", "tests/test_crud.py::test_create_user") in edges
    assert ("READS_CONFIG", "app/core/config.py::Settings", "app/core/config.py::Settings.DATABASE_URL") in edges
    assert ("HANDLES", "app/crud.py::create_user", "app/crud.py::create_user#handler") in edges
    meta = read_meta(py_map)
    assert meta["language"] == "python" and meta["commit"] == "abc" and len(meta["graph_hash"]) == 64


def test_go_overlay_nodes(go_map: Path):
    nodes = read_nodes(go_map)
    assert nodes["internal/config/options.go::Options.Port"].attrs["has_default"] is True
    url = nodes["internal/config/options.go::Options.DBURL"].attrs
    assert url["key"] == "DATABASE_URL" and url["validated"] is True
    assert nodes["internal/config/options.go::Options.MaxConns"].attrs["pool"] is True
    base = nodes["internal/config/options.go::config:BASE_URL"].attrs
    assert base["has_default"] is True and base["typed"] is False
    size = nodes["internal/config/options.go::config:POOL_SIZE"].attrs
    assert size["has_default"] is False and size["validated"] is True and size["typed"] is True
    assert nodes["internal/config/options.go::Workers#env:WORKERS"].attrs["parsed"] is True
    assert nodes["internal/config/options.go::Home#env:HOME"].attrs["has_default"] is True
    assert nodes["internal/config/viper.go::Load#config:cache.prefix"].attrs["has_default"] is True
    assert nodes["internal/config/viper.go::Load#config:region"].attrs["has_default"] is False
    assert nodes["internal/config/viper.go::Timeout#config:timeout"].attrs["typed"] is True
    assert "internal/worker/consumer.go::HandleMessage#handler" in nodes
    # untagged fields of an internal struct are not settings
    assert not any(n.id.startswith("internal/config/options.go::configValue.") for n in nodes.values())


def test_hash_is_stable_and_path_independent(tmp_path: Path, py_map: Path):
    a = build(py_repo(tmp_path / "a"), Language.python, tmp_path / "oa")
    again = build(tmp_path / "a", Language.python, tmp_path / "oa")
    moved = tmp_path / "elsewhere" / "b"
    shutil.copytree(tmp_path / "a", moved)
    b = build(moved, Language.python, tmp_path / "ob")
    assert a.graph_hash == again.graph_hash == b.graph_hash == read_meta(py_map)["graph_hash"]
    assert a.nodes == b.nodes and a.edges == b.edges and a.seconds >= 0


def test_hash_changes_with_content():
    n = MapNode("f.py", "File", "f.py", "f.py", 1, 2, "python")
    other = MapNode("f.py", "File", "f.py", "f.py", 1, 3, "python")
    assert graph_hash([n], []) != graph_hash([other], [])


def test_impact_and_tests(py_map: Path):
    assert impact_files(py_map, ["app/crud.py"], max_depth=1)[0] == "app/api/routes.py"
    tests = transitive_tests_many(py_map, ["app/crud.py::create_user", "app/export.py::save_config"])
    assert tests["app/crud.py::create_user"] == ["tests/test_crud.py::test_create_user"]
    assert tests["app/export.py::save_config"] == []


def test_serial_parse_env_restored(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CRG_SERIAL_PARSE", "0")
    with build_mod._serial_parse():
        import os

        assert os.environ["CRG_SERIAL_PARSE"] == "1"
    import os

    assert os.environ["CRG_SERIAL_PARSE"] == "0"
    monkeypatch.delenv("CRG_SERIAL_PARSE")
    with build_mod._serial_parse():
        pass
    assert "CRG_SERIAL_PARSE" not in os.environ


def test_surface_node_id():
    nodes = {
        "a.py": MapNode("a.py", "File", "a.py", "a.py", 1, 9, "python"),
        "a.py::f": MapNode("a.py::f", "Function", "f", "a.py", 2, 3, "python"),
        "a.py#env:X": MapNode("a.py#env:X", "env_read", "X", "a.py", 5, 5, "python"),
        "a.py::S.POOL_SIZE": MapNode("a.py::S.POOL_SIZE", "config_read", "POOL_SIZE", "a.py", 7, 7, "python"),
    }
    assert surface_node_id(Surface(file="a.py", symbol="f", kind="consumer"), nodes) == "a.py::f"
    assert surface_node_id(Surface(file="a.py", symbol="<module>:5", kind="env-read"), nodes) == "a.py#env:X"
    assert surface_node_id(Surface(file="a.py", symbol="create_engine:8", kind="pool-config"), nodes) == "a.py"
    assert surface_node_id(Surface(file="a.py", symbol="S.POOL_SIZE", kind="pool-config"), nodes) == "a.py::S.POOL_SIZE"
    assert surface_node_id(Surface(file="b.py", symbol="g", kind="consumer"), nodes) is None


def test_helpers():
    assert module_of("backend/app/core/config.py", "backend") == "app/core"
    assert module_of("internal/config/options.go") == "internal/config"
    assert module_of("main.go") == "."
    assert is_test_path("tests/test_x.py") and is_test_path("pkg/a_test.go") and not is_test_path("app/x.py")
