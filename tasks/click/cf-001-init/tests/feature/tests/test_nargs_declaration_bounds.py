import pytest

import click


def test_fault_negative_or_zero_option_constructor():
    with pytest.raises(ValueError) as exc_info:
        click.Option(["--pairs"], nargs=-2)
    msg = str(exc_info.value)
    assert "nargs" in msg
    assert "-2" in msg


def test_fault_negative_or_zero_argument_decorator():
    with pytest.raises(ValueError) as exc_info:

        @click.command()
        @click.argument("files", nargs=-3)
        def cli(files):
            pass

    msg = str(exc_info.value)
    assert "nargs" in msg
    assert "-3" in msg


def test_fault_mutually_exclusive_option_constructor():
    with pytest.raises(ValueError) as exc_info:
        click.Option(["--item"], multiple=True, nargs=-1)
    msg = str(exc_info.value)
    assert "multiple" in msg
    assert "nargs" in msg


def test_fault_mutually_exclusive_option_decorator():
    with pytest.raises(ValueError) as exc_info:

        @click.command()
        @click.option("--item", multiple=True, nargs=-1)
        def cli(item):
            pass

    msg = str(exc_info.value)
    assert "multiple" in msg
    assert "nargs" in msg


def test_argument_nargs_minus_one_boundary_still_allowed(runner):
    @click.command()
    @click.argument("files", nargs=-1)
    def cli(files):
        click.echo("|".join(files))

    result = runner.invoke(cli, ["a", "b", "c"])
    assert result.exit_code == 0, result.output
    assert result.output == "a|b|c\n"

    result = runner.invoke(cli, [])
    assert result.exit_code == 0, result.output
    assert result.output == "\n"


def test_multiple_option_default_nargs_still_works(runner):
    @click.command()
    @click.option("--item", multiple=True)
    def cli(item):
        click.echo(",".join(item))

    result = runner.invoke(cli, ["--item", "x", "--item", "y"])
    assert result.exit_code == 0, result.output
    assert result.output == "x,y\n"


def test_multiple_option_with_fixed_nargs_still_works(runner):
    @click.command()
    @click.option("--point", multiple=True, nargs=2, type=int)
    def cli(point):
        click.echo(repr(point))

    result = runner.invoke(cli, ["--point", "1", "2", "--point", "3", "4"])
    assert result.exit_code == 0, result.output
    assert result.output == "((1, 2), (3, 4))\n"


def test_fixed_nargs_argument_still_works(runner):
    @click.command()
    @click.argument("pair", nargs=2)
    def cli(pair):
        click.echo("-".join(pair))

    result = runner.invoke(cli, ["left", "right"])
    assert result.exit_code == 0, result.output
    assert result.output == "left-right\n"
