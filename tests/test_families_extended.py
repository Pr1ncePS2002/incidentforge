"""families 5-8 load, render and cover both languages."""

import pytest

from incidentforge.families import EXTENDED, FAMILIES_DIR, SURFACE_KINDS, list_families, load_family, render_prompt

VALUES = {"target": "T", "surface": "S", "excerpt": "E", "task_id": "x/y"}


@pytest.mark.parametrize("slug", EXTENDED)
def test_extended_family_loads_and_renders(slug: str) -> None:
    fam = load_family(slug)
    assert slug in list_families()
    assert set(fam.surface_kinds) <= set(SURFACE_KINDS)
    assert set(fam.languages) == {"python", "go"}
    assert len(fam.fault_catalogue) >= 4
    text = render_prompt(fam, VALUES)
    assert "{{" not in text
    assert "failure class" in text


def test_go_contract_names_go_test_conventions() -> None:
    text = (FAMILIES_DIR / "output-contract-go.md").read_text()
    for needle in ("TestFault", "t.Setenv", "_test.go", "repository-relative"):
        assert needle in text
