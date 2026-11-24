import os
from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from incidentforge.backends.base import Backend

app = typer.Typer(help="incidentforge coding task factory", no_args_is_help=True)
BACKEND_HELP = (
    "claude-code | codex | opencode | gemini-cli | command | gemini | auto; the clis use their own login, "
    "auto = first of claude, codex, opencode, gemini on PATH"
)
COMMAND_HELP = (
    "for --backend command: shell-style command, prompt on stdin or {prompt_file}; "
    "also {schema_file}, {model}; default env FORGE_GEN_COMMAND"
)


def _backend(name: str, model: str | None, command: str | None) -> "Backend":
    from incidentforge.backends.base import get_backend

    try:
        return get_backend(name, model, command)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--backend") from exc


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
    backend: str = typer.Option("claude-code", help=BACKEND_HELP),
    model: str = typer.Option(None, help="backend model override (opencode wants provider/model)"),
    backend_command: str = typer.Option(None, help=COMMAND_HELP),
    out: str = typer.Option("tasks", help="tasks root dir"),
    workers: int = typer.Option(1, help="parallel workers, one per failure-map cluster; 1 = single-worker path"),
    max_containers: int = typer.Option(4, help="docker containers shared by all workers (workers > 1 only)"),
    skip_file: list[str] = typer.Option(None, help="workers > 1: leave clusters holding this repo file alone"),
    peer_tasks: list[str] = typer.Option(None, help="workers > 1: other tasks roots whose titles and ids count"),
) -> None:
    """generate, validate and keep tasks for a target. owner: phase 2."""
    from pathlib import Path

    from incidentforge.families import list_families
    from incidentforge.families.sampling import pick_families
    from incidentforge.generate import generate
    from incidentforge.targets import load_target

    tgt = load_target(target)
    be = _backend(backend, model, backend_command)
    # weighted mix decides the family order; generate round-robins so each family gets a turn
    slugs = list(dict.fromkeys(family or pick_families(max(n, 8), available=list_families())))
    map_path = Path("work") / target / "map.sqlite"
    if workers > 1 and map_path.exists():
        from incidentforge.parallel import run_parallel

        reports = run_parallel(
            tgt,
            slugs,
            n,
            be,
            map_path=map_path,
            workers=workers,
            max_containers=max_containers,
            tasks_root=Path(out),
            skip_files=tuple(skip_file or ()),
            peers=tuple(Path(p) for p in peer_tasks or ()),
            log=typer.echo,
        )
    else:
        if workers > 1:
            typer.echo(f"no failure map at {map_path} (run `forge map build --target {target}`); using one worker")
        reports = generate(tgt, slugs, n, be, tasks_root=Path(out), log=typer.echo)
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


@app.command()
def rerender(
    task_dirs: list[str] = typer.Argument(..., help="task dirs or a tasks root"),
    nop_job: list[str] = typer.Option(
        [], help="harbor nop job dir(s); feature tests that passed there move from fail_to_pass to pass_to_pass"
    ),
) -> None:
    """rewrite committed tasks in the current package format (test.sh, test id lists, task.toml); content stays."""
    from pathlib import Path

    from incidentforge.harbor import read_trials
    from incidentforge.package import rerender_task, spec_from_task_dir
    from incidentforge.targets import load_target
    from incidentforge.validate import find_task_dirs, passed_on_base, task_target

    trials = {t.task_name: t for job in nop_job for t in read_trials(Path(job)) if not t.error}
    for d in find_task_dirs([Path(p) for p in task_dirs]):
        target = load_target(task_target(d))
        trial = trials.get(d.name)
        moved = passed_on_base(trial, d) if trial else []
        guards = [*spec_from_task_dir(d, target).guards, *moved]
        rerender_task(d, target, guards=guards)
        typer.echo(f"rewrote {d}" + (f" ({len(moved)} base-passing test(s) moved to pass_to_pass)" if moved else ""))


