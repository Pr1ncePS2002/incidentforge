"""generator backends over coding clis that are already logged in (codex, opencode, gemini-cli, any command)."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from incidentforge.backends.base import MalformedOutput, check_schema, extract_json
from incidentforge.backends.claude_code import Runner, _run

# schema goes in the prompt: not every cli has a schema flag, and codex's strict one rejects free-form maps
SCHEMA_NOTE = "\n\nreply with only one json object, no prose around it. it must follow this json schema:\n"


class CliBackendError(RuntimeError):
    """the cli was missing, timed out, exited badly or reported an error."""


def _tail(proc: subprocess.CompletedProcess[str]) -> str:
    return (proc.stderr or proc.stdout or "").strip()[-300:]


@dataclass
class CliBackend:
    """runs one cli call per attempt in an empty temp dir, so the prompt carries all context."""

    model: str | None = None
    timeout: float = 600.0
    runner: Runner = _run
    binary: str = ""
    name: str = ""
    calls: list[dict[str, Any]] = field(default_factory=list)

    def command(self, cwd: str) -> list[str]:
        raise NotImplementedError

    def environ(self, max_output_tokens: int) -> dict[str, str]:
        return dict(os.environ)

    def prepare(self, prompt: str, schema: dict[str, Any], cwd: str) -> tuple[list[str], str]:
        """command line and stdin for one call."""
        return self.command(cwd), prompt

    def answer(self, proc: subprocess.CompletedProcess[str], cwd: str) -> str:
        """the model's final text out of a finished call."""
        if proc.returncode != 0:
            raise CliBackendError(f"{self.name} exit {proc.returncode}: {_tail(proc)}")
        return proc.stdout

    def _once(self, prompt: str, schema: dict[str, Any], max_output_tokens: int, tag: str) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix=f"forge-{self.name}-") as cwd:
            cmd, stdin = self.prepare(prompt, schema, cwd)
            try:
                proc = self.runner(cmd, stdin, self.timeout, cwd, self.environ(max_output_tokens))
            except subprocess.TimeoutExpired as exc:
                raise CliBackendError(f"{self.name} timed out after {self.timeout}s") from exc
            except FileNotFoundError as exc:
                raise CliBackendError(f"{cmd[0]} not found on PATH") from exc
            self.calls.append({"tag": tag, "returncode": proc.returncode})
            text = self.answer(proc, cwd)
        obj = extract_json(text)
        check_schema(obj, schema)
        return obj

    def generate_json(
        self, prompt: str, schema: dict[str, Any], max_output_tokens: int = 8192, tag: str = ""
    ) -> dict[str, Any]:
        """one retry on malformed json, with the parse error appended so the model can correct it."""
        full = prompt + SCHEMA_NOTE + json.dumps(schema)
        try:
            return self._once(full, schema, max_output_tokens, tag)
        except MalformedOutput as exc:
            retry = f"{full}\n\nyour previous reply was rejected: {exc}. reply with only the json object."
            return self._once(retry, schema, max_output_tokens, tag)


LAST_MESSAGE = "last-message.txt"


@dataclass
class CodexBackend(CliBackend):
    """`codex exec` on the local chatgpt or api login; read-only sandbox, never asks for approval."""

    binary: str = "codex"
    name: str = "codex"

    def command(self, cwd: str) -> list[str]:
        # no user config, profiles, mcp servers or exec rules: same isolation as claude-code's flags
        cmd = [self.binary, "exec", "--skip-git-repo-check", "--ephemeral", "--ignore-user-config", "--ignore-rules"]
        cmd += ["-s", "read-only", "-c", 'approval_policy="never"', "--color", "never"]
        cmd += ["-C", cwd, "-o", str(Path(cwd) / LAST_MESSAGE)]
        if self.model:
            cmd += ["-m", self.model]
        return [*cmd, "-"]

    def answer(self, proc: subprocess.CompletedProcess[str], cwd: str) -> str:
        text = super().answer(proc, cwd)
        last = Path(cwd) / LAST_MESSAGE
        # stdout carries the final message too, but -o is free of any progress lines
        return last.read_text() if last.exists() and last.read_text().strip() else text


