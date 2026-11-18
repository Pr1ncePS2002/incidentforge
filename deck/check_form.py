"""count the characters of each form answer in deck/form.md against the 1024 limit."""

from __future__ import annotations

import sys
from pathlib import Path

LIMIT = 1024


def sections(text: str) -> dict[str, str]:
    out: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            out[current] = []
        elif current is not None:
            out[current].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def main(path: str = "deck/form.md") -> None:
    failed = False
    for name, body in sections(Path(path).read_text()).items():
        n = len(body)
        failed |= n > LIMIT
        print(f"{name}: {n}/{LIMIT} {'OVER' if n > LIMIT else 'ok'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(*sys.argv[1:])
