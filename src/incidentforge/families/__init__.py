"""task families: each is families/<slug>/family.yaml + prompt.md. owner: phase 2 (1-4), phase 3 (5-8)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FAMILIES_DIR = Path(__file__).parent
# per-target prompt notes, contract and surface preferences: families/targets/<target>/
PROFILES_DIR = FAMILIES_DIR / "targets"

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


class TargetProfile(BaseModel):
    """targets/<target>/profile.yaml: which families fit a target and which surfaces each should try first."""

    model_config = ConfigDict(extra="forbid")

    families: list[str] = Field(default_factory=list)  # empty = every family
    surface_kinds: dict[str, list[str]] = Field(default_factory=dict)  # family -> kind order for this target
    prefer: dict[str, list[str]] = Field(default_factory=dict)  # family -> symbol regexes, tried in order
    skip_symbols: list[str] = Field(default_factory=list)  # symbol regexes never offered to any family

    @model_validator(mode="after")
    def _check(self) -> TargetProfile:
        known = set(list_families())
        bad = (set(self.families) | set(self.surface_kinds) | set(self.prefer)) - known
        if bad:
            raise ValueError(f"profile names unknown families: {sorted(bad)}")
        kinds = {k for ks in self.surface_kinds.values() for k in ks} - set(SURFACE_KINDS)
        if kinds:
            raise ValueError(f"profile names unknown surface kinds: {sorted(kinds)}")
        for rx in [*self.skip_symbols, *(r for rs in self.prefer.values() for r in rs)]:
            try:
                re.compile(rx)
            except re.error as e:
                raise ValueError(f"bad symbol regex {rx!r}: {e}") from e
        return self

    def allows(self, slug: str) -> bool:
        return not self.families or slug in self.families

    def adapt(self, family: Family) -> Family:
        kinds = self.surface_kinds.get(family.slug)
        return family.model_copy(update={"surface_kinds": kinds}) if kinds else family

    def skipped(self, symbol: str) -> bool:
        return any(re.search(rx, symbol) for rx in self.skip_symbols)

    def rank(self, slug: str, symbol: str) -> int:
        """index of the first preferred regex the symbol matches; unmatched symbols come after all of them."""
        rxs = self.prefer.get(slug, [])
        return next((i for i, rx in enumerate(rxs) if re.search(rx, symbol)), len(rxs))


def load_profile(target: str, root: Path = PROFILES_DIR) -> TargetProfile:
    """the target's profile, or an empty one that changes nothing."""
    path = root / target / "profile.yaml"
    return TargetProfile(**(yaml.safe_load(path.read_text()) or {})) if path.exists() else TargetProfile()


def target_notes(target: str | None, slug: str, root: Path = PROFILES_DIR) -> str:
    """targets/<target>/<slug>.md: how this family reads on that target; empty when absent."""
    if not target:
        return ""
    path = root / target / f"{slug}.md"
    return path.read_text().strip() if path.exists() else ""


def contract_path(language: str, target: str | None = None, root: Path = PROFILES_DIR) -> Path:
    """target contract (targets/<t>/contract.md), else language-specific (output-contract-go.md), else python."""
    if target and (root / target / "contract.md").exists():
        return root / target / "contract.md"
    specific = FAMILIES_DIR / f"output-contract-{language}.md"
    return specific if specific.exists() else FAMILIES_DIR / "output-contract.md"


def render_prompt(family: Family, values: dict[str, str], language: str = "python", target: str | None = None) -> str:
    """fill prompt.md placeholders, add any target notes and append the output contract."""
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
    body = _PLACEHOLDER.sub(lambda m: filled[m.group(1)], family.prompt).rstrip()
    notes = target_notes(target, family.slug)
    if notes:
        body += f"\n\n## how this failure class applies to {target}\n\n{notes}"
    contract = contract_path(language, target).read_text()
    return f"{body}\n\n{contract}"
