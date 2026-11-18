"""leak gate: the instruction must not hand the agent the reference solution."""

from __future__ import annotations

import re

MIN_LINE_CHARS = 25
NGRAM = 8
MAX_NGRAM_SHARE = 0.30
_TOKEN = re.compile(r"\w+|[^\w\s]")


def added_lines(patch: str) -> list[str]:
    return [line[1:] for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++")]


def _ngrams(text: str) -> set[tuple[str, ...]]:
    toks = _TOKEN.findall(text)
    return {tuple(toks[i : i + NGRAM]) for i in range(len(toks) - NGRAM + 1)}


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def check_leak(instruction: str, patch: str) -> tuple[bool, str]:
    """return (passed, detail); fails on a copied code line or a high 8-gram overlap."""
    added = added_lines(patch)
    flat = _squash(instruction)
    for line in added:
        code = _squash(line)
        if len(code) >= MIN_LINE_CHARS and code in flat:
            return False, f"instruction contains patch line: {code[:80]!r}"
    patch_grams = _ngrams("\n".join(added))
    if not patch_grams:
        return True, "no 8-grams in patch"
    share = len(patch_grams & _ngrams(instruction)) / len(patch_grams)
    if share >= MAX_NGRAM_SHARE:
        return False, f"{share:.0%} of patch 8-grams appear in the instruction"
    return True, f"{share:.0%} 8-gram overlap"
