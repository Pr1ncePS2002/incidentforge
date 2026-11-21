"""failure map page: tolerant input, coverage numbers, offline html, png export and the cli."""

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from incidentforge import map_render as mr
from incidentforge.budget import Ledger
from incidentforge.cli import app
from incidentforge.report import build as build_report

FIXTURE = Path(__file__).parent / "fixtures" / "map" / "map.json"


def fixture_map() -> dict[str, Any]:
    return mr.normalise(json.loads(FIXTURE.read_text()))


def test_normalise_drops_broken_parts_and_fills_defaults() -> None:
    m = mr.normalise(
        {
            "nodes": [
                {"id": "a.b.f", "file": "a/b.py", "families": ["x", "x"], "blast_radius": "n/a", "covered": "yes"},
                {"name": "no id"},
                "junk",
                {"id": "g", "module": "m"},
            ],
            "edges": [
                {"source": "a.b.f", "target": "g"},
                {"source": "a.b.f", "target": "a.b.f"},
                {"source": "a.b.f", "target": "missing"},
            ],
            "tasks": [{"task_id": "t/1", "node_id": "g"}, {"task_id": "t/1", "node_id": "g"}, {"node_id": "g"}],
        }
    )
    f, g = m["nodes"]
    assert (f["name"], f["module"], f["kind"], f["families"], f["blast_radius"], f["covered"]) == (
        "f",
        "a",
        "function",
        ["x"],
        0,
        None,
    )
    assert g["module"] == "m" and g["file"] == ""
    assert m["edges"] == [{"source": "a.b.f", "target": "g", "kind": "edge"}]
    assert [t["task_id"] for t in m["tasks"]] == ["t/1"]
    assert m["target"] == "unknown"
    assert mr.normalise({"nodes": [{"id": "solo"}]})["nodes"][0]["module"] == "."


def test_normalise_reads_the_builder_shape() -> None:
    # v2-map writes tags, is_test and crg kinds; tests and files are left off the page
    m = mr.normalise(
        {
            "nodes": [
                {"id": "f", "kind": "Function", "file": "internal/config/parser/p.go", "tags": ["fail-fast-config"]},
                {"id": "t", "kind": "Function", "file": "x_test.go", "is_test": True},
                {"id": "file", "kind": "File", "file": "internal/config/parser/p.go"},
            ],
            "edges": [{"kind": "TESTED_BY", "source": "f", "target": "t", "line": 3}],
        }
    )
    assert [(n["id"], n["module"], n["families"]) for n in m["nodes"]] == [
        ("f", "internal/config", ["fail-fast-config"])
    ]
    assert m["edges"] == []


def test_coverage_counts_per_family_and_module() -> None:
    cov = mr.coverage(fixture_map())
    assert cov["nodes"] == 7 and cov["unplaced_tasks"] == 1
    assert cov["total"] == {"surfaces": 5, "with_task": 2, "tasks": 3, "covered": 2, "uncovered": 3}
    assert cov["by_family"]["fail-fast-config"] == {
        "surfaces": 1,
        "with_task": 1,
        "tasks": 1,
        "covered": 1,
        "uncovered": 0,
    }
    assert cov["by_family"]["tolerant-typed-config"]["with_task"] == 0
    assert cov["by_module"]["app.core.config"] == {
        "surfaces": 2,
        "with_task": 1,
        "tasks": 2,
        "covered": 1,
        "uncovered": 1,
    }
    assert cov["by_module"]["app.core.db"] == {"surfaces": 1, "with_task": 0, "tasks": 0, "covered": 0, "uncovered": 1}
    # untagged nodes are not surfaces
    assert "app.utils" in cov["by_module"] and set(mr.by_target([fixture_map()])) == {"demo"}


