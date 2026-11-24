"""from-postmortem with a stub backend, a git fixture repo and fake gates; no model or network calls."""

import json
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from incidentforge import cli
from incidentforge import postmortem as pm_mod
from incidentforge.families import list_families, load_family
from incidentforge.models import GateResult, Language, Surface, Target, ValidationReport
from incidentforge.package import write_task
from incidentforge.postmortem import (
    Classification,
    NoFamilyFits,
    Postmortem,
    PostmortemError,
    classification_schema,
    classify,
    copied_run,
    fetch_url,
    from_postmortem,
    html_to_text,
    load_postmortem,
    rank_for_incident,
    sentences,
    stamp_metadata,
    used_surfaces,
)

URL = "https://example.org/blog/incident-2025"
REPORT = (
    "On the day of the incident a deploy shipped a credentials rotation to the storage gateway. "
    "The new token was written for the production cluster but the gateway kept reading the old variable name, "
    "so every write was rejected with an authentication error for over an hour while engineers rolled back. "
) * 3
HTML = (
    "<html><head><title>t</title><style>x{}</style></head><body><nav>menu</nav>"
    f"<p>{REPORT}</p><script>evil()</script></body></html>"
)
CONFIG = """from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SECRET_KEY: str = "changethis"
    SMTP_HOST: str | None = None
"""
NEW_CONFIG = CONFIG.replace("    SMTP_HOST", "    STRICT: bool = True\n    SMTP_HOST")
TESTS = {"test_forge_x.py": "def test_fault_missing():\n    assert True\n"}
TRIGGER = "A rotated storage credential was published under one env variable name while the gateway still read another."


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def target(tmp_path: Path) -> Target:
    repo = tmp_path / "upstream"
    (repo / "backend" / "app" / "core").mkdir(parents=True)
    (repo / "backend" / "app" / "core" / "config.py").write_text(CONFIG)
    _git(repo.parent, "init", "-q", str(repo))
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    env = tmp_path / "env"
    env.mkdir()
    (env / "Dockerfile").write_text("FROM scratch\nARG REPO_URL=x\nARG REPO_COMMIT=y\n")
    return Target(
        name="fixture",
        repo_url=str(repo),
        commit=_git(repo, "rev-parse", "HEAD").strip(),
        licence="MIT",
        language=Language.python,
        env_template=env,
        test_command="run_tests -q tests/",
        source_root="backend",
    )


def good_patch(target: Target) -> str:
    repo = Path(target.repo_url)
    (repo / "backend/app/core/config.py").write_text(NEW_CONFIG)
    diff = _git(repo, "diff")
    _git(repo, "checkout", "--", ".")
    return diff


def cls_answer(family: str = "fail-fast-config", **kw: Any) -> dict[str, Any]:
    return {"family": family, "trigger": TRIGGER, "keywords": ["secret"], "reason": "a startup check catches it", **kw}


def task_answer(patch: str) -> dict[str, Any]:
    return {
        "title": "refuse to start on a stale secret",
        "instruction": "make settings refuse a placeholder secret at startup",
        "solution_patch": patch,
        "feature_tests": TESTS,
        "fault_cases": ["placeholder: secret left as changethis"],
        "difficulty": "easy",
    }


class StubBackend:
    name = "stub"

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []
        self.schemas: list[dict[str, Any]] = []

    def generate_json(
        self, prompt: str, schema: dict[str, Any], max_output_tokens: int = 8192, tag: str = ""
    ) -> dict[str, Any]:
        self.prompts.append(prompt)
        self.schemas.append(schema)
        return dict(self.answers.pop(0))


class FakeValidator:
    def __init__(self, *verdicts: bool) -> None:
        self.verdicts = list(verdicts)

    def __call__(self, task_dir: Path) -> ValidationReport:
        ok = self.verdicts.pop(0)
        gate = GateResult(gate="fail_on_base", passed=ok, detail="" if ok else "tests passed on base")
        return ValidationReport(task_id=task_dir.name, accepted=ok, gates=[gate])


