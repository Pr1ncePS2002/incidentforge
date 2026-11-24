"""codex, opencode, gemini-cli and command backends against fake executables on PATH."""

import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from incidentforge.backends.base import MalformedOutput, get_backend, pick_auto
from incidentforge.backends.cli import (
    OPENCODE_CONFIG,
    CliBackend,
    CliBackendError,
    CodexBackend,
    CommandBackend,
    GeminiCliBackend,
    OpenCodeBackend,
)

SCHEMA = {
    "type": "object",
    "properties": {"a": {"type": "integer"}, "b": {"type": "string"}},
    "required": ["a"],
}
# each fake appends {argv, stdin, env subset} to $FAKE_LOG, then runs the test's body
PRELUDE = """import json, os, sys, time, pathlib
argv = sys.argv[1:]
stdin = sys.stdin.read()
keep = ("OPENCODE_CONFIG_CONTENT", "OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX")
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"argv": argv, "stdin": stdin, "env": {k: os.environ.get(k) for k in keep}}) + "\\n")
n = sum(1 for _ in open(os.environ["FAKE_LOG"]))
"""


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_LOG", str(log))

    def make(name: str, body: str) -> Any:
        script = bindir / name
        script.write_text(f"#!{sys.executable}\n{PRELUDE}{body}\n")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        return lambda: [json.loads(line) for line in log.read_text().splitlines()]

    return make


