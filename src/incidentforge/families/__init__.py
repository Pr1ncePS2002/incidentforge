"""task families: each is families/<slug>/family.yaml + prompt.md. owner: phase 2 (1-4), phase 3 (5-8)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

FAMILIES_DIR = Path(__file__).parent

CORE = ("fail-fast-config", "tolerant-typed-config", "cross-field-validation", "idempotent-consumer")
EXTENDED = ("hot-reload-config", "env-aware-naming", "resource-aware-defaults", "config-round-trip")

SURFACE_KINDS = (
    "settings-class",
    "env-read",
    "validator",
    "consumer",
    "cache-key",
    "config-writer",
    "pool-config",
)
PLACEHOLDERS = (
    "target",
    "surface",
    "excerpt",
    "faults",
    "acceptance",
    "gold_example",
    "previous_failure",
    "task_id",
    "existing_tasks",
)
_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


class Fault(BaseModel):
    id: str
    description: str

    @field_validator("id")
    @classmethod
    def _kebab(cls, v: str) -> str:
        if not _SLUG.match(v):
            raise ValueError(f"fault id {v!r} must be kebab-case")
        return v


class Family(BaseModel):
    """parsed family.yaml; schema documented in families/README.md."""

    slug: str
    title: str
    intent: str
    surface_kinds: list[str] = Field(min_length=1)
    fault_catalogue: list[Fault] = Field(min_length=2)
    acceptance: list[str] = Field(min_length=1)
    difficulty_levers: list[str] = Field(default_factory=list)
    examples: list[str] = Field(min_length=1, max_length=2)
    weight: float = Field(default=1.0, gt=0)
    languages: list[str] = Field(default_factory=lambda: ["python", "go"])
    prompt: str = ""  # prompt.md contents, filled by load_family

    @model_validator(mode="after")
    def _check(self) -> Family:
        if not _SLUG.match(self.slug):
            raise ValueError(f"slug {self.slug!r} must be kebab-case")
        ids = [f.id for f in self.fault_catalogue]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate fault ids in {self.slug}")
        return self


def list_families() -> list[str]:
    return sorted(p.name for p in FAMILIES_DIR.iterdir() if (p / "family.yaml").exists())


def load_family(slug: str, root: Path = FAMILIES_DIR) -> Family:
    d = root / slug
    fam = Family(**yaml.safe_load((d / "family.yaml").read_text()))
    if fam.slug != slug:
        raise ValueError(f"family.yaml slug {fam.slug!r} does not match directory {slug!r}")
    prompt = (d / "prompt.md").read_text()
    unknown = set(_PLACEHOLDER.findall(prompt)) - set(PLACEHOLDERS)
    if unknown:
        raise ValueError(f"{slug}/prompt.md has unknown placeholders: {sorted(unknown)}")
    return fam.model_copy(update={"prompt": prompt})


def bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items)


def render_prompt(family: Family, values: dict[str, str]) -> str:
    """fill prompt.md placeholders and append the shared output contract."""
    filled = {
        "faults": bullets([f"{f.id}: {f.description}" for f in family.fault_catalogue]),
        "acceptance": bullets(family.acceptance),
        "gold_example": "none",
        "previous_failure": "none",
        "existing_tasks": "none",
        **values,
    }
    missing = set(_PLACEHOLDER.findall(family.prompt)) - set(filled)
    if missing:
        raise KeyError(f"no value for placeholders: {sorted(missing)}")
    body = _PLACEHOLDER.sub(lambda m: filled[m.group(1)], family.prompt)
    contract = (FAMILIES_DIR / "output-contract.md").read_text()
    return f"{body.rstrip()}\n\n{contract}"
