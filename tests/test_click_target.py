"""library surfaces, click map rules and the per-target profile, contract and notes."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from incidentforge import generate as gen_mod
from incidentforge.failmap.overlay import NOISE_DIR
from incidentforge.failmap.store import MapNode
from incidentforge.failmap.tag import load_rules, tags_for
from incidentforge.families import (
    TargetProfile,
    contract_path,
    list_families,
    load_family,
    load_profile,
    render_prompt,
    target_notes,
)
from incidentforge.generate import plan_pairs
from incidentforge.models import Language, Surface, Target
from incidentforge.surfaces.python import find_python_surfaces, scan_file
from incidentforge.targets import load_target

TYPES = """
class ParamType:
    def convert(self, value, param, ctx):
        return value

    def fail(self, message, param=None, ctx=None):
        raise ValueError(message)


class BoolType(ParamType):
    name = "boolean"
    states = {"1": True, "0": False}

    def convert(self, value, param, ctx):
        if value not in self.states:
            self.fail(f"{value!r} is not a valid boolean", param, ctx)
        return self.states[value]


class Range(ParamType):
    def __init__(self, min=None, max=None):
        self.min = min
        self.max = max

    def convert(self, value, param, ctx):
        if self.min is not None and value < self.min:
            raise ValueError("too small")
        return value


class Flag:
    def __init__(self, count=False, multiple=False):
        self.count = count
        if count and multiple:
            raise TypeError("'count' is not valid with 'multiple'.")

    def _validate(self):
        if self.count:
            raise TypeError("bad")

    def consume_value(self, ctx, opts):
        return opts

    def process_value(self, ctx, value):
        return value

    def handle_event(self, event):
        return event


class Formatter:
    def __init__(self, width=None, max_width=None):
        import shutil

        if width is None:
            width = min(shutil.get_terminal_size().columns, max_width or 80)
        self.width = width

    def write_text(self, text):
        self.buffer = text

    def render(self):
        self.write_text("usage")


def save(path, text):
    path.write_text(text)


def plain(value):
    return value