def test_snapshot_merges_tasks_from_task_metadata(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks" / "demo"
    for name, meta in [
        ("rd-001-engine", 'node_id = "app.core.db.create_engine"\nfamily = "resource-aware-defaults"'),
        ("ff-001-settings", 'node_id = "app.core.config.Settings"\nfamily = "other"'),
        ("xx-001-plain", 'family = "fail-fast-config"'),
        ("bad", "= not toml"),
    ]:
        (tasks / name).mkdir(parents=True)
        (tasks / name / "task.toml").write_text(f"[metadata]\n{meta}\n")
    out = mr.snapshot(FIXTURE, tmp_path / "reports", tmp_path / "tasks")
    assert out == tmp_path / "reports" / "map" / "demo.json"
    snap = json.loads(out.read_text())
    ids = {t["task_id"]: t for t in snap["tasks"]}
    assert "demo/rd-001-engine" in ids and "demo/xx-001-plain" not in ids
    # the map's own task row wins over the task.toml copy
    assert ids["demo/ff-001-settings"]["family"] == "fail-fast-config"
    assert mr.load_snapshots(tmp_path / "reports")[0]["target"] == "demo"


def test_render_is_self_contained_and_escapes_data(tmp_path: Path) -> None:
    m = fixture_map()
    m["nodes"][0]["name"] = "</script><b>x"
    page = mr.render([m, {**fixture_map(), "target": "other"}])
    assert "https://d3js.org v7.9.0" in page
    assert "</script><b>x" not in page and "<\\/script><b>x" in page
    # nothing is fetched: no external scripts, styles or images
    assert not re.search(r'(src|href)="(https?:)?//', page)
    assert page.count('class="cov"') == 2 and "hidden" in page
    assert 'href="index.html"' in page


def test_d3_checksum_is_enforced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert mr.d3_source().startswith("// https://d3js.org v7.9.0")
    shutil.copytree(mr.ASSETS, tmp_path / "assets")
    (tmp_path / "assets" / mr.D3_FILE).write_text("alert(1)")
    monkeypatch.setattr(mr, "ASSETS", tmp_path / "assets")
    with pytest.raises(RuntimeError, match="sha256"):
        mr.d3_source()


def test_render_all_and_colours(tmp_path: Path) -> None:
    assert mr.render_all(tmp_path) is None
    mr.snapshot(FIXTURE, tmp_path)
    page = mr.render_all(tmp_path)
    assert page == tmp_path / "map.html" and page.read_text().startswith("<!doctype html>")
    extra = {"nodes": [{"id": "n", "families": ["new-family"]}]}
    cols = mr.colours([mr.normalise(extra)])
    assert cols["fail-fast-config"] == mr.FAMILY_COLOURS["fail-fast-config"]
    assert cols["new-family"] in mr.EXTRA_COLOURS


def test_export_png_runs_chrome_in_png_mode(tmp_path: Path) -> None:
    page = tmp_path / "map.html"
    page.write_text("<html></html>")
    png = tmp_path / "out" / "map.png"
    seen: list[list[str]] = []

    def fake(cmd: list[str]) -> None:
        seen.append(cmd)
        png.write_bytes(b"\x89PNG")

    assert mr.export_png(page, png, run=fake, chrome="chrome") == png
    assert seen[0][0] == "chrome" and seen[0][-1].endswith("map.html?png=1")
    assert f"--screenshot={png.resolve()}" in seen[0]
    with pytest.raises(RuntimeError, match="did not write"):
        mr.export_png(page, tmp_path / "none.png", run=lambda cmd: None, chrome="chrome")


def test_find_chrome(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = tmp_path / "chrome"
    fake.write_text("")
    monkeypatch.setenv("CHROME", str(fake))
    assert mr.find_chrome() == str(fake)
    monkeypatch.setenv("CHROME", "")
    monkeypatch.setattr(mr, "CHROME_CANDIDATES", ("no-such-browser-xyz",))
    with pytest.raises(RuntimeError, match="not found"):
        mr.find_chrome()


def test_cli_map_render(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "work" / "demo").mkdir(parents=True)
    shutil.copy(FIXTURE, tmp_path / "work" / "demo" / "map.json")
    args = ["map", "render", "--work", str(tmp_path / "work"), "--reports", str(tmp_path / "r")]
    args += ["--tasks", str(tmp_path / "tasks")]
    runner = CliRunner()
    res = runner.invoke(app, [*args, "--target", "demo"])
    assert res.exit_code == 0 and (tmp_path / "r" / "map.html").exists(), res.output
    res = runner.invoke(app, [*args, "--target", "nope"])
    assert res.exit_code == 1 and "forge map build --target nope" in res.output

    def boom(page: Path, png: Path) -> Path:
        raise RuntimeError("chrome/chromium not found")

    monkeypatch.setattr(mr, "export_png", boom)
    res = runner.invoke(app, [*args, "--target", "demo", "--png", str(tmp_path / "m.png")])
    assert res.exit_code == 1 and "png export failed" in res.output
    monkeypatch.setattr(mr, "export_png", lambda page, png: png)
    res = runner.invoke(app, [*args, "--target", "demo", "--png", str(tmp_path / "m.png")])
    assert res.exit_code == 0 and "m.png" in res.output


def test_report_links_the_map_and_shows_coverage(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    mr.snapshot(FIXTURE, reports)
    out = build_report(reports / "index.html", tmp_path / "tasks", reports, Ledger(tmp_path / "l.jsonl"))
    page = out.read_text()
    assert 'href="map.html"' in page and "tagged surfaces" in page and "app.core.config" in page
    assert (reports / "map.html").exists()
    summary = json.loads((reports / "summary.json").read_text())
    assert summary["map_coverage"]["demo"]["total"]["surfaces"] == 5
