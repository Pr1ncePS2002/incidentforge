"""gemini backend: free key first, paid key only as a metered fallback."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from incidentforge.budget import BudgetExhausted, Ledger

# errors that mean "this key can't serve this call", so the paid key may try
FALLBACK_CODES = {402, 403, 404, 429}


def load_env(path: str | Path = ".env") -> dict[str, str]:
    env: dict[str, str] = {}
    p = Path(path)
    if not p.exists():
        return env
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip("\"'")
    return env


def _code(exc: Exception) -> int | None:
    return getattr(exc, "code", None) or getattr(exc, "status_code", None)


@dataclass
class Result:
    text: str
    model: str
    key: str  # "free" or "paid"
    input_tokens: int
    output_tokens: int
    cost_usd: float = 0.0


@dataclass
class GeminiBackend:
    free_key: str | None
    paid_key: str | None
    ledger: Ledger = field(default_factory=Ledger.default)
    _clients: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_env(cls, env_path: str | Path = ".env") -> GeminiBackend:
        env = {**load_env(env_path), **os.environ}
        return cls(env.get("GEMINI_API_KEY"), env.get("GEMINI_API_KEY2"))

    def _client(self, which: str) -> Any:
        if which not in self._clients:
            from google import genai

            key = self.free_key if which == "free" else self.paid_key
            self._clients[which] = genai.Client(api_key=key)
        return self._clients[which]

    def _call(self, which: str, model: str, prompt: str, max_output_tokens: int) -> Any:
        from google.genai import types

        return self._client(which).models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=max_output_tokens),
        )

    @staticmethod
    def _usage(resp: Any) -> tuple[int, int, int] | None:
        """(prompt, output incl. thinking, cached prompt) tokens, or None when the reply carries no usage."""
        u = getattr(resp, "usage_metadata", None)
        if u is None:
            return None
        out = (u.candidates_token_count or 0) + (getattr(u, "thoughts_token_count", 0) or 0)
        return u.prompt_token_count or 0, out, getattr(u, "cached_content_token_count", 0) or 0

    def _count_prompt(self, model: str, prompt: str) -> int:
        try:
            return int(self._client("paid").models.count_tokens(model=model, contents=prompt).total_tokens)
        except Exception:  # noqa: BLE001
            # any counting failure falls back to a rough upper bound
            return len(prompt) // 2 + 1

    def generate(self, model: str, prompt: str, max_output_tokens: int = 8192, tag: str = "") -> Result:
        if self.free_key:
            try:
                resp = self._call("free", model, prompt, max_output_tokens)
                i, o, _ = self._usage(resp) or (0, 0, 0)
                return Result(resp.text or "", model, "free", i, o)
            except Exception as exc:
                if _code(exc) not in FALLBACK_CODES or not self.paid_key:
                    raise
        if not self.paid_key:
            raise RuntimeError("no gemini key configured")
        # the worst case is held in the shared ledger before any paid token is spent
        prompt_tokens = self._count_prompt(model, prompt)
        rid = self.ledger.reserve(model, prompt_tokens, max_output_tokens, tag=tag)
        try:
            resp = self._call("paid", model, prompt, max_output_tokens)
        except BaseException:
            # a failed call bills nothing on gemini, so its hold goes back to the pool
            self.ledger.release(rid)
            raise
        usage = self._usage(resp)
        # a reply without usage is billed at the reserved worst case rather than for free
        i, o, cached = usage or (prompt_tokens, max_output_tokens, 0)
        cost = self.ledger.record(model, i, o, tag=tag, cached_tokens=cached, reservation=rid)
        return Result(resp.text or "", model, "paid", i, o, cost)


__all__ = ["BudgetExhausted", "GeminiBackend", "Result", "load_env"]
