"""exact ledger, status and render behaviour; written to kill the mutants mutmut found surviving."""

import json
import os
import re
from pathlib import Path

import pytest

from incidentforge import budget
from incidentforge.budget import (
    PRICES,
    BudgetExhausted,
    BudgetStatus,
    Ledger,
    bar,
    cost_usd,
    default_ledger_path,
    price_for,
    render,
    status,
)


def test_models_prefix_is_stripped_before_pricing() -> None:
    assert price_for("models/gemini-2.5-flash") == PRICES["gemini-2.5-flash"]
    assert price_for("gemini-2.5-flash") == PRICES["gemini-2.5-flash"]


def test_zero_or_negative_cached_tokens_bill_full_input() -> None:
    assert cost_usd("gemini-3.8-flash", 1000, 0) == pytest.approx(1000 * 1.5 / 1e6, rel=1e-9)
    assert cost_usd("gemini-3.8-flash", 1000, 0, cached_tokens=-5) == pytest.approx(1000 * 1.5 / 1e6, rel=1e-9)


def test_default_ledger_path_follows_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("FORGE_LEDGER", raising=False)
    assert default_ledger_path() == Path(".cache/spend-ledger.jsonl")
    monkeypatch.setenv("FORGE_LEDGER", str(tmp_path / "l.jsonl"))
    assert default_ledger_path() == tmp_path / "l.jsonl"


def test_default_ledger_uses_env_path_and_cap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FORGE_LEDGER", str(tmp_path / "l.jsonl"))
    monkeypatch.setenv("FORGE_PAID_CAP_USD", "12.5")
    led = Ledger.default()
    assert led.path == tmp_path / "l.jsonl" and led.cap == 12.5


def test_remaining_subtracts_spend_and_floors_at_zero(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "l.jsonl", cap=1.0)
    led.record("gemini-4-argon", 0, 10_000)  # $0.25
    assert led.remaining() == pytest.approx(0.75)
    led.record("gemini-4-argon", 0, 80_000)  # +$2.00
    assert led.remaining() == 0.0


def test_check_refuses_at_exactly_the_cap_even_for_a_free_call(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "l.jsonl", cap=1.0)
    led.record("gemini-4-argon", 0, 40_000)  # exactly $1.00
    with pytest.raises(BudgetExhausted):
        led.check("gemini-4-argon", 0, 0)


def test_check_allows_a_call_that_lands_exactly_on_the_cap(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "l.jsonl", cap=1.0)
    assert led.check("gemini-4-argon", 0, 40_000) == 1.0


def test_refusal_message_names_spend_holds_and_cap(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "l.jsonl", cap=1.0)
    led.record("gemini-4-argon", 0, 36_000)  # $0.90
    with pytest.raises(BudgetExhausted, match=r"spent \$0\.90 \(\+\$0\.00 reserved by running calls\) of \$1\.00 cap"):
        led.check("gemini-4-argon", 0, 8192)


def test_record_writes_the_exact_entry_into_a_new_nested_dir(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "a" / "b" / "l.jsonl")
    led.record("gemini-2.5-flash-lite", 1, 0)
    [entry] = [json.loads(x) for x in led.path.read_text().splitlines()]
    assert set(entry) == {"ts", "model", "input_tokens", "output_tokens", "cached_tokens", "cost_usd", "tag"}
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4}", entry["ts"])
    assert entry["model"] == "gemini-2.5-flash-lite"
    assert (entry["input_tokens"], entry["output_tokens"], entry["cached_tokens"]) == (1, 0, 0)
    # $1e-7 rounds away at 6 decimals
    assert entry["cost_usd"] == 0.0
    assert entry["tag"] == ""


def test_status_floors_remaining_and_leaves_affordable_unset(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "l.jsonl", cap=1.0)
    led.record("gemini-4-argon", 0, 80_000)  # $2 > cap
    s = status(led)
    assert s.remaining == 0.0 and s.runs_affordable is None and s.fits is None


def test_affordable_runs_use_floor_division() -> None:
    # 1.0 // 0.1 is 9.0 in floats; the budget rounds down rather than over-promise a run
    s = status(Ledger(Path("/nonexistent/l.jsonl"), cap=1.0), runs_left=9, per_run_usd=0.1)
    assert s.runs_affordable == 9


