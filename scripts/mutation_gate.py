"""fail ci when a mutmut mutant survives that is not in the equivalent-mutant allowlist."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

NOT_KILLED = {"survived", "no tests", "not checked"}
ALLOWLIST = Path(__file__).resolve().parent.parent / "tests" / "mutation-allowlist.txt"


def parse_results(text: str) -> dict[str, str]:
    """`mutmut results --all true` lines look like `    <name>: <status>`."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        name, sep, state = line.strip().rpartition(": ")
        if sep and name:
            out[name] = state.strip()
    return out


def load_allowlist(text: str, platform: str) -> dict[str, str]:
    """`<mutant> <platform|any> <reason>` per line; entries for other platforms are ignored."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, plat, reason = [*line.split(None, 2), "", ""][:3]
        if not reason:
            raise ValueError(f"allowlist entry needs a platform and a reason: {raw!r}")
        if plat in ("any", platform):
            out[name] = reason
    return out


def evaluate(results: dict[str, str], allow: dict[str, str]) -> tuple[list[str], list[str], str]:
    """(unexpected survivors, allowlist entries that no longer survive, summary line)."""
    alive = sorted(n for n, s in results.items() if s in NOT_KILLED)
    bad = [f"{n}: {results[n]}" for n in alive if n not in allow]
    stale = sorted(n for n in allow if n in results and results[n] not in NOT_KILLED)
    total = len(results)
    killed = total - len(alive)
    rate = killed / total if total else 0.0
    summary = f"mutants: {total}, killed {killed} ({rate:.1%}), allowlisted {len(alive) - len(bad)}, failing {len(bad)}"
    return bad, stale, summary


def main(argv: list[str]) -> int:
    # optional arg: a saved `mutmut results --all true` output instead of asking mutmut
    if argv:
        text = Path(argv[0]).read_text()
    else:
        cmd = ["mutmut", "results", "--all", "true"]
        text = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    results = parse_results(text)
    if not results:
        print("::error::no mutmut results found")
        return 1
    bad, stale, summary = evaluate(results, load_allowlist(ALLOWLIST.read_text(), sys.platform))
    for name in bad:
        print(f"::error::mutant not killed: {name} (see `mutmut show {name.split(':')[0]}`)")
    for name in stale:
        print(f"::warning::allowlisted mutant is now killed, drop it from the allowlist: {name}")
    print(summary)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