def fake_fetch(body: str, ctype: str = "text/html; charset=utf-8") -> Any:
    def fetch(url: str) -> tuple[str, str]:
        return body, ctype

    return fetch


def _pm(tmp_path: Path, text: str = REPORT) -> Postmortem:
    return Postmortem(text, URL, tmp_path / "s.txt")


def _families() -> list[Any]:
    return [load_family(s) for s in list_families()]


# loading


def test_html_to_text_drops_chrome() -> None:
    text = html_to_text(HTML)
    assert "credentials rotation" in text
    assert "evil" not in text and "menu" not in text and "x{}" not in text


def test_load_url_writes_snapshot(tmp_path: Path) -> None:
    pm = load_postmortem(URL, tmp_path, fetch=fake_fetch(HTML))
    assert pm.source_url == URL and pm.snapshot == tmp_path / "postmortems" / "example-org-blog-incident-2025.txt"
    assert pm.snapshot.read_text().startswith("On the day")


def test_load_plain_text_url_and_source_url_override(tmp_path: Path) -> None:
    pm = load_postmortem(URL, tmp_path, source_url="https://mirror.example/x", fetch=fake_fetch(REPORT, "text/plain"))
    assert pm.source_url == "https://mirror.example/x" and pm.text == REPORT.strip()


def test_load_local_file_needs_source_url(tmp_path: Path) -> None:
    f = tmp_path / "report.html"
    f.write_text(HTML)
    with pytest.raises(PostmortemError, match="--source-url"):
        load_postmortem(str(f), tmp_path)
    pm = load_postmortem(str(f), tmp_path, source_url=URL)
    assert "evil" not in pm.text
    txt = tmp_path / "report.txt"
    txt.write_text(REPORT)
    assert load_postmortem(str(txt), tmp_path, source_url=URL).text == REPORT.strip()


@pytest.mark.parametrize(
    ("source", "source_url", "match"),
    [
        ("missing.txt", URL, "no such file"),
        ("https://", None, "not a usable url"),
        (URL, "ftp://x/y", "public http"),
    ],
)
def test_load_refusals(tmp_path: Path, source: str, source_url: str | None, match: str) -> None:
    with pytest.raises(PostmortemError, match=match):
        load_postmortem(source, tmp_path, source_url, fetch=fake_fetch(HTML))


def test_load_too_short(tmp_path: Path) -> None:
    with pytest.raises(PostmortemError, match="too short"):
        load_postmortem(URL, tmp_path, fetch=fake_fetch("<p>tiny</p>"))


class _Resp:
    def __init__(self, body: bytes, ctype: str) -> None:
        self.body = body
        from email.message import Message

        self.headers = Message()
        self.headers["Content-Type"] = ctype

    def read(self, n: int) -> bytes:
        return self.body[:n]

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *a: object) -> None:
        return None


