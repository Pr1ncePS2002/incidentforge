"""families 5-8 load, render and cover both languages."""

from pathlib import Path

import pytest

from incidentforge.families import EXTENDED, FAMILIES_DIR, SURFACE_KINDS, list_families, load_family, render_prompt
from incidentforge.models import Language, Target, TaskSpec
from incidentforge.package import feature_test_paths

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


def test_go_contract_example_path_survives_packaging() -> None:
    # the contract's example path must reach the package dir unchanged, and a bare name must not
    text = (FAMILIES_DIR / "output-contract-go.md").read_text()
    assert "at least one directory" in text
    assert _packaged("internal/config/forge_feature_test.go") == "internal/config/forge_feature_test.go"
    assert _packaged("forge_feature_test.go") == "tests/forge_feature_test.go"


def _packaged(name: str) -> str:
    target = Target(name="t", repo_url="u", commit="c", language=Language.go, env_template=Path("."), test_command="x")
    spec = TaskSpec(
        task_id="t/x",
        family="f",
        target=target,
        title="t",
        instruction="i",
        solution_patch="",
        feature_tests={name: ""},
    )
    return feature_test_paths(spec)[0]
