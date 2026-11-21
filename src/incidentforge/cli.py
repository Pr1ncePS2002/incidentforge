import os

import typer

app = typer.Typer(help="incidentforge coding task factory", no_args_is_help=True)


@app.callback()
def main() -> None:
    """incidentforge coding task factory."""


@app.command()
def version() -> None:
    """print the installed version."""
    from importlib.metadata import version as v

    typer.echo(v("incidentforge"))


@app.command()
def run(
    target: str = typer.Option("fastapi-template", help="target name under incidentforge/targets"),
    family: list[str] = typer.Option(None, help="family slug(s); default = frequency-weighted mix"),
    n: int = typer.Option(5, help="tasks to accept"),
    backend: str = typer.Option("claude-code", help="claude-code | gemini"),
    out: str = typer.Option("tasks", help="tasks root dir"),
) -> None:
    """generate, validate and keep tasks for a target. owner: phase 2."""
    from pathlib import Path

    from incidentforge.backends.base import get_backend
    from incidentforge.families import list_families
    from incidentforge.families.sampling import pick_families
    from incidentforge.generate import generate
    from incidentforge.targets import load_target

    tgt = load_target(target)
    # weighted mix decides the family order; generate round-robins so each family gets a turn
    slugs = list(dict.fromkeys(family or pick_families(max(n, 8), available=list_families())))
    reports = generate(tgt, slugs, n, get_backend(backend), tasks_root=Path(out), log=typer.echo)
    kept = sum(r.accepted for r in reports)
    if kept < n:
        typer.echo(f"only {kept}/{n} tasks accepted")
        raise typer.Exit(1)


@app.command()
def validate(task_dirs: list[str] = typer.Argument(..., help="task dirs or a tasks root")) -> None:
    """run all validation gates and write reports/validation/<task>.json. owner: phase 1."""
    from pathlib import Path

    from incidentforge.validate import find_task_dirs, validate_task

    dirs = find_task_dirs([Path(d) for d in task_dirs])
    if not dirs:
        typer.echo("no task dirs found")
        raise typer.Exit(1)
    rejected = 0
    typer.echo(f"{'task':<50} {'result':<9} {'mutants':<8} detail")
    for d in dirs:
        r = validate_task(d)
        last = r.gates[-1] if r.gates else None
        detail = "" if r.accepted or last is None else f"{last.gate}: {last.detail}"
        rejected += not r.accepted
        verdict = "accepted" if r.accepted else "rejected"
        typer.echo(f"{r.task_id:<50} {verdict:<9} {f'{r.mutants_killed}/{r.mutants_total}':<8} {detail[:120]}")
    typer.echo(f"{len(dirs) - rejected}/{len(dirs)} accepted")
    if rejected:
        raise typer.Exit(1)


@app.command(name="eval")
def eval_(
    tasks: str = typer.Option("tasks", help="tasks root"),
    model: list[str] = typer.Option(None, help="model ids, e.g. gemini/gemini-3.8-flash"),
    agent: str = typer.Option("terminus-2", help="harbor agent"),
    k: int = typer.Option(1, help="attempts per task"),
    subset: int = typer.Option(None, help="only a fixed seeded subset of this many tasks (>=1 per family)"),
) -> None:
    """evaluate models on the dataset with the paid-key cap enforced. owner: phase 4."""
    from pathlib import Path

    from incidentforge.backends.gemini import load_env
    from incidentforge.evaluate import frozen_subset, run_eval

    root = Path(tasks)
    picked = frozen_subset(root, subset) if subset else None
    models = model or ["gemini/gemini-3.8-flash"]
    # keys come from .env unless already exported; harbor only ever sees the routed one
    env = {**load_env(".env"), **os.environ}
    new = run_eval(root, models, agent, k, picked, env=env, echo=typer.echo)
    typer.echo(f"recorded {len(new)} new result(s) in reports/eval/results.jsonl")