@app.command(name="eval")
def eval_(
    tasks: str = typer.Option("tasks", help="tasks root"),
    model: list[str] = typer.Option(None, help="model ids, e.g. gemini/gemini-3.8-flash"),
    agent: str = typer.Option(
        "terminus-2",
        help="terminus-2 (gemini keys) or a login cli: claude-code, codex, gemini-cli, opencode, cursor-cli",
    ),
    k: int = typer.Option(1, help="attempts per task"),
    subset: int = typer.Option(None, help="only a fixed seeded subset of this many tasks (>=1 per family)"),
    only: list[str] = typer.Option(
        None, help="task ids or dataset prefixes to run, e.g. click/ (ids stay relative to --tasks)"
    ),
) -> None:
    """evaluate models on the dataset with the paid-key cap enforced. owner: phase 4."""
    from pathlib import Path

    from incidentforge.backends.gemini import load_env
    from incidentforge.evaluate import SUBSCRIPTION_AGENTS, discover_tasks, frozen_subset, run_eval, select_tasks

    root = Path(tasks)
    if subset and only:
        raise typer.BadParameter("--subset and --only don't combine")
    picked = frozen_subset(root, subset) if subset else None
    if only:
        picked = select_tasks(discover_tasks(root), only)
        if not picked:
            raise typer.BadParameter(f"no task under {root} matches {only}")
    # a login agent with no --model runs its own default model
    models = model or ([agent] if agent in SUBSCRIPTION_AGENTS else ["gemini/gemini-3.8-flash"])
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


@app.command("from-postmortem")
def from_postmortem_cmd(
    source: str = typer.Argument(..., help="public postmortem url, or a local copy with --source-url"),
    target: str = typer.Option(..., help="target name under incidentforge/targets"),
    source_url: str = typer.Option(None, help="public url of the report; required for a local file"),
    backend: str = typer.Option("claude-code", help=BACKEND_HELP),
    model: str = typer.Option(None, help="backend model override"),
    backend_command: str = typer.Option(None, help=COMMAND_HELP),
    tries: int = typer.Option(2, help="surfaces to try in rank order before giving up"),
    family: str = typer.Option(None, help="use this family even if the classifier picks another (logged)"),
    out: str = typer.Option("tasks", help="tasks root dir"),
) -> None:
    """turn a public incident report into one validated task with source_url set. owner: v2-postmortem."""
    from pathlib import Path

    from incidentforge.postmortem import NoFamilyFits, PostmortemError, from_postmortem
    from incidentforge.targets import load_target

    try:
        res = from_postmortem(
            source,
            load_target(target),
            _backend(backend, model, backend_command),
            source_url=source_url,
            tasks_root=Path(out),
            tries=tries,
            family=family,
            log=typer.echo,
        )
    except NoFamilyFits as exc:
        typer.echo(f"refused: {exc}")
        raise typer.Exit(3) from exc
    except PostmortemError as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(2) from exc
    ok = res.accepted
    if ok is None:
        typer.echo(f"no task accepted for {res.postmortem.source_url}")
        raise typer.Exit(1)
    note = "" if res.classifier_family == res.classification.family else f", classifier said {res.classifier_family}"
    typer.echo(f"accepted {ok.task_id} ({res.classification.family}{note}) from {res.postmortem.source_url}")


map_app = typer.Typer(help="failure map of a target repo", no_args_is_help=True)
app.add_typer(map_app, name="map")


@map_app.command("build")
def map_build(
    target: str = typer.Option(..., help="target name under incidentforge/targets, or a new name with --repo-url"),
    repo_url: str = typer.Option(None, help="unseen repo: clone url (target yaml not needed)"),
    commit: str = typer.Option(None, help="unseen repo: commit to pin"),
    language: str = typer.Option(None, help="unseen repo: python | go"),
    source_root: str = typer.Option(".", help="unseen repo: package dir inside the repo"),
    licence: str = typer.Option("unknown", help="unseen repo: spdx licence id"),
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
            licence=licence,
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


@map_app.command("backfill")
def map_backfill(
    tasks: str = typer.Option("tasks", help="tasks root"),
    work: str = typer.Option("work", help="work root holding <target>/map.sqlite"),
) -> None:
    """add map node, blast radius, fix scope and fault-based difficulty to existing tasks. owner: lead."""
    from pathlib import Path

    from incidentforge.failmap.backfill import backfill

    for b in backfill(Path(tasks), Path(work)):
        typer.echo(f"{b.task_id}\t{b.difficulty}\t{b.fix_scope or '-'}\t{b.map_node or '-'}")


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
