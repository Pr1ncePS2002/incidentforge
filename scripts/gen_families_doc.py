"""regenerate docs/families.md from family.yaml, taxonomy weights and accepted tasks, so the doc never drifts."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

from incidentforge.families import CORE, EXTENDED, FAMILIES_DIR, load_family

ROOT = Path(__file__).resolve().parent.parent
HEADER = """# Task families

Each family is a recurring production failure class seen across a large e-commerce microservice fleet,
rewritten as a feature request: "add the protection that would have prevented this outage". Definitions live
in `src/incidentforge/families/<slug>/` (`family.yaml` + `prompt.md`); this page is generated from them by
`uv run python scripts/gen_families_doc.py`.

`forge run` without `--family` samples families by the share of incidents each class accounts for
(`families/taxonomy.json`), so the dataset mix follows production reality rather than being uniform.
"""


def accepted_tasks(tasks_root: Path, reports_root: Path) -> dict[str, list[str]]:
    """family slug -> task dirs whose validation report says accepted."""
    out: dict[str, list[str]] = {}
    for toml_path in sorted(tasks_root.glob("*/*/task.toml")):
        task_dir = toml_path.parent
        task_id = f"{task_dir.parent.name}/{task_dir.name}"
        report = reports_root / f"{task_id}.json"
        try:
            accepted = json.loads(report.read_text()).get("accepted", False)
            family = tomllib.loads(toml_path.read_text())["metadata"]["family"]
        except (OSError, ValueError, KeyError):
            continue
        if accepted:
            out.setdefault(family, []).append(task_id)
    return out


def render(root: Path = ROOT) -> str:
    weights = json.loads((FAMILIES_DIR / "taxonomy.json").read_text())
    samples = accepted_tasks(root / "tasks", root / "reports" / "validation")
    parts = [HEADER]
    for i, slug in enumerate((*CORE, *EXTENDED), 1):
        parts.append(f"## {i}. {slug}\n")
        if not (FAMILIES_DIR / slug / "family.yaml").exists():
            parts.append("_definition not landed yet._\n")
            continue
        fam = load_family(slug)
        share = weights.get(slug)
        parts.append(f"**{fam.title}.** {fam.intent}\n")
        meta = f"Attaches to: {', '.join(f'`{k}`' for k in fam.surface_kinds)} · languages: {', '.join(fam.languages)}"
        if share is not None:
            meta += f" · sampling weight: {share:.0%}"
        parts.append(meta + "\n")
        parts.append("Injected faults:\n")
        parts.extend(f"- `{f.id}`: {f.description}" for f in fam.fault_catalogue)
        parts.append("\nExample: " + fam.examples[0] + "\n")
        tasks = samples.get(slug, [])
        if tasks:
            links = ", ".join(f"[`{t}`](../tasks/{t}/instruction.md)" for t in tasks[:3])
            parts.append(f"Accepted tasks ({len(tasks)}): {links}\n")
        else:
            parts.append("Accepted tasks: none yet.\n")
    return "\n".join(parts)


def main(out: str = "docs/families.md") -> None:
    Path(out).write_text(render())
    print(out)


if __name__ == "__main__":
    main(*sys.argv[1:])
