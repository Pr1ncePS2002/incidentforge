import pytest

import click
from click.types import FloatRange
from click.types import IntRange


def _assert_names(excinfo, *values):
    msg = str(excinfo.value)
    assert "min" in msg
    assert "max" in msg
    for v in values:
        assert str(v) in msg


def test_fault_inverted_range_int():
    with pytest.raises(ValueError) as excinfo:
        click.IntRange(10, 1)
    _assert_names(excinfo, 10, 1)


def test_fault_inverted_range_float():
    with pytest.raises(ValueError) as excinfo:
        FloatRange(2.5, -1.0)
    _assert_names(excinfo, 2.5, -1.0)


def test_fault_inverted_range_mixed_numbers():
    with pytest.raises(ValueError) as excinfo:
        click.FloatRange(1, 0.5)
    _assert_names(excinfo, 1, 0.5)


def test_fault_inverted_range_keywords_and_clamp():
    with pytest.raises(ValueError) as excinfo:
        IntRange(min=7, max=3, clamp=True)
    _assert_names(excinfo, 7, 3)


def test_fault_inverted_range_at_declaration():
    with pytest.raises(ValueError) as excinfo:

        @click.command()
        @click.option("--n", type=click.IntRange(5, 2))
        def cli(n):
            pass

    _assert_names(excinfo, 5, 2)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_open": True},
        {"max_open": True},
        {"min_open": True, "max_open": True},
    ],
)
def test_fault_boundary_equal_open_int(kwargs):
    with pytest.raises(ValueError) as excinfo:
        click.IntRange(3, 3, **kwargs)
    _assert_names(excinfo)


def test_fault_boundary_equal_open_float():
    with pytest.raises(ValueError) as excinfo:
        click.FloatRange(1.0, 1.0, max_open=True)
    _assert_names(excinfo)


def test_equal_closed_bounds_accept_single_value(runner):
    @click.command()
    @click.option("--n", type=click.IntRange(3, 3))
    def cli(n):
        click.echo(f"n={n}")

    result = runner.invoke(cli, ["--n", "3"])
    assert result.exit_code == 0, result.output
    assert "n=3" in result.output

    result = runner.invoke(cli, ["--n", "4"])
    assert result.exit_code == 2
    assert "not in the range" in result.output


def test_equal_closed_bounds_clamp(runner):
    @click.command()
    @click.option("--n", type=click.IntRange(3, 3, clamp=True))
    def cli(n):
        click.echo(f"n={n}")

    for raw in ("-10", "3", "99"):
        result = runner.invoke(cli, ["--n", raw])
        assert result.exit_code == 0, result.output
        assert "n=3" in result.output


def test_equal_closed_float_bounds(runner):
    @click.command()
    @click.option("--x", type=click.FloatRange(1.5, 1.5))
    def cli(x):
        click.echo(f"x={x}")

    result = runner.invoke(cli, ["--x", "1.5"])
    assert result.exit_code == 0, result.output
    assert "x=1.5" in result.output


def test_single_and_no_bounds_still_work():
    assert click.IntRange(min=5).convert(100, None, None) == 100
    assert click.FloatRange(max=1.0).convert(-50.0, None, None) == -50.0
    assert click.IntRange().convert(0, None, None) == 0


def test_valid_ranges_unchanged(runner):
    @click.command()
    @click.option("--a", type=click.IntRange(0, 5))
    @click.option("--b", type=click.FloatRange(0, 1, min_open=True))
    @click.option("--c", type=click.IntRange(0, 10, clamp=True))
    def cli(a, b, c):
        click.echo(f"{a} {b} {c}")

    result = runner.invoke(cli, ["--a", "5", "--b", "0.5", "--c", "20"])
    assert result.exit_code == 0, result.output
    assert "5 0.5 10" in result.output

    result = runner.invoke(cli, ["--b", "0"])
    assert result.exit_code == 2
    assert "not in the range" in result.output


def test_float_clamp_open_still_type_error():
    with pytest.raises(TypeError):
        click.FloatRange(0, 1, min_open=True, clamp=True)
