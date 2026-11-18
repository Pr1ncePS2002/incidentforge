"""generator backend contract and shared json helpers. owner: phase 2."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol


class Backend(Protocol):
    name: str

    def generate_json(
        self, prompt: str, schema: dict[str, Any], max_output_tokens: int = 8192, tag: str = ""
    ) -> dict[str, Any]:
        """return a json object matching schema; raise on failure."""
        ...


class MalformedOutput(ValueError):
    """the model answered, but not with a json object that fits the schema."""


_FENCE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.DOTALL)


def extract_json(text: str) -> dict[str, Any]:
    """pull one json object out of model text that may carry fences or prose around it."""
    candidates = [text.strip(), *_FENCE.findall(text)]
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for c in candidates:
        try:
            obj = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise MalformedOutput(f"no json object in model output: {text[:200]!r}")


_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "object": dict,
    "array": list,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
}


def check_schema(obj: dict[str, Any], schema: dict[str, Any]) -> None:
    """shallow check of required keys and top-level types; full validation is the caller's pydantic model."""
    missing = [k for k in schema.get("required", []) if k not in obj]
    if missing:
        raise MalformedOutput(f"missing keys: {missing}")
    for key, prop in schema.get("properties", {}).items():
        kind = prop.get("type") if isinstance(prop, dict) else None
        # union types like ["string", "null"] are left to the caller's model
        if key not in obj or not isinstance(kind, str) or kind not in _TYPES:
            continue
        value = obj[key]
        # json schema keeps booleans apart from numbers, python does not
        bad_bool = isinstance(value, bool) and kind in {"integer", "number"}
        if bad_bool or not isinstance(value, _TYPES[kind]):
            raise MalformedOutput(f"key {key!r} should be {kind}")


DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"


class GeminiJsonBackend:
    """adapts the metered GeminiBackend (p4) to Backend; all key and cap rules stay inside it."""

    name = "gemini"

    def __init__(self, gemini: Any, model: str = DEFAULT_GEMINI_MODEL) -> None:
        self.gemini = gemini
        self.model = model

    def _once(self, prompt: str, schema: dict[str, Any], max_output_tokens: int, tag: str) -> dict[str, Any]:
        res = self.gemini.generate(self.model, prompt, max_output_tokens=max_output_tokens, tag=tag)
        obj = extract_json(res.text)
        check_schema(obj, schema)
        return obj

    def generate_json(
        self, prompt: str, schema: dict[str, Any], max_output_tokens: int = 8192, tag: str = ""
    ) -> dict[str, Any]:
        full = f"{prompt}\n\nthe json object must follow this json schema:\n{json.dumps(schema)}"
        try:
            return self._once(full, schema, max_output_tokens, tag)
        except MalformedOutput as exc:
            retry = f"{full}\n\nyour previous reply was rejected: {exc}. reply with only the json object."
            return self._once(retry, schema, max_output_tokens, tag)


def get_backend(name: str, model: str | None = None) -> Backend:
    if name == "claude-code":
        from incidentforge.backends.claude_code import ClaudeCodeBackend

        return ClaudeCodeBackend(model=model)
    if name == "gemini":
        from incidentforge.backends.gemini import GeminiBackend

        return GeminiJsonBackend(GeminiBackend.from_env(), model or DEFAULT_GEMINI_MODEL)
    raise ValueError(f"unknown backend {name!r}; use claude-code or gemini")
