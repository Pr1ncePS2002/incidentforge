"""text mutation operators for go sources; mutate only lines the reference patch added."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator

Mutant = tuple[str, int, str]

_COMPARISONS = {"<=": ">", ">=": "<", "==": "!=", "!=": "==", "<": ">=", ">": "<="}
_COMPARE_RE = re.compile(r"<=|>=|==|!=|<-|<<|>>|->|:=|<|>")
_IF_RE = re.compile(r"^(?P<lead>\s*(?:\}\s*else\s+)?if\s+)(?P<cond>.+?)\s*\{\s*$")
_RETURN_RE = re.compile(r"^(?P<lead>\s*return\s+)(?P<exprs>.+?)\s*$")
_ERR_EXPR = re.compile(r"\b(fmt\.Errorf|errors\.(New|Join)|err)\b")
_APPEND_RE = re.compile(r"^\s*\w+(\.\w+)*\s*=\s*append\(")
_INCDEC_RE = re.compile(r"^\s*[\w.\[\]]+\s*(\+\+|--)\s*$")


def _code_spans(line: str) -> Iterator[tuple[int, int]]:
    """(start, end) of runs outside string/rune literals, stopping at a line comment."""
    i, start, n = 0, 0, len(line)
    while i < n:
        c = line[i]
        if c == "/" and line.startswith("//", i):
            break
        if c in "\"'`":
            yield start, i
            i += 1
            while i < n and line[i] != c:
                i += 2 if line[i] == "\\" and c != "`" else 1
            start = i + 1
        i += 1
    yield start, min(i, n)


def _split_top(exprs: str) -> list[str]:
    """split a return list on commas outside brackets and literals."""
    parts, depth, cur, quote = [], 0, "", ""
    for c in exprs:
        if quote:
            cur += c
            quote = "" if c == quote else quote
            continue
        if c in "\"'`":
            quote = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
            continue
        cur += c
    parts.append(cur.strip())
    return parts


def flip_comparison(line: str) -> str | None:
    for start, end in _code_spans(line):
        for m in _COMPARE_RE.finditer(line, start, end):
            if m.group() in _COMPARISONS:
                return line[: m.start()] + _COMPARISONS[m.group()] + line[m.end() :]
    return None


def flip_logical(line: str) -> str | None:
    for start, end in _code_spans(line):
        for op, new in (("&&", "||"), ("||", "&&")):
            at = line.find(op, start, end)
            if at >= 0:
                return line[:at] + new + line[at + 2 :]
    return None


def negate_if(line: str) -> str | None:
    m = _IF_RE.match(line)
    # an init statement may declare a var used only by the condition, so leave those alone
    if not m or ";" in m.group("cond"):
        return None
    return f"{m.group('lead')}!({m.group('cond')}) {{"


def disable_if(line: str) -> str | None:
    m = _IF_RE.match(line)
    if not m or ";" in m.group("cond") or m.group("lead").lstrip().startswith("}"):
        return None
    return f"{m.group('lead')}false {{"


def drop_error_return(line: str) -> str | None:
    m = _RETURN_RE.match(line)
    if not m:
        return None
    parts = _split_top(m.group("exprs"))
    if parts[-1] == "nil" or not _ERR_EXPR.search(parts[-1]):
        return None
    return m.group("lead") + ", ".join([*parts[:-1], "nil"])


def drop_statement(line: str) -> str | None:
    # appends and counters are safe to drop: the target stays declared and used elsewhere
    if _APPEND_RE.match(line) or _INCDEC_RE.match(line):
        indent = line[: len(line) - len(line.lstrip())]
        return f"{indent}// mutant: statement removed"
    return None


OPERATORS: dict[str, Callable[[str], str | None]] = {
    "flip-comparison": flip_comparison,
    "flip-logical": flip_logical,
    "negate-if": negate_if,
    "disable-if": disable_if,
    "drop-error-return": drop_error_return,
    "drop-statement": drop_statement,
}


def go_mutants(src: str, added: set[int]) -> list[Mutant]:
    """one mutant per (operator, added line) that changes the line; order is by line then operator."""
    lines = src.split("\n")
    out: list[Mutant] = []
    for lineno in sorted(added):
        if not 1 <= lineno <= len(lines):
            continue
        line = lines[lineno - 1]
        if not line.strip() or line.lstrip().startswith("//"):
            continue
        for name, op in OPERATORS.items():
            new = op(line)
            if new is not None and new != line:
                mutated = [*lines[: lineno - 1], new, *lines[lineno:]]
                out.append((name, lineno, "\n".join(mutated)))
    return out