"""


@pytest.fixture
def lib(tmp_path: Path) -> Path:
    src = tmp_path / "src" / "lib"
    src.mkdir(parents=True)
    (src / "types.py").write_text(TYPES)
    for noise in ("docs", "examples"):
        (tmp_path / noise).mkdir()
        (tmp_path / noise / "demo.py").write_text("import os\nos.getenv('A')\n")
    return tmp_path


def _kinds(lib: Path) -> set[tuple[str, str]]:
    return {(s.kind, s.symbol) for s in find_python_surfaces(lib)}


def test_converters_and_constructor_checks_are_validators(lib: Path) -> None:
    got = {sym for kind, sym in _kinds(lib) if kind == "validator"}
    # the base convert only returns, so it rejects nothing and is not a surface
    assert got == {"BoolType.convert", "Range.convert", "Flag.__init__", "Flag._validate"}


def test_converter_excerpt_carries_class_and_init(lib: Path) -> None:
    (s,) = [s for s in find_python_surfaces(lib) if s.symbol == "Range.convert"]
    assert s.excerpt.startswith("class Range(ParamType):")
    assert "self.max = max" in s.excerpt and "too small" in s.excerpt


def test_long_constructor_keeps_signature_and_checks(tmp_path: Path) -> None:
    body = "\n".join(f"        self.a{i} = {i}" for i in range(120))
    src = (
        "class Opt:\n    def __init__(self, count=False, multiple=False):\n"
        f"{body}\n        if count and multiple:\n            raise TypeError('count with multiple')\n"
        "    def convert(self, value):\n        if not value:\n            self.fail('x')\n        return value\n"
    )
    f = tmp_path / "opt.py"
    f.write_text(src)
    got = {s.symbol: s.excerpt for s in scan_file(f, "opt.py") if s.kind == "validator"}
    assert "self.a50" not in got["Opt.__init__"] and "count with multiple" in got["Opt.__init__"]
    # a long __init__ shrinks to its checks inside the converter excerpt too
    assert "self.a50" not in got["Opt.convert"] and "def __init__" in got["Opt.convert"]


def test_resource_probe_is_pool_config(lib: Path) -> None:
    assert ("pool-config", "Formatter.__init__") in _kinds(lib)


def test_name_regex_consumers_need_a_message_parameter(lib: Path) -> None:
    consumers = {sym for kind, sym in _kinds(lib) if kind == "consumer"}
    assert consumers == {"Flag.handle_event"}


def test_write_text_counts_only_on_a_path(lib: Path) -> None:
    writers = {sym for kind, sym in _kinds(lib) if kind == "config-writer"}
    assert writers == {"save"}


def test_path_constructor_write_text_is_a_writer(tmp_path: Path) -> None:
    f = tmp_path / "w.py"
    f.write_text("from pathlib import Path\n\ndef dump(x):\n    Path('c.toml').write_text(x)\n")
    assert [s.kind for s in scan_file(f, "w.py")] == ["config-writer"]


def test_docs_and_examples_are_skipped(lib: Path) -> None:
    assert not any(s.file.startswith(("docs/", "examples/")) for s in find_python_surfaces(lib))
    assert NOISE_DIR.search("examples/x.py") and NOISE_DIR.search("docs/conf.py")
    assert not NOISE_DIR.search("src/click/docs.py")


FAMILIES = [load_rules(s) for s in list_families()]


def node(kind: str, name: str = "X", **attrs: object) -> MapNode:
    return MapNode(f"f.py::{name}", kind, name, "f.py", 1, 1, "python", False, dict(attrs))


def test_converter_nodes_are_tolerant_typed_and_cross_field() -> None:
    tags = tags_for(node("Function", "convert", surface_kinds=["validator"]), FAMILIES)
    assert {"tolerant-typed-config", "cross-field-validation"} <= set(tags)
    init = tags_for(node("Function", "__init__", surface_kinds=["validator"]), FAMILIES)
    assert "tolerant-typed-config" not in init and "cross-field-validation" in init


def test_runtime_built_env_name_is_env_aware_naming() -> None:
    assert "env-aware-naming" in tags_for(node("env_read", "<dynamic>", key="<dynamic>", has_default=False), FAMILIES)
    assert "env-aware-naming" not in tags_for(node("env_read", "HOME", key="HOME", has_default=True), FAMILIES)


def test_click_target_loads() -> None:
    t = load_target("click")
    assert t.source_root == "." and t.test_command == "run_tests -q" and len(t.commit) == 40
    dockerfile = (t.env_template / "Dockerfile").read_text()
    assert "ARG REPO_URL=" in dockerfile and f"ARG REPO_COMMIT={t.commit}" in dockerfile


def test_click_profile() -> None:
    p = load_profile("click")
    assert len(p.families) >= 5 and not p.allows("idempotent-consumer")
    assert p.adapt(load_family("tolerant-typed-config")).surface_kinds[0] == "validator"
    assert p.adapt(load_family("fail-fast-config")).surface_kinds == ["env-read", "validator"]
    assert p.skipped("ProgressBar.render_progress") and not p.skipped("Option._validate")
    assert p.rank("tolerant-typed-config", "BoolParamType.convert") < p.rank("tolerant-typed-config", "Path.convert")
    assert p.rank("tolerant-typed-config", "Path.convert") < p.rank("tolerant-typed-config", "Option.__init__")
    assert p.rank("fail-fast-config", "BoolParamType.convert") == len(p.prefer["fail-fast-config"])
    for slug in p.families:
        assert target_notes("click", slug), slug


def test_missing_profile_changes_nothing(tmp_path: Path) -> None:
    p = load_profile("nope", root=tmp_path)
    fam = load_family("fail-fast-config")
    assert p.allows("anything") and p.adapt(fam) is fam and not p.skipped("X") and p.rank("f", "X") == 0
    (tmp_path / "empty").mkdir()
    (tmp_path / "empty" / "profile.yaml").write_text("")
    assert load_profile("empty", root=tmp_path) == TargetProfile()
    assert target_notes(None, "fail-fast-config") == "" and target_notes("nope", "x", root=tmp_path) == ""


@pytest.mark.parametrize(
    "bad",
    [
        {"families": ["no-such-family"]},
        {"surface_kinds": {"fail-fast-config": ["widget"]}},
        {"prefer": {"fail-fast-config": ["("]}},
        {"skip_symbols": ["["]},
        {"unknown": 1},
    ],
)
def test_profile_rejects(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TargetProfile(**bad)


def test_contract_and_notes_for_click() -> None:
    assert contract_path("python", "click").parent.name == "click"
    assert contract_path("python", "fastapi-template").name == "output-contract.md"
    fam = load_family("cross-field-validation")
    text = render_prompt(fam, {"target": "T", "surface": "S", "excerpt": "E", "task_id": "click/cf-1"}, target="click")
    assert "## how this failure class applies to click" in text
    assert "CliRunner" in text and "filterwarnings = error" in text
    assert "from app.core import config" not in text and "database is up" not in text
    plain = render_prompt(fam, {"target": "T", "surface": "S", "excerpt": "E", "task_id": "x/1"})
    assert "applies to" not in plain and "from app.core import config" in plain


def test_plan_pairs_tries_preferred_symbols_first() -> None:
    fam = load_family("tolerant-typed-config").model_copy(update={"surface_kinds": ["validator"]})
    a = Surface(file="core.py", symbol="Option.__init__", kind="validator")
    b = Surface(file="types.py", symbol="Bool.convert", kind="validator")
    prof = TargetProfile(prefer={"tolerant-typed-config": [r"\.convert$"]})
    assert [s.symbol for _, s in plan_pairs([fam], [a, b], set(), prof)] == ["Bool.convert", "Option.__init__"]
    assert [s.symbol for _, s in plan_pairs([fam], [a, b], set())] == ["Option.__init__", "Bool.convert"]


def test_generate_applies_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    logs: list[str] = []
    seen: list[list[str]] = []
    surfaces = [Surface(file="a.py", symbol="Skip.me", kind="env-read")]
    monkeypatch.setattr(gen_mod, "checkout", lambda _t, _w: tmp_path)
    monkeypatch.setattr(gen_mod, "find_target_surfaces", lambda _r, _t: surfaces)
    monkeypatch.setattr(
        gen_mod, "load_profile", lambda _n: TargetProfile(families=["fail-fast-config"], skip_symbols=["^Skip"])
    )

    def fake_plan(fams: list[Any], surf: list[Surface], used: Any, profile: Any) -> Any:
        seen.append([f.slug for f in fams])
        assert surf == []
        return iter(())

    monkeypatch.setattr(gen_mod, "plan_pairs", fake_plan)
    target = Target.model_construct(name="lib", language=Language.python, commit="0" * 40)
    out = gen_mod.generate(
        target,
        ["fail-fast-config", "hot-reload-config"],
        1,
        backend=None,  # type: ignore[arg-type]
        tasks_root=tmp_path / "tasks",
        work_root=tmp_path / "work",
        writer=lambda _s, _r: tmp_path,
        validator=lambda _d: None,  # type: ignore[arg-type,return-value]
        log=logs.append,
    )
    assert out == [] and seen == [["fail-fast-config"]]
    assert any("leaves out ['hot-reload-config']" in m for m in logs)
