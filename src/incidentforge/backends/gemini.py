"""gemini backend: free key first, paid key only as a metered fallback."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

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
    _clients: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_env(cls, env_path: str | Path = ".env") -> GeminiBackend:
        env = {**load_env(env_path), **os.environ}
        return cls(env.get("GEMINI_API_KEY"), env.get("GEMINI_API_KEY2"))

    def _client(self, which: str):
        if which not in self._clients:
            from google import genai

            key = self.free_key if which == "free" else self.paid_key
            self._clients[which] = genai.Client(api_key=key)
        return self._clients[which]

    def _call(self, which: str, model: str, prompt: str, max_output_tokens: int):
        from google.genai import types

        return self._client(which).models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=max_output_tokens),
        )

    @staticmethod
    def _usage(resp) -> tuple[int, int]:
        u = resp.usage_metadata
        out = (u.candidates_token_count or 0) + (getattr(u, "thoughts_token_count", 0) or 0)
        return u.prompt_token_count or 0, out

    def _count_prompt(self, model: str, prompt: str) -> int:
        try:
            return self._client("paid").models.count_tokens(model=model, contents=prompt).total_tokens
        except Exception:  # noqa: BLE001
            # any counting failure falls back to a rough upper bound
            return len(prompt) // 2 + 1

    def generate(self, model: str, prompt: str, max_output_tokens: int = 8192, tag: str = "") -> Result:
        if self.free_key:
            try:
                resp = self._call("free", model, prompt, max_output_tokens)
                i, o = self._usage(resp)
                return Result(resp.text or "", model, "free", i, o)
            except Exception as exc:
                if _code(exc) not in FALLBACK_CODES or not self.paid_key:
                    raise
        if not self.paid_key:
            raise RuntimeError("no gemini key configured")
        # the cap check reserves the worst case before any paid token is spent
        self.ledger.check(model, self._count_prompt(model, prompt), max_output_tokens)
        resp = self._call("paid", model, prompt, max_output_tokens)
        i, o = self._usage(resp)
        cost = self.ledger.record(model, i, o, tag=tag)
        return Result(resp.text or "", model, "paid", i, o, cost)


__all__ = ["BudgetExhausted", "GeminiBackend", "Result", "load_env"]
