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
def budget(
    runs_left: int = typer.Option(None, help="evaluation runs still to do on the paid key"),
    per_run_usd: float = typer.Option(None, help="estimated cost of one run"),
) -> None:
    """show paid-key spend against the hard cap and whether the remaining eval fits."""
    from incidentforge.budget import Ledger, render, status

    typer.echo(render(status(Ledger.default(), runs_left, per_run_usd)))


if __name__ == "__main__":
    app()
