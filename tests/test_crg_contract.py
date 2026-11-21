"""pins the code-review-graph internals the failure map adapter relies on; a crg bump that moves them fails here."""

import inspect
from pathlib import Path

from code_review_graph.graph import GraphStore
from code_review_graph.parser import CodeParser


def test_graphstore_methods_used_by_failmap():
    for name in (
        "get_impact_radius",
        "get_transitive_tests",
        "get_all_nodes",
        "get_all_edges",
        "store_file_nodes_edges",
    ):
        assert callable(getattr(GraphStore, name)), name
    params = inspect.signature(GraphStore.get_impact_radius).parameters
    assert {"changed_files", "max_depth", "max_nodes"} <= params.keys()


def test_parser_handles_python_and_go(tmp_path: Path):
    (tmp_path / "a.py").write_text('import os\ndef load():\n    return os.getenv("X")\n')
    (tmp_path / "b.go").write_text('package m\nimport "os"\nfunc Load() string { return os.Getenv("X") }\n')
    parser = CodeParser()
    for name, fn in (("a.py", "load"), ("b.go", "Load")):
        nodes, edges = parser.parse_file(tmp_path / name)
        assert ("Function", fn) in {(n.kind, n.name) for n in nodes}
        assert "IMPORTS_FROM" in {e.kind for e in edges}
