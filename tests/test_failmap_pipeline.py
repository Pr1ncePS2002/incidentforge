"""forge map build end to end on a fixture repo: map.json schema, surface annotation, cli and sampling."""

import json
from pathlib import Path

import pytest
from failmap_repos import py_repo, target
from typer.testing import CliRunner

from incidentforge import cli
from incidentforge.failmap.pipeline import SCHEMA_VERSION, annotate_surfaces, build_map
from incidentforge.families.sampling import rank_surfaces
from incidentforge.models import Language, Surface

NODE_KEYS = {
    "id", "kind", "name", "file", "line", "module", "families", "surface_kinds",
    "blast_radius", "difficulty", "covered", "risk_score", "cluster",
}  # fmt: skip


def test_build_map_and_json(tmp_path: Path):
    repo = py_repo(tmp_path / "repo")
    s = build_map(target("demo", Language.python), repo, tmp_path / "work")
    assert s.map_path == tmp_path / "work" / "demo" / "map.sqlite" and s.coverage == "static"
    assert s.tagged > 0 and s.clusters == 2 and set(s.timings) >= {"graph", "coverage", "total"}
    doc = json.loads(s.json_path.read_text())
    assert doc["schema"] == SCHEMA_VERSION and doc["target"] == "demo" and doc["graph_hash"] == s.graph_hash
    assert doc["language"] == "python" and doc["commit"] == "0123456789abcdef0123"
    assert all(set(n) == NODE_KEYS for n in doc["nodes"])
    assert not any(n["file"].startswith("tests/") for n in doc["nodes"])
    ids = {n["id"] for n in doc["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in doc["edges"])
    handler = next(n for n in doc["nodes"] if n["id"] == "app/crud.py::create_user#handler")
    assert handler["families"] == ["idempotent-consumer"] and handler["cluster"] == "c001"
    assert handler["difficulty"] == "hard" and handler["covered"] is True
    assert {c["id"] for c in doc["clusters"]} == {"c001", "c002"}
    again = build_map(target("demo", Language.python), repo, tmp_path / "work")
    assert again.json_path.read_text() == s.json_path.read_text()


def test_build_map_uses_cached_coverage(tmp_path: Path):
    repo = py_repo(tmp_path / "repo")
    out = tmp_path / "work" / "demo"
    out.mkdir(parents=True)
    (out / "coverage-0123456789ab.json").write_text(json.dumps({"app/export.py": {"executed": [5], "missing": []}}))
    s = build_map(target("demo", Language.python), repo, tmp_path / "work", run_coverage=True)
    assert s.coverage == "cached"


def test_annotate_surfaces(tmp_path: Path):
    repo = py_repo(tmp_path / "repo")
    s = build_map(target("demo", Language.python), repo, tmp_path / "work")
    surfaces = [
        Surface(file="app/crud.py", symbol="create_user", kind="consumer"),
        Surface(file="nowhere.py", symbol="x", kind="consumer"),
    ]
    out = annotate_surfaces(surfaces, s.map_path)
    assert out[0].node_id == "app/crud.py::create_user" and out[0].difficulty == "hard"
    assert out[0].covered is True and out[0].risk_score == 1.0 and out[0].blast_radius == 2
    assert out[1].node_id is None and out[1].difficulty is None
    assert surfaces[0].node_id is None


def test_cli_map_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = py_repo(tmp_path / "repo")
    monkeypatch.setattr("incidentforge.generate.checkout", lambda t, root: repo)
    runner = CliRunner()
    args = ["map", "build", "--target", "demo", "--work", str(tmp_path / "w")]
    unseen = [*args, "--repo-url", "https://example.invalid/x.git", "--commit", "abc", "--language", "python"]
    r = runner.invoke(cli.app, unseen)
    assert r.exit_code == 0, r.output
    assert "graph_hash " in r.output and "timings graph=" in r.output
    assert (tmp_path / "w" / "demo" / "map.json").exists()
    assert runner.invoke(cli.app, [*args, "--repo-url", "u"]).exit_code == 2
    assert runner.invoke(cli.app, args).exit_code == 2
    known = runner.invoke(cli.app, ["map", "build", "--target", "fastapi-template", "--work", str(tmp_path / "w")])
    assert known.exit_code == 0, known.output


def test_rank_surfaces_weights_but_keeps_all():
    hot = Surface(file="a", symbol="hot", kind="consumer", risk_score=2.5)
    cold = Surface(file="a", symbol="cold", kind="consumer", risk_score=1.0)
    plain = Surface(file="a", symbol="plain", kind="consumer")
    first = [rank_surfaces([cold, plain, hot], seed=s)[0].symbol for s in range(200)]
    assert first.count("hot") > first.count("cold")
    assert sorted(x.symbol for x in rank_surfaces([cold, plain, hot])) == ["cold", "hot", "plain"]
    assert rank_surfaces([cold, hot], seed=3) == rank_surfaces([cold, hot], seed=3)
