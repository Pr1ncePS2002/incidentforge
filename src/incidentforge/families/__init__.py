"""task families: each is families/<slug>/family.yaml + prompt.md. owner: phase 2 (1-4), phase 3 (5-8)."""

from pathlib import Path

FAMILIES_DIR = Path(__file__).parent

CORE = ("fail-fast-config", "tolerant-typed-config", "cross-field-validation", "idempotent-consumer")
EXTENDED = ("hot-reload-config", "env-aware-naming", "resource-aware-defaults", "config-round-trip")


def list_families() -> list[str]:
    return sorted(p.name for p in FAMILIES_DIR.iterdir() if (p / "family.yaml").exists())