def test_bar_is_exact() -> None:
    assert bar(0.5) == "[" + "#" * 15 + "-" * 15 + "]"
    assert bar(0.5, 10) == "[#####-----]"
    assert bar(-1, 4) == "[----]"
    assert bar(2, 4) == "[####]"
    assert bar(0.25, 4) == "[#---]"


def _status(spent: float, cap: float, runs_left: int | None = None, per_run: float | None = None) -> BudgetStatus:
    remaining = max(cap - spent, 0.0)
    affordable = int(remaining // per_run) if per_run else None
    return BudgetStatus(spent, cap, remaining, runs_left, per_run, affordable)


def test_render_fits() -> None:
    assert render(_status(10, 40, runs_left=4, per_run=2.5)) == (
        "paid key   [" + "#" * 8 + "-" * 22 + "]  $10.00 / $40.00  ($30.00 left)\n"
        "eval left  4 runs x ~$2.50 = ~$10.00  -> affordable runs: 12\n"
        "verdict    remaining evaluation fits in the paid budget"
    )


def test_render_short_and_blocked() -> None:
    assert render(_status(40, 40, runs_left=4, per_run=2.5)) == (
        "paid key   [" + "#" * 30 + "]  $40.00 / $40.00  ($0.00 left)\n"
        "eval left  4 runs x ~$2.50 = ~$10.00  -> affordable runs: 0\n"
        "verdict    short by ~$10.00: only 0 of 4 runs fit; the rest must use the free key or a new key\n"
        "status     paid key is permanently blocked (cap reached)"
    )


def test_render_without_per_run_and_with_zero_cap() -> None:
    assert (
        render(_status(0.5, 1, runs_left=5)) == "paid key   [" + "#" * 15 + "-" * 15 + "]  $0.50 / $1.00  ($0.50 left)"
    )
    assert render(_status(0, 0)).startswith("paid key   [" + "#" * 30 + "]")


def test_render_short_with_money_left() -> None:
    assert render(_status(35, 40, runs_left=4, per_run=2.5)).splitlines()[2] == (
        "verdict    short by ~$5.00: only 2 of 4 runs fit; the rest must use the free key or a new key"
    )


def test_blank_lines_mid_ledger_are_skipped(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "l.jsonl")
    led.path.write_text('{"cost_usd": 1.0}\n\n{"cost_usd": 2.0}\n')
    assert led.spent() == 3.0


def test_reserve_and_release_write_exact_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(budget.socket, "gethostname", lambda: "host-a")
    led = Ledger(tmp_path / "l.jsonl")
    rid = led.reserve("gemini-2.5-flash-lite", 1, 0)
    led.release(rid)
    hold, rel = [json.loads(x) for x in led.path.read_text().splitlines()]
    assert set(hold) == {"kind", "id", "ts", "model", "cost_usd", "pid", "host", "tag"}
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4}", hold["ts"])
    assert (hold["kind"], hold["id"], hold["model"], hold["cost_usd"]) == ("reserve", rid, "gemini-2.5-flash-lite", 0.0)
    assert (hold["pid"], hold["host"], hold["tag"]) == (os.getpid(), "host-a", "")
    assert rel == {"kind": "release", "releases": rid}


def test_open_hold_counts_against_remaining_and_check(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "l.jsonl", cap=1.0)
    led.record("gemini-4-argon", 0, 20_000)  # $0.50 spent
    led.reserve("gemini-4-argon", 0, 10_000)  # $0.25 held
    assert led.remaining() == pytest.approx(0.25)
    led.reserve("gemini-4-argon", 0, 10_000)  # spent + held now exactly the cap
    with pytest.raises(BudgetExhausted):
        led.check("gemini-4-argon", 0, 0)


def test_local_hold_without_pid_still_counts(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "l.jsonl")
    hold = {"kind": "reserve", "id": "r1", "cost_usd": 2.0, "host": budget.socket.gethostname()}
    led.path.write_text(json.dumps(hold) + "\n")
    assert led.reserved() == 2.0
