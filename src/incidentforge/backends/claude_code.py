"""generator backend over headless claude code (`claude -p`). owner: phase 2."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from incidentforge.backends.base import MalformedOutput, check_schema, extract_json

Runner = Callable[[list[str], str, float, str, dict[str, str]], "subprocess.CompletedProcess[str]"]


def _run(cmd: list[str], stdin: str, timeout: float, cwd: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, input=stdin, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env, check=False
    )


class ClaudeCodeError(RuntimeError):
    """claude exited badly or reported an error envelope."""


@dataclass
class ClaudeCodeBackend:
    """uses the local claude login, so no api key is needed."""

    model: str | None = None
    timeout: float = 600.0
    binary: str = "claude"
    runner: Runner = _run
    name: str = "claude-code"
    cost_usd: float = 0.0  # running total reported by the cli, for logging only
    calls: list[dict[str, Any]] = field(default_factory=list)

    def command(self, schema: dict[str, Any]) -> list[str]:
        # no tools, no user settings or mcp servers: the prompt carries all context and nothing private leaks in
        cmd = [self.binary, "-p", "--output-format", "json", "--json-schema", json.dumps(schema)]
        cmd += ["--tools", "", "--strict-mcp-config", "--setting-sources", "project"]
        if self.model:
            cmd += ["--model", self.model]
        return cmd

    def _once(self, prompt: str, schema: dict[str, Any], max_output_tokens: int, tag: str) -> dict[str, Any]:
        # the cli has no flag for the output cap, only this env var
        env = {**os.environ, "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(max_output_tokens)}
        with tempfile.TemporaryDirectory(prefix="forge-claude-") as cwd:
            try:
                proc = self.runner(self.command(schema), prompt, self.timeout, cwd, env)
            except subprocess.TimeoutExpired as exc:
                raise ClaudeCodeError(f"claude timed out after {self.timeout}s") from exc
        try:
            env = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise ClaudeCodeError(f"claude exit {proc.returncode}: {(proc.stderr or proc.stdout)[:300]}") from exc
        cost = float(env.get("total_cost_usd") or 0.0)
        self.cost_usd += cost
        self.calls.append({"tag": tag, "cost_usd": cost, "duration_ms": env.get("duration_ms")})
        if env.get("is_error") or proc.returncode != 0:
            raise ClaudeCodeError(f"claude error: {str(env.get('result', ''))[:300]}")
        out = env.get("structured_output")
        obj = out if isinstance(out, dict) else extract_json(str(env.get("result", "")))
        check_schema(obj, schema)
        return obj

    def generate_json(
        self, prompt: str, schema: dict[str, Any], max_output_tokens: int = 8192, tag: str = ""
    ) -> dict[str, Any]:
        """one retry on malformed json, with the parse error appended so the model can correct it."""
        try:
            return self._once(prompt, schema, max_output_tokens, tag)
        except MalformedOutput as exc:
            retry = f"{prompt}\n\nyour previous reply was rejected: {exc}. reply with only the json object."
            return self._once(retry, schema, max_output_tokens, tag)
