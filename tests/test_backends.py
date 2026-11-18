"""claude code and gemini json backends against fake subprocess / fake gemini."""

import json
import subprocess
from dataclasses import dataclass
from typing import Any

import pytest

from incidentforge.backends.base import (
    GeminiJsonBackend,
    MalformedOutput,
    check_schema,
    extract_json,
    get_backend,
)
from incidentforge.backends.claude_code import ClaudeCodeBackend, ClaudeCodeError

SCHEMA = {
    "type": "object",
    "properties": {"a": {"type": "integer"}, "b": {"type": "string"}},
    "required": ["a"],
}


class FakeRunner:
    def __init__(self, *outs: tuple[int, str]) -> None:
        self.outs = list(outs)
        self.calls: list[tuple[list[str], str, float, str]] = []

    def __call__(self, cmd: list[str], stdin: str, timeout: float, cwd: str) -> subprocess.CompletedProcess[str]:
        self.calls.append((cmd, stdin, timeout, cwd))
        code, out = self.outs.pop(0)
        return subprocess.CompletedProcess(cmd, code, out, "boom")


def envelope(**kw: Any) -> str:
    return json.dumps({"type": "result", "is_error": False, "total_cost_usd": 0.01, **kw})


def test_extract_json_variants() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('sure:\n```json\n{"a": 2}\n```') == {"a": 2}
    assert extract_json('prefix {"a": 3} suffix') == {"a": 3}
    with pytest.raises(MalformedOutput):
        extract_json("[1, 2]")
    with pytest.raises(MalformedOutput):
        extract_json("no json here")


def test_check_schema() -> None:
    check_schema({"a": 1, "b": "x"}, SCHEMA)
    with pytest.raises(MalformedOutput, match="missing"):
        check_schema({"b": "x"}, SCHEMA)
    with pytest.raises(MalformedOutput, match="should be"):
        check_schema({"a": "1"}, SCHEMA)


def test_claude_structured_output() -> None:
    run = FakeRunner((0, envelope(structured_output={"a": 1}, result="ignored")))
    be = ClaudeCodeBackend(model="opus", runner=run)
    assert be.generate_json("hello", SCHEMA, tag="t1") == {"a": 1}
    cmd, stdin, timeout, _ = run.calls[0]
    assert stdin == "hello" and timeout == 600.0
    assert cmd[cmd.index("--model") + 1] == "opus"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == SCHEMA
    assert be.cost_usd == pytest.approx(0.01)
    assert be.calls[0]["tag"] == "t1"


def test_claude_result_text_fallback_and_no_model() -> None:
    run = FakeRunner((0, envelope(result='```json\n{"a": 5}\n```')))
    be = ClaudeCodeBackend(runner=run)
    assert be.generate_json("p", SCHEMA) == {"a": 5}
    assert "--model" not in run.calls[0][0]


def test_claude_retries_once_on_malformed() -> None:
    run = FakeRunner((0, envelope(result="oops")), (0, envelope(result='{"a": 7}')))
    assert ClaudeCodeBackend(runner=run).generate_json("p", SCHEMA) == {"a": 7}
    assert "rejected" in run.calls[1][1]


def test_claude_gives_up_after_retry() -> None:
    run = FakeRunner((0, envelope(result="oops")), (0, envelope(result='{"b": "x"}')))
    with pytest.raises(MalformedOutput):
        ClaudeCodeBackend(runner=run).generate_json("p", SCHEMA)


def test_claude_error_envelope() -> None:
    run = FakeRunner((1, envelope(is_error=True, result="Not logged in")))
    with pytest.raises(ClaudeCodeError, match="Not logged in"):
        ClaudeCodeBackend(runner=run).generate_json("p", SCHEMA)


def test_claude_non_json_stdout() -> None:
    with pytest.raises(ClaudeCodeError, match="exit 2"):
        ClaudeCodeBackend(runner=FakeRunner((2, "crash"))).generate_json("p", SCHEMA)


def test_claude_timeout() -> None:
    def slow(cmd: list[str], stdin: str, timeout: float, cwd: str) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd, timeout)

    with pytest.raises(ClaudeCodeError, match="timed out"):
        ClaudeCodeBackend(runner=slow, timeout=1).generate_json("p", SCHEMA)


def test_default_runner_executes(tmp_path: Any) -> None:
    from incidentforge.backends.claude_code import _run

    proc = _run(["cat"], "hi", 5, str(tmp_path))
    assert proc.stdout == "hi"


@dataclass
class FakeResult:
    text: str


class FakeGemini:
    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.prompts: list[str] = []

    def generate(self, model: str, prompt: str, max_output_tokens: int = 8192, tag: str = "") -> FakeResult:
        self.prompts.append(prompt)
        return FakeResult(self.texts.pop(0))


def test_gemini_adapter_retry() -> None:
    fake = FakeGemini("nope", '{"a": 1}')
    be = GeminiJsonBackend(fake, model="m")
    assert be.generate_json("p", SCHEMA) == {"a": 1}
    assert "json schema" in fake.prompts[0]
    assert "rejected" in fake.prompts[1]


def test_get_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    assert get_backend("claude-code", "sonnet").name == "claude-code"
    monkeypatch.setenv("GEMINI_API_KEY2", "")
    assert get_backend("gemini").name == "gemini"
    with pytest.raises(ValueError, match="unknown backend"):
        get_backend("other")
