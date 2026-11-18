"""repo invariants every phase relies on: targets, pins, cli wiring."""

import re
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from incidentforge.backends.gemini import GeminiBackend, load_env
from incidentforge.cli import app
from incidentforge.families import list_families
from incidentforge.models import Language, TaskSpec
from incidentforge.targets import TARGETS_DIR, load_target

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


@pytest.mark.parametrize("name", sorted(p.stem for p in TARGETS_DIR.glob("*.yaml")))
def test_every_target_is_pinned_and_has_an_env(name):
    t = load_target(name)
    assert re.fullmatch(r"[0-9a-f]{40}", t.commit), "targets must pin a full commit sha"
    assert (t.env_template / "Dockerfile").is_file()
    assert (t.env_template / "run_tests.sh").is_file()
    assert t.commit in (t.env_template / "Dockerfile").read_text(), "dockerfile must build the pinned commit"
    assert t.language in Language


def test_all_dependencies_are_exact_pins():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    deps = data["project"]["dependencies"] + [d for g in data["dependency-groups"].values() for d in g]
    loose = [d for d in deps if "==" not in d]
    assert not loose, f"unpinned dependencies: {loose}"


def test_task_spec_requires_core_fields():
    with pytest.raises(ValueError):
        TaskSpec.model_validate({"task_id": "x"})


def test_families_listing_only_counts_dirs_with_family_yaml():
    assert all("/" not in f for f in list_families())


def test_cli_version_and_budget_run(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_LEDGER", str(tmp_path / "ledger.jsonl"))
    assert runner.invoke(app, ["version"]).exit_code == 0
    r = runner.invoke(app, ["budget", "--runs-left", "4", "--per-run-usd", "1"])
    assert r.exit_code == 0 and "$0.00 / $70.00" in r.output


def test_load_env_ignores_comments_and_quotes(tmp_path):
    p = tmp_path / ".env"
    p.write_text('# c\nGEMINI_API_KEY="abc"\nBROKEN\nGEMINI_API_KEY2=def\n')
    assert load_env(p) == {"GEMINI_API_KEY": "abc", "GEMINI_API_KEY2": "def"}
    assert load_env(tmp_path / "missing") == {}


def test_backend_from_env_reads_both_keys(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY2", raising=False)
    p = tmp_path / ".env"
    p.write_text("GEMINI_API_KEY=free\nGEMINI_API_KEY2=paid\n")
    b = GeminiBackend.from_env(p)
    assert (b.free_key, b.paid_key) == ("free", "paid")
