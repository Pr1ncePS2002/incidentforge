"""cap enforcement and fallback routing for the paid gemini key."""

from types import SimpleNamespace

import pytest

from incidentforge.backends.gemini import GeminiBackend
from incidentforge.budget import (
    HARD_CAP_USD,
    BudgetExhausted,
    Ledger,
    configured_cap,
    cost_usd,
    render,
    status,
)


class ApiError(Exception):
    def __init__(self, code):
        super().__init__(f"api error {code}")
        self.code = code


def resp(text="ok", i=1000, o=500):
    return SimpleNamespace(
        text=text,
        usage_metadata=SimpleNamespace(prompt_token_count=i, candidates_token_count=o, thoughts_token_count=0),
    )


class FakeBackend(GeminiBackend):
    """routes calls to scripted behaviour per key instead of the network."""

    def __init__(self, ledger, free=None, paid=None):
        super().__init__("free-key", "paid-key", ledger)
        self.script = {"free": free, "paid": paid}
        self.calls = []

    def _call(self, which, model, prompt, max_output_tokens):
        self.calls.append(which)
        action = self.script[which]
        if isinstance(action, Exception):
            raise action
        return action

    def _count_prompt(self, model, prompt):
        return 1000


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "ledger.jsonl", cap=HARD_CAP_USD)


def test_cap_cannot_be_raised_by_env(monkeypatch):
    monkeypatch.setenv("FORGE_PAID_CAP_USD", "500")
    assert configured_cap() == HARD_CAP_USD
    monkeypatch.setenv("FORGE_PAID_CAP_USD", "10")
    assert configured_cap() == 10


def test_unknown_model_priced_at_most_expensive():
    assert cost_usd("gemini-9-mystery", 0, 1_000_000) >= cost_usd("gemini-4-argon", 0, 1_000_000)


def test_free_key_used_first_and_not_metered(ledger):
    b = FakeBackend(ledger, free=resp(), paid=resp())
    r = b.generate("gemini-3.8-flash", "hi")
    assert r.key == "free" and b.calls == ["free"]
    assert ledger.spent() == 0


def test_falls_back_to_paid_on_quota_and_records_cost(ledger):
    b = FakeBackend(ledger, free=ApiError(429), paid=resp(i=1000, o=500))
    r = b.generate("gemini-4-argon", "hi")
    assert r.key == "paid" and b.calls == ["free", "paid"]
    assert ledger.spent() == pytest.approx(cost_usd("gemini-4-argon", 1000, 500), rel=1e-4)


def test_non_quota_error_does_not_touch_paid_key(ledger):
    b = FakeBackend(ledger, free=ApiError(400), paid=resp())
    with pytest.raises(ApiError):
        b.generate("gemini-3.8-flash", "hi")
    assert b.calls == ["free"]


def test_paid_call_blocked_once_cap_reached(ledger):
    ledger.record("gemini-4-argon", 0, 2_800_000)  # $70 at 25/M output
    b = FakeBackend(ledger, free=ApiError(429), paid=resp())
    with pytest.raises(BudgetExhausted):
        b.generate("gemini-4-argon", "hi")
    assert b.calls == ["free"]


def test_worst_case_reservation_blocks_call_that_could_cross_cap(tmp_path):
    led = Ledger(tmp_path / "l.jsonl", cap=1.0)
    led.record("gemini-4-argon", 0, 36_000)  # $0.90 spent
    b = FakeBackend(led, free=ApiError(429), paid=resp(o=10))
    with pytest.raises(BudgetExhausted):
        b.generate("gemini-4-argon", "hi", max_output_tokens=8192)  # worst case ~$0.23


def test_status_reports_whether_remaining_eval_fits(ledger):
    ledger.record("gemini-4-argon", 0, 2_000_000)  # $50 spent, $20 left
    s = status(ledger, runs_left=40, per_run_usd=0.65)
    assert s.runs_affordable == 30 and s.fits is False
    text = render(s)
    assert "short by" in text and "30 of 40" in text
    s2 = status(ledger, runs_left=20, per_run_usd=0.65)
    assert s2.fits is True
