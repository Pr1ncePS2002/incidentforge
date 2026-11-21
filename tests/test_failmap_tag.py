"""map_rules: schema strictness, one exposure check per family, and tagging a built map."""

from pathlib import Path

import pytest
import yaml
from failmap_repos import py_repo
from pydantic import ValidationError

from incidentforge.failmap.build import build
from incidentforge.failmap.store import MapNode, read_annotations
from incidentforge.failmap.tag import MapRule, load_rules, tag, tags_for
from incidentforge.families import list_families
from incidentforge.models import Language

FAMILIES = [load_rules(s) for s in list_families()]


def node(kind: str, name: str = "X", language: str = "python", **attrs: object) -> MapNode:
    return MapNode(f"f.py::{name}", kind, name, "f.py", 1, 1, language, False, dict(attrs))


def exposed(n: MapNode) -> list[str]:
    return tags_for(n, FAMILIES)


def test_every_family_has_rules():
    assert len(FAMILIES) == 8 and all(f.rules for f in FAMILIES)


def test_fail_fast_config():
    assert "fail-fast-config" in exposed(node("config_read", has_default=False, validated=False))
    assert "fail-fast-config" in exposed(node("config_read", has_default=True, placeholder_default=True))
    assert "fail-fast-config" in exposed(node("env_read", has_default=False))
    assert "fail-fast-config" not in exposed(node("config_read", has_default=False, validated=True))


def test_tolerant_typed_config():
    assert "tolerant-typed-config" in exposed(node("config_read", typed=True))
    assert "tolerant-typed-config" in exposed(node("env_read", parsed=True, has_default=True))
    assert "tolerant-typed-config" not in exposed(node("config_read", typed=False))


def test_cross_field_validation():
    assert "cross-field-validation" in exposed(node("Class", surface_kinds=["validator"]))
    assert "cross-field-validation" in exposed(node("Class", surface_kinds=["settings-class"]))
    assert "cross-field-validation" not in exposed(node("Function", surface_kinds=["consumer"]))


def test_idempotent_consumer():
    assert exposed(node("handler", dedupe=False)) == ["idempotent-consumer"]
    assert exposed(node("handler", dedupe=True)) == []


def test_hot_reload_config():
    assert "hot-reload-config" in exposed(node("Class", surface_kinds=["settings-class"]))
    assert "hot-reload-config" in exposed(node("env_read", has_default=True))


def test_env_aware_naming():
    assert "env-aware-naming" in exposed(node("Function", surface_kinds=["cache-key"]))
    assert "env-aware-naming" in exposed(node("config_read", name="QUEUE_NAME", has_default=True))
    assert "env-aware-naming" not in exposed(node("config_read", name="TIMEOUT", has_default=True))


def test_resource_aware_defaults():
    assert "resource-aware-defaults" in exposed(node("config_read", pool=True, has_default=True))
    assert "resource-aware-defaults" in exposed(node("File", surface_kinds=["pool-config"]))


def test_config_round_trip():
    assert "config-round-trip" in exposed(node("Function", surface_kinds=["config-writer"]))
    assert "config-round-trip" in exposed(node("Class", surface_kinds=["settings-class"]))


def test_tests_and_other_languages_never_tagged():
    t = MapNode("t.py::x", "env_read", "x", "t.py", 1, 1, "python", True, {"has_default": False})
    assert exposed(t) == []
    assert exposed(node("env_read", language="rust", has_default=False)) == []


@pytest.mark.parametrize(
    "rule",
    [
        {"id": "x"},
        {"id": "x", "node_kinds": ["Banana"]},
        {"id": "x", "surface_kinds": ["nope"]},
        {"id": "Bad Id", "node_kinds": ["File"]},
        {"id": "x", "node_kinds": ["File"], "extra": 1},
        {"id": "x", "node_kinds": ["File"], "where": {"a": 1.5}},
        {"id": "x", "node_kinds": ["File"], "name_matches": "("},
    ],
)
def test_rule_schema_is_strict(rule: dict[str, object]):
    with pytest.raises((ValidationError, ValueError)):
        MapRule(**rule)  # type: ignore[arg-type]


def test_load_rules_errors(tmp_path: Path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "family.yaml").write_text(yaml.safe_dump({"slug": "a"}))
    with pytest.raises(ValueError, match="no map_rules"):
        load_rules("a", tmp_path)
    dup = {"slug": "a", "map_rules": [{"id": "r", "node_kinds": ["File"]}] * 2}
    (tmp_path / "a" / "family.yaml").write_text(yaml.safe_dump(dup))
    with pytest.raises(ValidationError, match="duplicate"):
        load_rules("a", tmp_path)


def test_tag_writes_annotations(tmp_path: Path):
    m = build(py_repo(tmp_path / "r"), Language.python, tmp_path / "o").map_path
    out = tag(m)
    assert out["app/crud.py::create_user#handler"] == ["idempotent-consumer"]
    assert "fail-fast-config" in out["app/core/config.py::Settings.DATABASE_URL"]
    annots = read_annotations(m)
    assert annots["app/export.py::save_config"].tags == ["config-round-trip"]
    # re-tagging with no families clears tags but keeps the rows
    assert tag(m, families=[]) == {}
    assert read_annotations(m)["app/export.py::save_config"].tags == []
