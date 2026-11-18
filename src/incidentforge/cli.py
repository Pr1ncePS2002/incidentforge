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
    from incidentforge.evaluate import discover_tasks, pick_subset, run_eval

    root = Path(tasks)
    picked = pick_subset(discover_tasks(root), subset) if subset else None
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


if __name__ == "__main__":
    app()
