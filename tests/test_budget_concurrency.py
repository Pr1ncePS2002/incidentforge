"""cross-process reservations keep a shared ledger under its cap (F-28)."""

import json
import multiprocessing as mp
import os
import time
from pathlib import Path
from typing import Any

import pytest

from incidentforge.budget import BudgetExhausted, Ledger, cost_usd

MODEL = "gemini-4-argon"
# each call may cost up to $0.10 (4000 output tokens at $25/M) but really costs $0.05
WORST_OUT, REAL_OUT = 4000, 2000
CAP = 1.0


def _hammer(path: str, calls: int, start: Any) -> None:
    led = Ledger(Path(path), cap=CAP)
    start.wait()
    for n in range(calls):
        try:
            rid = led.reserve(MODEL, 0, WORST_OUT, tag=f"pid{os.getpid()}-{n}")
        except BudgetExhausted:
            continue
        # check the invariant while holding a reservation, from inside a writer
        assert led.spent() + led.reserved() <= CAP + 1e-9
        # the api call: without the shared hold, the old check+record overshot by ~40% here
        time.sleep(0.002)
        led.record(MODEL, 0, REAL_OUT, reservation=rid)


def _reserve_and_die(path: str) -> None:
    Ledger(Path(path), cap=CAP).reserve(MODEL, 0, WORST_OUT)
    os._exit(1)


def _ctx() -> mp.context.BaseContext:
    # fork keeps the test fast; spawn is the portable fallback
    return mp.get_context("fork" if "fork" in mp.get_all_start_methods() else "spawn")


def test_parallel_processes_never_overshoot_the_cap(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ctx = _ctx()
    start = ctx.Event()
    procs = [ctx.Process(target=_hammer, args=(str(path), 15, start)) for _ in range(6)]
    for p in procs:
        p.start()
    start.set()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    led = Ledger(path, cap=CAP)
    assert led.reserved() == 0
    assert 0 < led.spent() <= CAP
    # 90 attempts at $0.05 real cost would be $4.50 without the shared reservation
    assert len(led.entries()) <= int(CAP / cost_usd(MODEL, 0, WORST_OUT)) * 2
    lines = [json.loads(x) for x in path.read_text().splitlines()]
    assert all(x["id"] in {y.get("releases") for y in lines} for x in lines if x.get("kind") == "reserve")


def test_reservation_blocks_a_second_ledger_until_recorded(tmp_path: Path) -> None:
    a = Ledger(tmp_path / "l.jsonl", cap=0.15)
    b = Ledger(tmp_path / "l.jsonl", cap=0.15)
    rid = a.reserve(MODEL, 0, WORST_OUT)  # holds $0.10
    with pytest.raises(BudgetExhausted, match="reserved"):
        b.reserve(MODEL, 0, WORST_OUT)
    with pytest.raises(BudgetExhausted):
        b.check(MODEL, 0, WORST_OUT)
    a.record(MODEL, 0, 0, reservation=rid)
    assert b.reserved() == 0 and b.spent() == 0
    b.release(b.reserve(MODEL, 0, WORST_OUT))
    assert b.remaining() == pytest.approx(0.15)


def test_crashed_process_reservation_is_released(tmp_path: Path) -> None:
    path = tmp_path / "l.jsonl"
    p = _ctx().Process(target=_reserve_and_die, args=(str(path),))
    p.start()
    p.join(30)
    assert p.exitcode == 1
    raw = [json.loads(x) for x in path.read_text().splitlines()]
    assert [x["kind"] for x in raw] == ["reserve"]
    led = Ledger(path, cap=CAP)
    # the dead pid's hold no longer counts, so the full cap is free again
    assert led.reserved() == 0
    assert led.remaining() == pytest.approx(CAP)


def test_live_reservation_from_another_host_still_counts(tmp_path: Path) -> None:
    path = tmp_path / "l.jsonl"
    hold = {"kind": "reserve", "id": "x", "cost_usd": 0.4, "pid": 1, "host": "elsewhere"}
    path.write_text(json.dumps(hold) + "\n")
    assert Ledger(path, cap=CAP).reserved() == pytest.approx(0.4)


def test_reader_skips_a_torn_last_line_but_not_a_corrupt_middle(tmp_path: Path) -> None:
    path = tmp_path / "l.jsonl"
    Ledger(path).record(MODEL, 0, 1000)
    with path.open("a") as f:
        f.write('{"model": "gemini-4-ar')
    assert len(Ledger(path).entries()) == 1
    path.write_text('{"broken\n' + path.read_text())
    with pytest.raises(json.JSONDecodeError):
        Ledger(path).entries()


def test_old_ledger_lines_without_kind_still_count_as_spend(tmp_path: Path) -> None:
    path = tmp_path / "l.jsonl"
    path.write_text(json.dumps({"model": MODEL, "cost_usd": 1.25}) + "\n\n")
    led = Ledger(path)
    assert led.spent() == pytest.approx(1.25) and led.reserved() == 0


def test_hold_of_a_pid_we_cannot_signal_still_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    led = Ledger(tmp_path / "l.jsonl", cap=CAP)
    assert led.check(MODEL, 0, WORST_OUT) == pytest.approx(cost_usd(MODEL, 0, WORST_OUT))
    led.reserve(MODEL, 0, WORST_OUT)

    def denied(pid: int, sig: int) -> None:
        raise PermissionError

    # another user's live process answers kill(pid, 0) with EPERM
    monkeypatch.setattr(os, "kill", denied)
    assert led.reserved() == pytest.approx(cost_usd(MODEL, 0, WORST_OUT))
