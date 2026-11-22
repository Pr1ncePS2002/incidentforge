"""render the pipeline and architecture diagrams as plain svg (stdlib only, so docs build anywhere)."""

from __future__ import annotations

import sys
from html import escape
from pathlib import Path

BLUE = "#1565c0"
ORANGE = "#e07b24"
INK = "#1f2933"
MUTED = "#52606d"
PALE_BLUE = "#e8f1fb"
PALE_ORANGE = "#fdf0e4"
FONT = "Helvetica, Arial, sans-serif"


def _box(x: float, y: float, w: float, h: float, title: str, sub: str = "", accent: str = BLUE) -> str:
    fill = PALE_ORANGE if accent == ORANGE else PALE_BLUE
    parts = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{accent}" stroke-width="2"/>',
        f'<text x="{x + w / 2}" y="{y + (h / 2 - 6 if sub else h / 2 + 5)}" text-anchor="middle" '
        f'font-size="15" font-weight="700" fill="{INK}">{escape(title)}</text>',
    ]
    for i, line in enumerate(sub.split("\n") if sub else []):
        parts.append(
            f'<text x="{x + w / 2}" y="{y + h / 2 + 14 + i * 15}" text-anchor="middle" '
            f'font-size="12" fill="{MUTED}">{escape(line)}</text>'
        )
    return "\n".join(parts)


def _arrow(x1: float, y1: float, x2: float, y2: float, label: str = "") -> str:
    out = f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{MUTED}" stroke-width="2" marker-end="url(#a)"/>'
    if label:
        out += (
            f'<text x="{(x1 + x2) / 2}" y="{(y1 + y2) / 2 - 7}" text-anchor="middle" '
            f'font-size="11" fill="{MUTED}">{escape(label)}</text>'
        )
    return out


def _svg(w: int, h: int, body: list[str]) -> str:
    head = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'font-family="{FONT}">\n<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" '
        f'markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{MUTED}"/>'
        f'</marker></defs>\n<rect width="{w}" height="{h}" fill="#ffffff"/>\n'
    )
    return head + "\n".join(body) + "\n</svg>\n"


def pipeline() -> str:
    """left-to-right flow: repo -> failure map -> generate -> gates -> package -> eval -> report."""
    w, h = 1200, 340
    bw, bh, y = 140, 78, 70
    steps = [
        ("target repo", "url + pinned\ncommit", BLUE),
        ("failure map", "code graph, family\ntags, untested risk", ORANGE),
        ("task generator", "one worker per\ncluster, in parallel", ORANGE),
        ("validation gates", "6 automatic\nchecks", ORANGE),
        ("harbor package", "instruction, tests,\nsolution, env", BLUE),
        ("evaluate", "models x tasks\nin docker", BLUE),
        ("report", "static html\n+ summary.json", BLUE),
    ]
    gap = (w - 40 - bw * len(steps)) / (len(steps) - 1)
    body: list[str] = []
    for i, (title, sub, accent) in enumerate(steps):
        x = 20 + i * (bw + gap)
        body.append(_box(x, y, bw, bh, title, sub, accent))
        if i:
            body.append(_arrow(x - gap + 2, y + bh / 2, x - 2, y + bh / 2))
    # rejected tasks get one retry with the failure reason fed back to the generator
    gx = 20 + 2 * (bw + gap)
    vx = 20 + 3 * (bw + gap)
    body.append(
        f'<path d="M{vx + bw / 2},{y + bh} C{vx + bw / 2},{y + bh + 70} {gx + bw / 2},{y + bh + 70} '
        f'{gx + bw / 2},{y + bh + 4}" fill="none" stroke="{ORANGE}" stroke-width="2" stroke-dasharray="6 4" '
        f'marker-end="url(#a)"/>'
    )
    body.append(
        f'<text x="{(gx + vx + bw) / 2}" y="{y + bh + 76}" text-anchor="middle" font-size="12" '
        f'fill="{ORANGE}">rejected: 1 retry with the failure reason</text>'
    )
    # a public postmortem enters through the map: its family picks the surface
    mx = 20 + 1 * (bw + gap)
    body.append(_box(mx, y + bh + 60, bw, 56, "postmortem", "public incident report", ORANGE))
    body.append(_arrow(mx + bw / 2, y + bh + 58, mx + bw / 2, y + bh + 2))
    gates = "fails on base · passes with reference · repo suite green · kills mutants · no leak · not flaky"
    body.append(
        f'<text x="{w / 2}" y="{h - 26}" text-anchor="middle" font-size="13" fill="{INK}">gates: {escape(gates)}</text>'
    )
    body.append(
        f'<text x="{w / 2}" y="34" text-anchor="middle" font-size="18" font-weight="700" fill="{INK}">'
        f"IncidentForge pipeline</text>"
    )
    return _svg(w, h, body)


