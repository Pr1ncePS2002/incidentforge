"""spend ledger and hard cap for the paid fallback gemini key."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# absolute ceiling for the paid key; env may lower it, never raise it
HARD_CAP_USD = 70.0

# usd per million tokens (input, output incl. thinking); priced high on purpose so the bill lands under the cap
PRICES: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (2.50, 15.00),
    "gemini-3.5-flash-lite": (0.25, 1.50),
    "gemini-3.5-flash": (0.75, 3.75),
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3.7-flash": (0.75, 3.75),
    "gemini-3.8-flash": (1.50, 7.50),
    "gemini-4-hydrogen": (2.50, 15.00),
    "gemini-4-carbon": (5.00, 25.00),
    "gemini-4-argon": (5.00, 25.00),
}
# unknown models get the most expensive known price
FALLBACK_PRICE = max(PRICES.values(), key=lambda p: p[1])
# cached input is billed at a fraction of the input price; 0.25 sits at or above the published cached rates
CACHED_INPUT_FRACTION = 0.25


class BudgetExhausted(RuntimeError):
    """raised when a paid call could push spend past the cap."""


def price_for(model: str) -> tuple[float, float]:
    return PRICES.get(model.removeprefix("models/"), FALLBACK_PRICE)


def cost_usd(model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
    """input_tokens includes cached_tokens, as harbor and gemini report them."""
    pin, pout = price_for(model)
    cached = min(max(cached_tokens, 0), input_tokens)
    fresh = input_tokens - cached
    return (fresh * pin + cached * pin * CACHED_INPUT_FRACTION + output_tokens * pout) / 1_000_000


def default_ledger_path() -> Path:
    return Path(os.environ.get("FORGE_LEDGER", ".cache/spend-ledger.jsonl"))


def configured_cap() -> float:
    raw = os.environ.get("FORGE_PAID_CAP_USD")
    if not raw:
        return HARD_CAP_USD
    return min(float(raw), HARD_CAP_USD)


@dataclass
class Ledger:
    path: Path
    cap: float = HARD_CAP_USD

    @classmethod
    def default(cls) -> Ledger:
        return cls(default_ledger_path(), configured_cap())

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in self.path.read_text().splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out

    def spent(self) -> float:
        return float(sum(e["cost_usd"] for e in self.entries()))

    def remaining(self) -> float:
        return max(self.cap - self.spent(), 0.0)

    def check(self, model: str, input_tokens: int, max_output_tokens: int) -> float:
        """refuse the call unless its worst case still fits under the cap."""
        worst = cost_usd(model, input_tokens, max_output_tokens)
        spent = self.spent()
        if spent >= self.cap or spent + worst > self.cap:
            raise BudgetExhausted(
                f"paid key blocked: spent ${spent:.2f} of ${self.cap:.2f} cap, this call could cost up to ${worst:.2f}"
            )
        return worst

    def record(self, model: str, input_tokens: int, output_tokens: int, tag: str = "", cached_tokens: int = 0) -> float:
        c = cost_usd(model, input_tokens, output_tokens, cached_tokens)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_tokens": cached_tokens,
            "cost_usd": round(c, 6),
            "tag": tag,
        }
        with self.path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        return c


@dataclass
class BudgetStatus:
    spent: float
    cap: float
    remaining: float
    runs_left: int | None
    per_run: float | None
    runs_affordable: int | None

    @property
    def fits(self) -> bool | None:
        if self.runs_left is None or self.runs_affordable is None:
            return None
        return self.runs_affordable >= self.runs_left


def status(ledger: Ledger, runs_left: int | None = None, per_run_usd: float | None = None) -> BudgetStatus:
    spent = ledger.spent()
    remaining = max(ledger.cap - spent, 0.0)
    affordable = None
    if per_run_usd:
        affordable = int(remaining // per_run_usd)
    return BudgetStatus(spent, ledger.cap, remaining, runs_left, per_run_usd, affordable)


def bar(frac: float, width: int = 30) -> str:
    frac = min(max(frac, 0.0), 1.0)
    filled = round(frac * width)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def render(s: BudgetStatus) -> str:
    lines = [
        (f"paid key   {bar(s.spent / s.cap if s.cap else 1)}  ${s.spent:.2f} / ${s.cap:.2f}  (${s.remaining:.2f} left)")
    ]
    if s.runs_left is not None and s.per_run is not None:
        need = s.runs_left * s.per_run
        lines.append(
            f"eval left  {s.runs_left} runs x ~${s.per_run:.2f} = ~${need:.2f}  -> affordable runs: {s.runs_affordable}"
        )
        if s.fits:
            lines.append("verdict    remaining evaluation fits in the paid budget")
        else:
            short = need - s.remaining
            lines.append(
                f"verdict    short by ~${short:.2f}: only {s.runs_affordable} of {s.runs_left} runs fit; "
                "the rest must use the free key or a new key"
            )
    if s.remaining <= 0:
        lines.append("status     paid key is permanently blocked (cap reached)")
    return "\n".join(lines)
