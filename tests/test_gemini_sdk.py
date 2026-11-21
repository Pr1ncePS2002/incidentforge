"""GeminiBackend through the real google-genai client; only the http transport is faked."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest
from google import genai
from google.genai import errors, types

from incidentforge.backends.gemini import FALLBACK_CODES, GeminiBackend, _code, load_env
from incidentforge.budget import BudgetExhausted, Ledger, cost_usd

MODEL = "gemini-3.8-flash"

# recorded shape of a generateContent reply (values made up, field names as the api sends them)
REPLY: dict[str, Any] = {
    "candidates": [
        {"content": {"parts": [{"text": '{"ok": true}'}], "role": "model"}, "finishReason": "STOP", "index": 0}
    ],
    "usageMetadata": {
        "promptTokenCount": 10_000,
        "candidatesTokenCount": 300,
        "thoughtsTokenCount": 200,
        "cachedContentTokenCount": 8_000,
        "totalTokenCount": 10_500,
    },
    "modelVersion": MODEL,
    "responseId": "abc123",
}


def error_body(code: int) -> dict[str, Any]:
    status = {400: "INVALID_ARGUMENT", 402: "FAILED_PRECONDITION", 403: "PERMISSION_DENIED", 404: "NOT_FOUND"}
    status |= {429: "RESOURCE_EXHAUSTED", 500: "INTERNAL", 503: "UNAVAILABLE"}
    return {"error": {"code": code, "message": f"simulated {code}", "status": status[code]}}


Handler = Callable[[httpx2.Request], httpx2.Response]


def client(handler: Handler, log: list[str]) -> genai.Client:
    def wrapped(req: httpx2.Request) -> httpx2.Response:
        log.append(req.url.path.rsplit(":", 1)[-1])
        return handler(req)

    transport = httpx2.MockTransport(wrapped)
    return genai.Client(
        api_key="test-key", http_options=types.HttpOptions(httpx_client=httpx2.Client(transport=transport))
    )


def respond(status: int, body: dict[str, Any] | None = None) -> Handler:
    def h(req: httpx2.Request) -> httpx2.Response:
        if req.url.path.endswith(":countTokens"):
            return httpx2.Response(200, json={"totalTokens": 1234})
        return httpx2.Response(status, json=body if body is not None else error_body(status))

    return h


def backend(
    tmp_path: Path, free: Handler | None, paid: Handler | None, cap: float = 70.0
) -> tuple[Any, dict[str, list[str]]]:
    calls: dict[str, list[str]] = {"free": [], "paid": []}
    b = GeminiBackend("free-key" if free else None, "paid-key" if paid else None, Ledger(tmp_path / "l.jsonl", cap))
    if free:
        b._clients["free"] = client(free, calls["free"])
    if paid:
        b._clients["paid"] = client(paid, calls["paid"])
    return b, calls


def test_sdk_raises_the_error_classes_we_branch_on(tmp_path: Path) -> None:
    for code, cls in [(402, errors.ClientError), (429, errors.ClientError), (500, errors.ServerError)]:
        b, _ = backend(tmp_path, respond(code), None)
        with pytest.raises(cls) as info:
            b._call("free", MODEL, "hi", 64)
        assert _code(info.value) == code


def test_free_success_is_not_metered(tmp_path: Path) -> None:
    b, calls = backend(tmp_path, respond(200, REPLY), respond(200, REPLY))
    r = b.generate(MODEL, "hi")
    assert (r.key, r.text, r.input_tokens, r.output_tokens) == ("free", '{"ok": true}', 10_000, 500)
    assert calls == {"free": ["generateContent"], "paid": []}
    assert b.ledger.spent() == 0 and not b.ledger.path.exists()


@pytest.mark.parametrize("code", sorted(FALLBACK_CODES))
def test_quota_codes_fall_back_to_paid_and_are_metered(tmp_path: Path, code: int) -> None:
    b, calls = backend(tmp_path, respond(code), respond(200, REPLY))
    r = b.generate(MODEL, "hi", max_output_tokens=1000, tag="t")
    assert r.key == "paid"
    assert calls == {"free": ["generateContent"], "paid": ["countTokens", "generateContent"]}
    # cached prompt tokens are billed at 25% of the input price
    expected = cost_usd(MODEL, 10_000, 500, cached_tokens=8_000)
    assert r.cost_usd == pytest.approx(expected)
    assert expected < cost_usd(MODEL, 10_000, 500)
    assert b.ledger.spent() == pytest.approx(expected, rel=1e-4)
    assert b.ledger.reserved() == 0
    [entry] = b.ledger.entries()
    assert entry["cached_tokens"] == 8_000 and entry["tag"] == "t"


@pytest.mark.parametrize("code", [400, 500, 503])
def test_other_codes_never_touch_the_paid_key(tmp_path: Path, code: int) -> None:
    b, calls = backend(tmp_path, respond(code), respond(200, REPLY))
    with pytest.raises(errors.APIError) as info:
        b.generate(MODEL, "hi")
    assert info.value.code == code
    assert calls["paid"] == [] and not b.ledger.path.exists()


def test_quota_error_without_paid_key_is_raised(tmp_path: Path) -> None:
    b, calls = backend(tmp_path, respond(429), None)
    with pytest.raises(errors.ClientError):
        b.generate(MODEL, "hi")
    assert calls["free"] == ["generateContent"]


def test_no_keys_at_all(tmp_path: Path) -> None:
    b, _ = backend(tmp_path, None, None)
    with pytest.raises(RuntimeError, match="no gemini key"):
        b.generate(MODEL, "hi")


def test_paid_only_skips_free_and_counts_prompt_on_paid_client(tmp_path: Path) -> None:
    b, calls = backend(tmp_path, None, respond(200, REPLY), cap=1.0)
    b.generate(MODEL, "hi", max_output_tokens=100)
    assert calls["paid"] == ["countTokens", "generateContent"]
    reserve = json.loads(b.ledger.path.read_text().splitlines()[0])
    # the hold used the counted prompt (1234 tokens), not the reply's usage
    assert reserve["cost_usd"] == pytest.approx(cost_usd(MODEL, 1234, 100), abs=1e-6)


def test_count_failure_falls_back_to_a_length_bound(tmp_path: Path) -> None:
    def h(req: httpx2.Request) -> httpx2.Response:
        if req.url.path.endswith(":countTokens"):
            return httpx2.Response(500, json=error_body(500))
        return httpx2.Response(200, json=REPLY)

    b, _ = backend(tmp_path, None, h)
    assert b._count_prompt(MODEL, "x" * 100) == 51


def test_failed_paid_call_releases_its_hold(tmp_path: Path) -> None:
    b, calls = backend(tmp_path, respond(429), respond(500), cap=1.0)
    with pytest.raises(errors.ServerError):
        b.generate(MODEL, "hi", max_output_tokens=1000)
    assert calls["paid"] == ["countTokens", "generateContent"]
    assert b.ledger.spent() == 0 and b.ledger.reserved() == 0
    assert b.ledger.remaining() == pytest.approx(1.0)


def test_paid_blocked_by_cap_before_any_paid_request(tmp_path: Path) -> None:
    b, calls = backend(tmp_path, respond(429), respond(200, REPLY), cap=0.001)
    with pytest.raises(BudgetExhausted):
        b.generate(MODEL, "hi", max_output_tokens=8192)
    assert calls["paid"] == ["countTokens"]


def test_reply_without_usage_is_billed_at_worst_case(tmp_path: Path) -> None:
    body = {k: v for k, v in REPLY.items() if k != "usageMetadata"}
    b, _ = backend(tmp_path, None, respond(200, body))
    r = b.generate(MODEL, "hi", max_output_tokens=100)
    assert (r.input_tokens, r.output_tokens) == (1234, 100)
    assert b.ledger.spent() == pytest.approx(cost_usd(MODEL, 1234, 100), rel=1e-4)
    assert b.ledger.reserved() == 0


def test_free_reply_without_usage_reports_zero_tokens(tmp_path: Path) -> None:
    body = {k: v for k, v in REPLY.items() if k != "usageMetadata"}
    b, _ = backend(tmp_path, respond(200, body), None)
    r = b.generate(MODEL, "hi")
    assert (r.key, r.input_tokens, r.output_tokens) == ("free", 0, 0)


def test_real_client_is_built_lazily_per_key(monkeypatch: pytest.MonkeyPatch) -> None:
    made: list[str | None] = []

    class FakeClient:
        def __init__(self, api_key: str | None) -> None:
            made.append(api_key)

    monkeypatch.setattr(genai, "Client", FakeClient)
    b = GeminiBackend("k1", "k2", Ledger(Path("unused.jsonl")))
    assert b._client("free") is b._client("free")
    b._client("paid")
    assert made == ["k1", "k2"]


def test_from_env_prefers_process_env_over_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text("# comment\n\nGEMINI_API_KEY='from-file'\nGEMINI_API_KEY2=\"paid-file\"\nnot a pair\n")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY2", "")
    b = GeminiBackend.from_env(env)
    assert b.free_key == "from-file" and not b.paid_key
    assert load_env(tmp_path / "missing") == {}