def architecture() -> str:
    """module map: cli on top, core modules in the middle, external tools at the bottom."""
    w, h = 1400, 560
    body: list[str] = [
        f'<text x="{w / 2}" y="34" text-anchor="middle" font-size="18" font-weight="700" fill="{INK}">'
        f"IncidentForge architecture</text>"
    ]
    body.append(
        _box(
            (w - 520) / 2,
            56,
            520,
            60,
            "forge CLI (typer)",
            "run · validate · eval · report · map · from-postmortem",
        )
    )
    row = [
        ("targets/", "repo + commit +\nenv template"),
        ("surfaces/", "python + go\nsurface finders"),
        ("failmap/", "graph, tags, radius,\nclusters, coverage"),
        ("families/", "8 failure-class\nprompts + sampling"),
        ("generate.py", "backend call,\n1 retry on reject"),
        ("validate/", "6 gates +\nmutation"),
        ("package.py", "harbor task\nwriter"),
    ]
    bw, gap, y = 170, 22, 170
    x0 = (w - (bw * len(row) + gap * (len(row) - 1))) / 2
    for i, (title, sub) in enumerate(row):
        x = x0 + i * (bw + gap)
        accent = ORANGE if title in ("families/", "failmap/", "validate/") else BLUE
        body.append(_box(x, y, bw, 80, title, sub, accent))
        body.append(_arrow(w / 2, 116, x + bw / 2, y - 2))
    row2 = [
        ("backends/", "claude code headless,\ngemini api"),
        ("harbor.py", "run jobs,\nread rewards"),
        ("evaluate.py", "models x tasks,\ncap check per batch"),
        ("report.py", "static html +\nsummary.json"),
        ("parallel.py", "workers, docker\nslots, id merge"),
        ("postmortem.py", "incident report\n-> family + trigger"),
        ("map_render.py", "offline d3\nfailure map page"),
    ]
    bw2, y2 = 150, 310
    x02 = (w - (bw2 * len(row2) + gap * (len(row2) - 1))) / 2
    for i, (title, sub) in enumerate(row2):
        body.append(_box(x02 + i * (bw2 + gap), y2, bw2, 80, title, sub))
    ext = [
        ("Claude Code CLI", "task generation"),
        ("Gemini API", "generation + eval"),
        ("Harbor", "docker task runner"),
        ("Docker", "target images"),
        ("code-review-graph", "base code graph"),
    ]
    bw3, y3 = 220, 450
    x03 = (w - (bw3 * len(ext) + gap * (len(ext) - 1))) / 2
    for i, (title, sub) in enumerate(ext):
        x = x03 + i * (bw3 + gap)
        body.append(
            f'<rect x="{x}" y="{y3}" width="{bw3}" height="64" rx="10" fill="#f5f7fa" stroke="{MUTED}" '
            f'stroke-width="1.5" stroke-dasharray="5 4"/>'
        )
        body.append(
            f'<text x="{x + bw3 / 2}" y="{y3 + 28}" text-anchor="middle" font-size="15" font-weight="700" '
            f'fill="{INK}">{escape(title)}</text>'
        )
        body.append(
            f'<text x="{x + bw3 / 2}" y="{y3 + 47}" text-anchor="middle" font-size="12" '
            f'fill="{MUTED}">{escape(sub)}</text>'
        )
    body.append(
        f'<text x="20" y="{y3 - 14}" font-size="12" fill="{MUTED}">external tools (dashed) · '
        f"orange = where the failure-class knowledge lives</text>"
    )
    return _svg(w, h, body)


def main(out_dir: str = "docs/img") -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, render in (("pipeline", pipeline), ("architecture", architecture)):
        path = out / f"{name}.svg"
        path.write_text(render())
        print(path)


if __name__ == "__main__":
    main(*sys.argv[1:])