@app.command()
def report(out: str = typer.Option("reports/index.html")) -> None:
    """build the static html report. owner: phase 4."""
    from pathlib import Path

    from incidentforge.report import build

    typer.echo(f"wrote {build(Path(out))}")


@app.command()
def budget(
    runs_left: int = typer.Option(None, help="evaluation runs still to do on the paid key"),
    per_run_usd: float = typer.Option(None, help="estimated cost of one run"),
) -> None:
    """show paid-key spend against the hard cap and whether the remaining eval fits."""
    from incidentforge.budget import Ledger, render, status

    typer.echo(render(status(Ledger.default(), runs_left, per_run_usd)))


map_app = typer.Typer(help="failure map of a target repo", no_args_is_help=True)
app.add_typer(map_app, name="map")


@map_app.command("build")
def map_build(
    target: str = typer.Option(..., help="target name under incidentforge/targets, or a new name with --repo-url"),
    repo_url: str = typer.Option(None, help="unseen repo: clone url (target yaml not needed)"),
    commit: str = typer.Option(None, help="unseen repo: commit to pin"),
    language: str = typer.Option(None, help="unseen repo: python | go"),
    source_root: str = typer.Option(".", help="unseen repo: package dir inside the repo"),
    coverage: bool = typer.Option(False, help="run the suite once with coverage in the target image if not cached"),
    image: str = typer.Option(None, help="docker image for the coverage run"),
    work: str = typer.Option("work", help="work root; outputs go to <work>/<target>/"),
) -> None:
    """build work/<target>/map.sqlite and map.json. owner: v2-map."""
    from pathlib import Path

    from incidentforge.failmap.pipeline import build_map
    from incidentforge.generate import checkout
    from incidentforge.models import Language, Target
    from incidentforge.targets import TARGETS_DIR, load_target

    if repo_url:
        if not commit or not language:
            typer.echo("--repo-url needs --commit and --language")
            raise typer.Exit(2)
        tgt = Target(
            name=target,
            repo_url=repo_url,
            commit=commit,
            language=Language(language),
            env_template=Path("."),
            test_command="",
            source_root=source_root,
        )
    elif (TARGETS_DIR / f"{target}.yaml").exists():
        tgt = load_target(target)
    else:
        typer.echo(f"unknown target {target}; pass --repo-url/--commit/--language for an unseen repo")
        raise typer.Exit(2)
    root = Path(work)
    s = build_map(tgt, checkout(tgt, root), root, run_coverage=coverage, image=image)
    typer.echo(f"map {s.map_path} json {s.json_path}")
    typer.echo(f"graph_hash {s.graph_hash}")
    typer.echo(f"nodes {s.nodes} edges {s.edges} tagged {s.tagged} clusters {s.clusters} coverage {s.coverage}")
    typer.echo("timings " + " ".join(f"{k}={v}s" for k, v in s.timings.items()))


@map_app.command("render")
def map_render(
    target: list[str] = typer.Option(..., help="target name(s); reads work/<target>/map.json"),
    work: str = typer.Option("work", help="dir holding <target>/map.json"),
    reports: str = typer.Option("reports", help="reports root; writes map.html and map/<target>.json"),
    tasks: str = typer.Option("tasks", help="tasks root, for tasks whose metadata names a map node"),
    png: str = typer.Option(None, help="also save a static png of the map here (needs chrome)"),
) -> None:
    """render reports/map.html from the failure map. owner: v2-viz."""
    import subprocess
    from pathlib import Path

    from incidentforge import map_render as mr

    page = None
    for name in target:
        try:
            page = mr.build(name, Path(work), Path(reports), Path(tasks))
        except FileNotFoundError as e:
            typer.echo(str(e))
            raise typer.Exit(1) from None
    typer.echo(f"wrote {page}")
    if png and page:
        try:
            typer.echo(f"wrote {mr.export_png(page, Path(png))}")
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            typer.echo(f"png export failed: {e}")
            raise typer.Exit(1) from None


if __name__ == "__main__":
    app()
