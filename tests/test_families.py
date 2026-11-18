"""family.yaml schema, loader and prompt rendering."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from incidentforge.families import (
    CORE,
    PLACEHOLDERS,
    SURFACE_KINDS,
    Family,
    list_families,
    load_family,
    render_prompt,
)

GOOD = {
    "slug": "demo-family",
    "title": "demo",
    "intent": "demo intent",
    "surface_kinds": ["settings-class"],
    "fault_catalogue": [{"id": "a-one", "description": "x"}, {"id": "b", "description": "y"}],
    "acceptance": ["works"],
    "difficulty_levers": ["more"],
    "examples": ["one"],
}


def _write(root: Path, data: dict[str, object], prompt: str = "s={{surface}} t={{task_id}}") -> None:
    d = root / str(data["slug"])
    d.mkdir(parents=True)
    (d / "family.yaml").write_text(yaml.safe_dump(data))
    (d / "prompt.md").write_text(prompt)


@pytest.mark.parametrize("slug", CORE)
def test_core_families_load(slug: str) -> None:
    fam = load_family(slug)
    assert fam.slug == slug
    assert set(fam.surface_kinds) <= set(SURFACE_KINDS)
    assert {p for p in PLACEHOLDERS} >= {"surface", "excerpt"}
    text = render_prompt(fam, {"target": "T", "surface": "S", "excerpt": "E", "task_id": "x/y"})
    assert "{{" not in text
    assert "output contract" in text


def test_list_families_includes_core() -> None:
    assert set(CORE) <= set(list_families())


def test_load_custom_root(tmp_path: Path) -> None:
    _write(tmp_path, GOOD)
    fam = load_family("demo-family", root=tmp_path)
    out = render_prompt(fam, {"surface": "f.py::S", "task_id": "t/1"})
    assert out.startswith("s=f.py::S t=t/1")
    assert fam.weight == 1.0


def test_slug_must_match_dir(tmp_path: Path) -> None:
    _write(tmp_path, GOOD)
    (tmp_path / "demo-family").rename(tmp_path / "other")
    with pytest.raises(ValueError, match="does not match"):
        load_family("other", root=tmp_path)


def test_unknown_placeholder_rejected(tmp_path: Path) -> None:
    _write(tmp_path, GOOD, prompt="{{nope}}")
    with pytest.raises(ValueError, match="unknown placeholders"):
        load_family("demo-family", root=tmp_path)


def test_missing_value_raises(tmp_path: Path) -> None:
    _write(tmp_path, GOOD)
    fam = load_family("demo-family", root=tmp_path)
    with pytest.raises(KeyError):
        render_prompt(fam, {"surface": "s"})


@pytest.mark.parametrize(
    "patch",
    [
        {"slug": "Bad Slug"},
        {"fault_catalogue": [{"id": "x", "description": "a"}]},
        {"fault_catalogue": [{"id": "x", "description": "a"}, {"id": "x", "description": "b"}]},
        {"fault_catalogue": [{"id": "Not_Kebab", "description": "a"}, {"id": "y", "description": "b"}]},
        {"examples": []},
        {"weight": 0},
    ],
)
def test_schema_rejects(patch: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Family(**{**GOOD, **patch})
