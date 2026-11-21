"""failure map page: tolerant input, coverage numbers, offline html, png export and the cli."""

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from incidentforge import map_render as mr
from incidentforge.cli import app
from incidentforge.report import build as build_report

FIXTURE = Path(__file__).parent / "fixtures" / "map" / "map.json"


T = "fastapi-template"
SETTINGS = "backend/app/core/config.py::Settings"
USERCREATE = "backend/app/models.py::UserCreate"


def write_tasks(root: Path) -> Path:
    tasks = root / "tasks" / T
    for name, meta in [
        ("ff-001-settings", f'map_node = "{SETTINGS}"\nfamily = "fail-fast-config"\ndifficulty = "easy"'),
        ("cf-003-usercreate", f'map_node = "{USERCREATE}"\nfamily = "cross-field-validation"'),
        ("xx-001-gone", 'map_node = "backend/app/gone.py::f"\nfamily = "fail-fast-config"'),
        ("xx-002-plain", 'family = "fail-fast-config"'),
        ("bad", "= not toml"),
    ]:
        (tasks / name).mkdir(parents=True)
        (tasks / name / "task.toml").write_text(f"[metadata]\n{meta}\n")
    return root / "tasks"


def fixture_map(tmp: Path) -> dict[str, Any]:
    out = mr.snapshot(FIXTURE, tmp / "reports", write_tasks(tmp))
    return mr.normalise(json.loads(out.read_text()))


def test_normalise_reads_schema_v1_and_drops_broken_parts() -> None:
    m = mr.normalise(json.loads(FIXTURE.read_text()))
    assert (m["schema"], m["language"], m["coverage_mode"], m["target"]) == (1, "python", "run", T)
    ids = {n["id"]: n for n in m["nodes"]}
    # the untagged file node is left off; the tagged one is a surface and stays
    assert "backend/app/core/config.py" not in ids and "backend/app/core/db.py" in ids
    s = ids[SETTINGS]
    assert (s["kind"], s["module"], s["covered"]) == ("Class", "app/core", True)
    assert s["line"] > 0 and "fail-fast-config" in s["families"]
    # edges touching the dropped file node go with it
    assert all(e["source"] in ids and e["target"] in ids for e in m["edges"]) and len(m["edges"]) == 4
    m = mr.normalise(
        {
            "nodes": [
                {"id": "a::f", "families": ["x", "x"], "blast_radius": "n/a", "covered": "yes", "line": None},
                {"name": "no id"},
                "junk",
            ],
            "edges": [{"source": "a::f", "target": "a::f"}, {"source": "a::f", "target": "missing"}],
            "tasks": [{"task_id": "t/1", "node_id": "a::f"}, {"task_id": "t/1"}, {"node_id": "a::f"}],
        }
    )
    [f] = m["nodes"]
    assert (f["name"], f["module"], f["kind"], f["families"], f["blast_radius"], f["covered"], f["line"]) == (
        "a::f",
        ".",
        "function",
        ["x"],
        0,
        None,
        0,
    )
    assert m["edges"] == [] and [t["task_id"] for t in m["tasks"]] == ["t/1"] and m["schema"] == 0


def test_coverage_counts_per_family_and_module(tmp_path: Path) -> None:
    cov = mr.coverage(fixture_map(tmp_path))
    assert cov["nodes"] == 8 and cov["unplaced_tasks"] == 1
    assert cov["total"] == {"surfaces": 7, "with_task": 2, "tasks": 2, "covered": 6, "uncovered": 1}
    fam = cov["by_family"]
    assert fam["fail-fast-config"] == {"surfaces": 1, "with_task": 1, "tasks": 1, "covered": 1, "uncovered": 0}
    assert fam["cross-field-validation"] == {"surfaces": 2, "with_task": 1, "tasks": 1, "covered": 2, "uncovered": 0}
    assert fam["config-round-trip"] == {"surfaces": 2, "with_task": 0, "tasks": 0, "covered": 1, "uncovered": 1}
    mod = cov["by_module"]
    assert mod["app/core"] == {"surfaces": 4, "with_task": 1, "tasks": 1, "covered": 4, "uncovered": 0}
    assert mod["scripts"] == {"surfaces": 1, "with_task": 0, "tasks": 0, "covered": 0, "uncovered": 1}
    assert mod["app"] == {"surfaces": 2, "with_task": 1, "tasks": 1, "covered": 2, "uncovered": 0}
    assert set(mr.by_target([fixture_map(tmp_path / "again")])) == {T}


def test_snapshot_merges_tasks_and_round_trips(tmp_path: Path) -> None:
    out = mr.snapshot(FIXTURE, tmp_path / "reports", write_tasks(tmp_path))
    assert out == tmp_path / "reports" / "map" / f"{T}.json"
    snap = json.loads(out.read_text())
    ids = {t["task_id"]: t for t in snap["tasks"]}
    assert set(ids) == {f"{T}/ff-001-settings", f"{T}/cf-003-usercreate", f"{T}/xx-001-gone"}
    assert ids[f"{T}/ff-001-settings"]["difficulty"] == "easy"
    # snapshot is one row per line and reads back unchanged
    assert len(out.read_text().splitlines()) > len(snap["nodes"]) and mr.normalise(snap) == snap
    assert mr.load_snapshots(tmp_path / "reports")[0]["target"] == T
    # no tasks dir for the target: snapshot still written
    assert json.loads(mr.snapshot(FIXTURE, tmp_path / "r2", tmp_path / "none").read_text())["tasks"] == []


def test_render_is_self_contained_and_escapes_data(tmp_path: Path) -> None:
    m = fixture_map(tmp_path)
    m["nodes"][0]["name"] = "</script><b>x"
    page = mr.render([m, {**m, "target": "other"}])
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
    (tmp_path / "work" / T).mkdir(parents=True)
    shutil.copy(FIXTURE, tmp_path / "work" / T / "map.json")
    args = ["map", "render", "--work", str(tmp_path / "work"), "--reports", str(tmp_path / "r")]
    args += ["--tasks", str(tmp_path / "tasks")]
    runner = CliRunner()
    res = runner.invoke(app, [*args, "--target", T])
    assert res.exit_code == 0 and (tmp_path / "r" / "map.html").exists(), res.output
    res = runner.invoke(app, [*args, "--target", "nope"])
    assert res.exit_code == 1 and "forge map build --target nope" in res.output

    def boom(page: Path, png: Path) -> Path:
        raise RuntimeError("chrome/chromium not found")

    monkeypatch.setattr(mr, "export_png", boom)
    res = runner.invoke(app, [*args, "--target", T, "--png", str(tmp_path / "m.png")])
    assert res.exit_code == 1 and "png export failed" in res.output
    monkeypatch.setattr(mr, "export_png", lambda page, png: png)
    res = runner.invoke(app, [*args, "--target", T, "--png", str(tmp_path / "m.png")])
    assert res.exit_code == 0 and "m.png" in res.output


def test_report_links_the_map_and_shows_coverage(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    mr.snapshot(FIXTURE, reports)
    out = build_report(reports / "index.html", tmp_path / "tasks", reports)
    page = out.read_text()
    assert 'href="map.html"' in page and "tagged surfaces" in page and "app/core" in page
    assert (reports / "map.html").exists()
    summary = json.loads((reports / "summary.json").read_text())
    assert summary["map_coverage"][T]["total"]["surfaces"] == 7
