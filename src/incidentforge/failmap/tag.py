"""evaluate the declarative map_rules in each families/<slug>/family.yaml against map nodes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

from incidentforge.failmap.store import (
    OVERLAY_KINDS,
    UNIT_KINDS,
    Annotation,
    MapNode,
    read_annotations,
    read_meta,
    read_nodes,
    write_annotations,
)
from incidentforge.families import FAMILIES_DIR, SURFACE_KINDS, list_families

NODE_KINDS = (*UNIT_KINDS, *OVERLAY_KINDS)


class MapRule(BaseModel):
    """one rule: a node matches when every given condition holds."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: StrictStr = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    node_kinds: list[StrictStr] = Field(default_factory=list)
    surface_kinds: list[StrictStr] = Field(default_factory=list)
    where: dict[StrictStr, StrictBool | StrictInt | StrictStr] = Field(default_factory=dict)
    name_matches: StrictStr | None = None

    @model_validator(mode="after")
    def _check(self) -> MapRule:
        if not self.node_kinds and not self.surface_kinds:
            raise ValueError(f"rule {self.id}: needs node_kinds or surface_kinds")
        bad = set(self.node_kinds) - set(NODE_KINDS)
        if bad:
            raise ValueError(f"rule {self.id}: unknown node kinds {sorted(bad)}")
        bad = set(self.surface_kinds) - set(SURFACE_KINDS)
        if bad:
            raise ValueError(f"rule {self.id}: unknown surface kinds {sorted(bad)}")
        if self.name_matches is not None:
            try:
                re.compile(self.name_matches)
            except re.error as e:
                raise ValueError(f"rule {self.id}: bad name_matches: {e}") from e
        return self

    def matches(self, node: MapNode) -> bool:
        if node.is_test:
            return False
        if self.node_kinds and node.kind not in self.node_kinds:
            return False
        if self.surface_kinds and not set(self.surface_kinds) & set(node.attrs.get("surface_kinds", [])):
            return False
        if any(node.attrs.get(k) != v for k, v in self.where.items()):
            return False
        return self.name_matches is None or re.search(self.name_matches, node.name) is not None


class FamilyRules(BaseModel):
    model_config = ConfigDict(frozen=True)

    slug: str
    languages: list[str]
    rules: list[MapRule] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> FamilyRules:
        ids = [r.id for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate map rule ids in {self.slug}")
        return self


def load_rules(slug: str, root: Path = FAMILIES_DIR) -> FamilyRules:
    data: dict[str, Any] = yaml.safe_load((root / slug / "family.yaml").read_text())
    if "map_rules" not in data:
        raise ValueError(f"{slug}/family.yaml has no map_rules")
    return FamilyRules(
        slug=slug,
        languages=data.get("languages", ["python", "go"]),
        rules=[MapRule(**r) for r in data["map_rules"]],
    )


def tags_for(node: MapNode, families: list[FamilyRules]) -> list[str]:
    return sorted(f.slug for f in families if node.language in f.languages and any(r.matches(node) for r in f.rules))


def tag(map_path: Path, families: list[FamilyRules] | None = None) -> dict[str, list[str]]:
    """write family tags into fm_annot; returns node id -> tags for tagged nodes only."""
    fams = families if families is not None else [load_rules(s) for s in list_families()]
    language = read_meta(map_path)["language"]
    nodes = read_nodes(map_path)
    annots = read_annotations(map_path)
    out: dict[str, list[str]] = {}
    for nid, node in nodes.items():
        node.language = node.language or language
        tags = tags_for(node, fams)
        if tags:
            out[nid] = tags
        if tags or nid in annots:
            a = annots.get(nid, Annotation(nid))
            a.tags = tags
            annots[nid] = a
    write_annotations(map_path, annots.values())
    return out