def test_fetch_url(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []

    def urlopen(req: Any, timeout: float) -> _Resp:
        seen.append(req)
        return _Resp("café".encode("latin-1"), "text/html; charset=latin-1")

    monkeypatch.setattr(pm_mod.urllib.request, "urlopen", urlopen)
    assert fetch_url(URL) == ("café", "text/html; charset=latin-1")
    assert seen[0].get_header("User-agent") == pm_mod.USER_AGENT
    monkeypatch.setattr(pm_mod, "MAX_FETCH_BYTES", 2)
    with pytest.raises(PostmortemError, match="larger"):
        fetch_url(URL)


# classification


def test_classify_accepts_and_prompt_carries_catalogue(tmp_path: Path) -> None:
    backend = StubBackend(cls_answer())
    got = classify(_pm(tmp_path), backend, _families())
    assert got.family == "fail-fast-config" and got.keywords == ["secret"]
    prompt = backend.prompts[0]
    assert all(f"`{s}`" in prompt for s in list_families()) and "<report>" in prompt and URL in prompt
    assert backend.schemas[0]["properties"]["family"]["enum"][-1] == "none"


def test_classify_none_is_a_refusal(tmp_path: Path) -> None:
    with pytest.raises(NoFamilyFits, match="a network partition"):
        classify(_pm(tmp_path), StubBackend(cls_answer("none", reason="a network partition")), _families())


def test_classify_family_outside_language_is_a_refusal(tmp_path: Path) -> None:
    fams = [f for f in _families() if f.slug != "fail-fast-config"]
    with pytest.raises(NoFamilyFits, match="language"):
        classify(_pm(tmp_path), StubBackend(cls_answer()), fams)


@pytest.mark.parametrize(
    "bad",
    [
        cls_answer("made-up-family"),
        cls_answer(trigger="short"),
        cls_answer(trigger="One. Two sentences here. Three is too many for a trigger."),
        cls_answer(keywords=["Two Words"]),
        cls_answer(extra="field"),
        {**cls_answer(), "keywords": "secret"},
        {k: v for k, v in cls_answer().items() if k != "reason"},
    ],
)
def test_classify_rejects_malformed(tmp_path: Path, bad: dict[str, Any]) -> None:
    with pytest.raises(PostmortemError, match="classifier answer rejected"):
        classify(_pm(tmp_path), StubBackend(bad, bad), _families())


def test_classify_retries_once_with_the_reason(tmp_path: Path) -> None:
    backend = StubBackend(cls_answer(trigger="short"), cls_answer())
    assert classify(_pm(tmp_path), backend, _families()).family == "fail-fast-config"
    assert "your previous answer was rejected: classifier answer rejected" in backend.prompts[1]


def test_classify_rejects_quoted_trigger(tmp_path: Path) -> None:
    quoted = "The new token was written for the production cluster but the gateway kept reading the old variable name."
    with pytest.raises(PostmortemError, match="quotes the report"):
        classify(_pm(tmp_path), StubBackend(cls_answer(trigger=quoted), cls_answer(trigger=quoted)), _families())


def test_text_helpers() -> None:
    assert sentences("A value e.g. v1.2 was wrong. Then it broke.") == [
        "A value e.g. v1.2 was wrong.",
        "Then it broke.",
    ]
    assert copied_run("one two three", "one two three", n=3) == "one two three"
    assert copied_run("one two four", "one two three", n=3) is None
    assert Classification.model_validate(cls_answer(trigger="  spaced   out  trigger text here  ok ")).trigger == (
        "spaced out trigger text here ok"
    )
    assert classification_schema()["additionalProperties"] is False


# surface choice


def test_used_surfaces_reads_ids_and_map_nodes(tmp_path: Path) -> None:
    base = tmp_path / "fixture"
    (base / "ff-001-settings").mkdir(parents=True)
    (base / "ff-002-other").mkdir()
    (base / "ff-002-other" / "task.toml").write_text('[metadata]\nfamily = "fail-fast-config"\nmap_node = "n1"\n')
    (base / "tt-001-thing").mkdir()
    assert used_surfaces(tmp_path, "fixture", "fail-fast-config") == {"settings", "other", "n1"}
    assert used_surfaces(tmp_path, "missing", "fail-fast-config") == set()


def test_rank_prefers_tag_then_keywords_then_kind() -> None:
    fam = load_family("fail-fast-config")
    s = [
        Surface(file="a.py", symbol="Pool", kind="pool-config", node_id="p"),
        Surface(file="a.py", symbol="read_secret", kind="env-read", excerpt="SECRET", node_id="e"),
        Surface(file="a.py", symbol="Settings", kind="settings-class", node_id="s"),
        Surface(file="a.py", symbol="Settings", kind="settings-class", node_id="s"),
        Surface(file="a.py", symbol="handler", kind="consumer"),
        Surface(file="a.py", symbol="Used", kind="settings-class"),
        Surface(file="a.py", symbol="Taken", kind="settings-class", node_id="t"),
    ]
    tags = {"p": ["fail-fast-config"], "e": [], "s": ["fail-fast-config"]}
    got = rank_for_incident(s, fam, tags, ["secret"], {"used", "t"})
    assert [x.symbol for x in got] == ["Settings", "Pool", "read_secret"]
    got = rank_for_incident(s, fam, {}, ["secret"], set())
    assert got[0].symbol == "read_secret"


# end to end with stubs


def run(target: Target, tmp_path: Path, backend: StubBackend, validator: FakeValidator, **kw: Any) -> Any:
    return from_postmortem(
        URL,
        target,
        backend,
        tasks_root=tmp_path / "tasks",
        work_root=tmp_path / "work",
        writer=write_task,
        validator=validator,
        fetch=fake_fetch(HTML),
        log=lambda _m: None,
        **kw,
    )


def test_end_to_end_with_real_map(target: Target, tmp_path: Path) -> None:
    patch = good_patch(target)
    backend = StubBackend(cls_answer(), task_answer(patch))
    res = run(target, tmp_path, backend, FakeValidator(True))
    assert res.accepted is not None and res.accepted.task_id.startswith("ff-001-")
    assert (tmp_path / "work" / "fixture" / "map.sqlite").exists()
    (task,) = (tmp_path / "tasks" / "fixture").iterdir()
    toml = (task / "task.toml").read_text()
    assert f'source_url = "{URL}"' in toml and 'origin = "postmortem"' in toml
    assert 'classifier_family = "fail-fast-config"\n\n[verifier]' in toml
    instruction = (task / "instruction.md").read_text()
    assert "## background" in instruction and TRIGGER in instruction and URL in instruction
    assert "credentials rotation" not in instruction
    gen_prompt = backend.prompts[1]
    assert "## real incident this task re-creates" in gen_prompt and TRIGGER in gen_prompt
    assert gen_prompt.index("real incident") < gen_prompt.index("## previous attempt")
    # the generator never sees the report body, only the one-line trigger
    assert "credentials rotation" not in gen_prompt
    record = json.loads((tmp_path / "work" / "postmortems" / "example-org-blog-incident-2025.json").read_text())
    assert record["family"] == "fail-fast-config" and record["source_url"] == URL


def _stub_map(monkeypatch: pytest.MonkeyPatch, surfaces: list[Surface]) -> None:
    monkeypatch.setattr(pm_mod, "map_surfaces", lambda *_a: (surfaces, {}))


SURFACES = [
    Surface(file="backend/app/core/config.py", symbol="Settings", kind="settings-class"),
    Surface(file="backend/app/core/config.py", symbol="Settings.SECRET_KEY", kind="env-read"),
]


def test_tries_next_surface_after_rejection(target: Target, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_map(monkeypatch, SURFACES)
    patch = good_patch(target)
    backend = StubBackend(cls_answer(), *[task_answer(patch)] * 3)
    res = run(target, tmp_path, backend, FakeValidator(False, False, True))
    assert [r.accepted for r in res.reports] == [False, True]
    # the keyword hit puts SECRET_KEY first, so the class-level surface is the fallback
    assert res.reports[0].task_id == "ff-001-secret-key" and res.accepted.task_id == "ff-002-settings"


def test_gives_up_after_tries(target: Target, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_map(monkeypatch, SURFACES)
    patch = good_patch(target)
    res = run(
        target, tmp_path, StubBackend(cls_answer(), *[task_answer(patch)] * 2), FakeValidator(False, False), tries=1
    )
    assert res.accepted is None and len(res.reports) == 1


def test_family_override_keeps_classifier_verdict(
    target: Target, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_map(monkeypatch, [*SURFACES, Surface(file="backend/app/core/config.py", symbol="Pool", kind="pool-config")])
    patch = good_patch(target)
    backend = StubBackend(cls_answer("none", reason="tooling, not config"), task_answer(patch))
    logs: list[str] = []
    res = from_postmortem(
        URL,
        target,
        backend,
        tasks_root=tmp_path / "tasks",
        work_root=tmp_path / "work",
        writer=write_task,
        validator=FakeValidator(True),
        fetch=fake_fetch(HTML),
        family="resource-aware-defaults",
        log=logs.append,
    )
    assert res.classification.family == "resource-aware-defaults" and res.classifier_family == "none"
    assert res.accepted.task_id.startswith("rd-001-")
    (task,) = (tmp_path / "tasks" / "fixture").iterdir()
    meta = tomllib.loads((task / "task.toml").read_text())["metadata"]
    assert meta["family"] == "resource-aware-defaults" and meta["classifier_family"] == "none"
    assert "classifier picked none, using --family resource-aware-defaults as asked" in logs
    record = json.loads((tmp_path / "work" / "postmortems" / "example-org-blog-incident-2025.json").read_text())
    assert record["family"] == "resource-aware-defaults" and record["classifier_family"] == "none"


def test_stamp_metadata_without_trailing_section(tmp_path: Path) -> None:
    f = tmp_path / "task.toml"
    f.write_text('[metadata]\ntitle = "x"\n')
    stamp_metadata(f, "classifier_family", "none")
    assert tomllib.loads(f.read_text())["metadata"] == {"title": "x", "classifier_family": "none"}


def test_family_override_must_exist(tmp_path: Path) -> None:
    with pytest.raises(PostmortemError, match="--family nope"):
        classify(_pm(tmp_path), StubBackend(cls_answer()), _families(), expected="nope")


def test_no_unused_surface(target: Target, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_map(monkeypatch, [])
    with pytest.raises(PostmortemError, match="no unused fail-fast-config surface"):
        run(target, tmp_path, StubBackend(cls_answer()), FakeValidator())


def test_generator_without_incident_is_stock(target: Target, tmp_path: Path) -> None:
    from incidentforge.generate import Pair

    gen = pm_mod.PostmortemGenerator(
        target, StubBackend(), Path(target.repo_url), tmp_path, tmp_path, write_task, FakeValidator()
    )
    fam = load_family("fail-fast-config")
    pair = Pair(fam, SURFACES[0], "fixture/ff-001-settings")
    assert "real incident" not in gen.prompt(pair, [], "")
    spec = gen.build_spec(pair, task_answer(good_patch(target)))
    assert spec.source_url is None and spec.origin == "llm"
    fam.prompt = fam.prompt.replace("## previous attempt", "## earlier try")
    gen.incident = Classification.model_validate(cls_answer())
    assert (
        gen.prompt(Pair(fam, SURFACES[0], "fixture/ff-001-settings"), [], "")
        .rstrip()
        .endswith("a background note linking the report is added for you.")
    )


# cli


class _Res:
    def __init__(self, accepted: ValidationReport | None, said: str = "fail-fast-config") -> None:
        self.accepted = accepted
        self.classifier_family = said
        self.classification = Classification.model_validate(cls_answer())
        self.postmortem = Postmortem(REPORT, URL, Path("x"))


@pytest.mark.parametrize(
    ("outcome", "code", "text"),
    [
        (_Res(ValidationReport(task_id="fixture/ff-001-x", accepted=True, gates=[])), 0, "accepted fixture/ff-001-x"),
        (_Res(None), 1, "no task accepted"),
        (
            _Res(ValidationReport(task_id="fixture/ff-002-x", accepted=True, gates=[]), "none"),
            0,
            "(fail-fast-config, classifier said none)",
        ),
        (NoFamilyFits("nothing fits"), 3, "refused: nothing fits"),
        (PostmortemError("bad url"), 2, "error: bad url"),
    ],
)
def test_cli(monkeypatch: pytest.MonkeyPatch, outcome: Any, code: int, text: str) -> None:
    seen: dict[str, Any] = {}

    def fake(source: str, target: Target, backend: Any, **kw: Any) -> Any:
        seen.update(source=source, target=target.name, **kw)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(pm_mod, "from_postmortem", fake)
    monkeypatch.setattr("incidentforge.backends.base.get_backend", lambda *_a: StubBackend())
    res = CliRunner().invoke(
        cli.app,
        ["from-postmortem", URL, "--target", "fastapi-template", "--tries", "3", "--source-url", URL, "--family", "x"],
    )
    assert res.exit_code == code, res.output
    assert text in res.output
    assert seen["source"] == URL and seen["target"] == "fastapi-template" and seen["tries"] == 3
    assert seen["family"] == "x"