# every tool denied and no sharing; opencode validates this and refuses unknown keys
OPENCODE_CONFIG = json.dumps({"permission": {"*": "deny"}, "share": "disabled"})


@dataclass
class OpenCodeBackend(CliBackend):
    """`opencode run` on whatever provider opencode is logged in to; model is provider/model."""

    binary: str = "opencode"
    name: str = "opencode"

    def command(self, cwd: str) -> list[str]:
        cmd = [self.binary, "run", "--pure", "--format", "json"]
        if self.model:
            cmd += ["-m", self.model]
        return cmd

    def environ(self, max_output_tokens: int) -> dict[str, str]:
        env = super().environ(max_output_tokens)
        env["OPENCODE_CONFIG_CONTENT"] = OPENCODE_CONFIG
        env["OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX"] = str(max_output_tokens)
        return env

    def answer(self, proc: subprocess.CompletedProcess[str], cwd: str) -> str:
        texts: list[str] = []
        for line in proc.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            # an error event is a failure even when the process exits 0
            if event.get("type") == "error":
                err = event.get("error") or {}
                msg = (err.get("data") or {}).get("message") or err.get("name") or "unknown error"
                raise CliBackendError(f"opencode error: {str(msg)[:300]}")
            if event.get("type") == "text":
                texts.append(str((event.get("part") or {}).get("text", "")))
        if proc.returncode != 0:
            raise CliBackendError(f"opencode exit {proc.returncode}: {_tail(proc)}")
        return "".join(texts) or proc.stdout


@dataclass
class GeminiCliBackend(CliBackend):
    """google's `gemini` cli in headless mode on its own login; prompt on stdin, json envelope out."""

    binary: str = "gemini"
    name: str = "gemini-cli"

    def command(self, cwd: str) -> list[str]:
        # -p is appended to stdin, so it only nudges; -e none keeps extensions out
        cmd = [self.binary, "--output-format", "json", "-e", "none", "-p", "answer with the json object only."]
        if self.model:
            cmd += ["-m", self.model]
        return cmd

    def answer(self, proc: subprocess.CompletedProcess[str], cwd: str) -> str:
        try:
            env = json.loads(proc.stdout)
        except json.JSONDecodeError:
            env = None
        if isinstance(env, dict) and env.get("error"):
            err = env["error"]
            msg = err.get("message", err) if isinstance(err, dict) else err
            raise CliBackendError(f"gemini-cli error: {str(msg)[:300]}")
        if proc.returncode != 0:
            raise CliBackendError(f"gemini-cli exit {proc.returncode}: {_tail(proc)}")
        if isinstance(env, dict) and isinstance(env.get("response"), str):
            return str(env["response"])
        return proc.stdout


PLACEHOLDERS = ("{prompt_file}", "{schema_file}", "{model}")


@dataclass
class CommandBackend(CliBackend):
    """any cli: FORGE_GEN_COMMAND or --backend-command, prompt on stdin unless {prompt_file} is used."""

    template: str = ""
    name: str = "command"

    def prepare(self, prompt: str, schema: dict[str, Any], cwd: str) -> tuple[list[str], str]:
        args = shlex.split(self.template)
        if not args:
            raise CliBackendError("command backend needs FORGE_GEN_COMMAND or --backend-command")
        prompt_file, schema_file = Path(cwd) / "prompt.txt", Path(cwd) / "schema.json"
        prompt_file.write_text(prompt)
        schema_file.write_text(json.dumps(schema))
        values = dict(zip(PLACEHOLDERS, (str(prompt_file), str(schema_file), self.model or ""), strict=True))
        uses_file = any("{prompt_file}" in a for a in args)
        for key, value in values.items():
            args = [a.replace(key, value) for a in args]
        return args, "" if uses_file else prompt