def _flag(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


# codex


CODEX_OK = """out = pathlib.Path(argv[argv.index("-o") + 1])
out.write_text('{"a": 1, "b": "x"}' if n == 1 or "rejected" in stdin else "nope")
print("progress line")
"""


def test_codex_success_flags_and_last_message(fake: Any) -> None:
    calls = fake("codex", CODEX_OK)
    be = CodexBackend(model="gpt-x")
    assert be.generate_json("hello", SCHEMA, tag="t1") == {"a": 1, "b": "x"}
    (call,) = calls()
    argv = call["argv"]
    assert argv[0] == "exec" and argv[-1] == "-"
    assert _flag(argv, "-s") == "read-only" and _flag(argv, "-m") == "gpt-x"
    assert 'approval_policy="never"' in argv and "--ignore-user-config" in argv
    assert call["stdin"].startswith("hello") and json.dumps(SCHEMA) in call["stdin"]
    assert be.calls == [{"tag": "t1", "returncode": 0}]


def test_codex_stdout_fallback_without_model(fake: Any) -> None:
    calls = fake("codex", "print('{\"a\": 2}')")
    assert CodexBackend().generate_json("p", SCHEMA) == {"a": 2}
    assert "-m" not in calls()[0]["argv"]


def test_codex_non_zero_exit(fake: Any) -> None:
    fake("codex", 'print("refresh token was revoked", file=sys.stderr); sys.exit(1)')
    with pytest.raises(CliBackendError, match="codex exit 1: refresh token was revoked"):
        CodexBackend().generate_json("p", SCHEMA)


def test_codex_timeout(fake: Any) -> None:
    fake("codex", "time.sleep(10)")
    with pytest.raises(CliBackendError, match="timed out"):
        CodexBackend(timeout=0.5).generate_json("p", SCHEMA)


def test_codex_retries_once_on_malformed(fake: Any) -> None:
    calls = fake("codex", 'print("sure, here it is" if n == 1 else \'{"a": 3}\')')
    assert CodexBackend().generate_json("p", SCHEMA) == {"a": 3}
    assert "rejected" in calls()[1]["stdin"]


def test_codex_gives_up_after_retry(fake: Any) -> None:
    calls = fake("codex", 'print(\'{"b": "no a"}\')')
    with pytest.raises(MalformedOutput, match="missing"):
        CodexBackend().generate_json("p", SCHEMA)
    assert len(calls()) == 2


def test_missing_binary_is_a_backend_error(fake: Any) -> None:
    with pytest.raises(CliBackendError, match="not found on PATH"):
        CodexBackend(binary="no-such-cli-xyz").generate_json("p", SCHEMA)


# opencode


def _events(*events: dict[str, Any]) -> str:
    lines = "\n".join(json.dumps(e) for e in events)
    return f"print({lines!r})"


def test_opencode_joins_text_events_and_denies_tools(fake: Any) -> None:
    body = _events(
        {"type": "step_start"},
        {"type": "text", "part": {"text": '{"a": 4, '}},
        {"type": "text", "part": {"text": '"b": "y"}'}},
    )
    calls = fake("opencode", f'print("not json"); print("[1]"); {body}')
    be = OpenCodeBackend(model="prov/model-1")
    assert be.generate_json("p", SCHEMA, max_output_tokens=77) == {"a": 4, "b": "y"}
    call = calls()[0]
    assert call["argv"][:4] == ["run", "--pure", "--format", "json"]
    assert _flag(call["argv"], "-m") == "prov/model-1"
    assert call["env"] == {"OPENCODE_CONFIG_CONTENT": OPENCODE_CONFIG, "OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX": "77"}
    assert json.loads(OPENCODE_CONFIG)["permission"] == {"*": "deny"}


def test_opencode_error_event_fails_even_on_exit_zero(fake: Any) -> None:
    fake(
        "opencode", _events({"type": "error", "error": {"name": "APIError", "data": {"message": "Invalid credential"}}})
    )
    with pytest.raises(CliBackendError, match="Invalid credential"):
        OpenCodeBackend().generate_json("p", SCHEMA)


def test_opencode_error_event_without_message(fake: Any) -> None:
    fake("opencode", _events({"type": "error"}))
    with pytest.raises(CliBackendError, match="unknown error"):
        OpenCodeBackend().generate_json("p", SCHEMA)


def test_opencode_non_zero_exit(fake: Any) -> None:
    fake("opencode", 'print("Configuration is invalid", file=sys.stderr); sys.exit(1)')
    with pytest.raises(CliBackendError, match="opencode exit 1: Configuration is invalid"):
        OpenCodeBackend().generate_json("p", SCHEMA)


def test_opencode_plain_stdout_and_no_model(fake: Any) -> None:
    calls = fake("opencode", "print('{\"a\": 5}')")
    assert OpenCodeBackend().generate_json("p", SCHEMA) == {"a": 5}
    assert "-m" not in calls()[0]["argv"]


def test_opencode_malformed_then_timeout(fake: Any) -> None:
    fake("opencode", _events({"type": "text", "part": {"text": "no json"}}))
    with pytest.raises(MalformedOutput):
        OpenCodeBackend().generate_json("p", SCHEMA)
    fake("opencode", "time.sleep(10)")
    with pytest.raises(CliBackendError, match="opencode timed out"):
        OpenCodeBackend(timeout=0.5).generate_json("p", SCHEMA)


# gemini-cli


def test_gemini_cli_response_envelope(fake: Any) -> None:
    calls = fake("gemini", 'print(json.dumps({"response": "```json\\n{\\"a\\": 6}\\n```", "stats": {}}))')
    assert GeminiCliBackend(model="gemini-x").generate_json("p", SCHEMA) == {"a": 6}
    argv = calls()[0]["argv"]
    assert _flag(argv, "--output-format") == "json" and _flag(argv, "-m") == "gemini-x"
    assert _flag(argv, "-e") == "none"


def test_gemini_cli_error_envelope(fake: Any) -> None:
    fake("gemini", 'print(json.dumps({"error": {"message": "quota exceeded"}})); sys.exit(1)')
    with pytest.raises(CliBackendError, match="gemini-cli error: quota exceeded"):
        GeminiCliBackend().generate_json("p", SCHEMA)
    fake("gemini", 'print(json.dumps({"error": "plain string"}))')
    with pytest.raises(CliBackendError, match="plain string"):
        GeminiCliBackend().generate_json("p", SCHEMA)


def test_gemini_cli_non_zero_exit_and_plain_stdout(fake: Any) -> None:
    fake("gemini", 'print("auth required", file=sys.stderr); sys.exit(41)')
    with pytest.raises(CliBackendError, match="gemini-cli exit 41: auth required"):
        GeminiCliBackend().generate_json("p", SCHEMA)
    calls = fake("gemini", "print('{\"a\": 7}')")
    assert GeminiCliBackend().generate_json("p", SCHEMA) == {"a": 7}
    assert "-m" not in calls()[-1]["argv"]


def test_gemini_cli_malformed_and_timeout(fake: Any) -> None:
    fake("gemini", 'print(json.dumps({"response": "sorry"}))')
    with pytest.raises(MalformedOutput):
        GeminiCliBackend().generate_json("p", SCHEMA)
    fake("gemini", "time.sleep(10)")
    with pytest.raises(CliBackendError, match="timed out"):
        GeminiCliBackend(timeout=0.5).generate_json("p", SCHEMA)


# command


def test_command_prompt_on_stdin(fake: Any) -> None:
    calls = fake("mycli", "print('{\"a\": 8}')")
    be = CommandBackend(template="mycli --quiet")
    assert be.generate_json("hello", SCHEMA) == {"a": 8}
    call = calls()[0]
    assert call["argv"] == ["--quiet"] and call["stdin"].startswith("hello")


def test_command_prompt_and_schema_files(fake: Any) -> None:
    body = """prompt = pathlib.Path(argv[argv.index("--message-file") + 1]).read_text()
schema = json.loads(pathlib.Path(argv[argv.index("--schema") + 1]).read_text())
print(json.dumps({"a": len(schema["required"]), "b": prompt[:5]}))
"""
    calls = fake("mycli", body)
    be = CommandBackend(
        model="m1", template="mycli --message-file {prompt_file} --schema {schema_file} --model {model}"
    )
    assert be.generate_json("hello", SCHEMA) == {"a": 1, "b": "hello"}
    call = calls()[0]
    assert call["stdin"] == "" and call["argv"][-1] == "m1"


def test_command_errors(fake: Any) -> None:
    with pytest.raises(CliBackendError, match="FORGE_GEN_COMMAND"):
        CommandBackend(template="  ").generate_json("p", SCHEMA)
    fake("mycli", "sys.exit(3)")
    with pytest.raises(CliBackendError, match="command exit 3"):
        CommandBackend(template="mycli").generate_json("p", SCHEMA)
    fake("mycli", "time.sleep(10)")
    with pytest.raises(CliBackendError, match="command timed out"):
        CommandBackend(template="mycli", timeout=0.5).generate_json("p", SCHEMA)
    fake("mycli", 'print("not json")')
    with pytest.raises(MalformedOutput):
        CommandBackend(template="mycli").generate_json("p", SCHEMA)


def test_base_command_is_abstract() -> None:
    with pytest.raises(NotImplementedError):
        CliBackend().command("/tmp")


# get_backend and the cli


def test_get_backend_names(monkeypatch: pytest.MonkeyPatch) -> None:
    assert isinstance(get_backend("codex", "m"), CodexBackend)
    assert isinstance(get_backend("opencode"), OpenCodeBackend)
    assert isinstance(get_backend("gemini-cli"), GeminiCliBackend)
    explicit = get_backend("command", command="x --y")
    assert isinstance(explicit, CommandBackend) and explicit.template == "x --y"
    monkeypatch.setenv("FORGE_GEN_COMMAND", "aider --message-file {prompt_file}")
    from_env = get_backend("command")
    assert isinstance(from_env, CommandBackend) and from_env.template.startswith("aider")
    monkeypatch.delenv("FORGE_GEN_COMMAND")
    with pytest.raises(ValueError, match="FORGE_GEN_COMMAND"):
        get_backend("command")
    with pytest.raises(ValueError, match="codex, opencode, gemini-cli"):
        get_backend("nope")


def test_auto_picks_first_cli_on_path(fake: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    with pytest.raises(ValueError, match="found none"):
        pick_auto()
    fake("gemini", "")
    assert pick_auto() == "gemini-cli"
    fake("opencode", "")
    assert isinstance(get_backend("auto"), OpenCodeBackend)


def test_forge_run_rejects_bad_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    from incidentforge.cli import app

    monkeypatch.delenv("FORGE_GEN_COMMAND", raising=False)
    res = CliRunner().invoke(app, ["run", "--target", "click", "--backend", "command"])
    assert res.exit_code == 2
    assert "FORGE_GEN_COMMAND" in res.output
