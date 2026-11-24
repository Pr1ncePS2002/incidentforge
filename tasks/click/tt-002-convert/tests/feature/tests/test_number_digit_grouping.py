import pytest

import click


def make_cli(type_, **kwargs):
    @click.command()
    @click.option("--count", type=type_, **kwargs)
    def cli(count):
        click.echo(repr(count))

    return cli


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,000", "1000"),
        ("12,345,678", "12345678"),
        ("-1,000", "-1000"),
        ("+2,500", "2500"),
        (" 9,999 ", "9999"),
    ],
)
def test_int_accepts_thousands_separators(runner, raw, expected):
    result = runner.invoke(make_cli(click.INT), ["--count", raw])
    assert result.exception is None, result.output
    assert result.exit_code == 0
    assert result.output == f"{expected}\n"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,000", 1000.0),
        ("1,234.5", 1234.5),
        ("-12,345.25", -12345.25),
    ],
)
def test_float_accepts_thousands_separators(runner, raw, expected):
    result = runner.invoke(make_cli(click.FLOAT), ["--count", raw])
    assert result.exit_code == 0, result.output
    assert result.output == f"{expected!r}\n"


def test_grouped_value_matches_canonical(runner):
    grouped = runner.invoke(make_cli(click.INT), ["--count", "1,000,000"])
    canonical = runner.invoke(make_cli(click.INT), ["--count", "1000000"])
    assert grouped.exit_code == 0 == canonical.exit_code
    assert grouped.output == canonical.output


def test_int_range_uses_grouped_value(runner):
    result = runner.invoke(make_cli(click.IntRange(0, 10000)), ["--count", "2,500"])
    assert result.exit_code == 0, result.output
    assert result.output == "2500\n"


def test_int_range_clamps_grouped_value(runner):
    cli = make_cli(click.IntRange(0, 1000, clamp=True))
    result = runner.invoke(cli, ["--count", "5,000"])
    assert result.exit_code == 0, result.output
    assert result.output == "1000\n"


def test_int_range_rejects_grouped_value_out_of_range(runner):
    result = runner.invoke(make_cli(click.IntRange(0, 100)), ["--count", "1,000"])
    assert result.exit_code == 2
    assert "--count" in result.output
    assert "not in the range" in result.output


def test_envvar_grouped_value(runner):
    cli = make_cli(click.INT, envvar="COUNT")
    result = runner.invoke(cli, [], env={"COUNT": "1,000"})
    assert result.exit_code == 0, result.output
    assert result.output == "1000\n"


def test_envvar_multiple_grouped_values(runner):
    cli = make_cli(click.INT, envvar="COUNT", multiple=True)
    result = runner.invoke(cli, [], env={"COUNT": "1,000 2,000"})
    assert result.exit_code == 0, result.output
    assert result.output == "(1000, 2000)\n"


@pytest.mark.parametrize(
    ("type_", "raw", "expected"),
    [
        (click.INT, "42", "42"),
        (click.INT, " 7 ", "7"),
        (click.INT, "1_000", "1000"),
        (click.INT, "-3", "-3"),
        (click.FLOAT, "2.5", "2.5"),
        (click.FLOAT, "1e3", "1000.0"),
    ],
)
def test_plain_numbers_still_parse(runner, type_, raw, expected):
    result = runner.invoke(make_cli(type_), ["--count", raw])
    assert result.exit_code == 0, result.output
    assert result.output == f"{expected}\n"


@pytest.mark.parametrize(
    "bad",
    ["1,00", "1,0000", "1234,567", ",100", "100,", "1,,000", "1,0a0"],
)
def test_fault_garbage_bad_grouping_names_option_and_value(runner, bad):
    cli = make_cli(click.INT, multiple=True)
    # The first value is well formed, so the error must come from the bad one.
    result = runner.invoke(cli, ["--count", "1,000", "--count", bad])
    assert result.exit_code == 2
    assert isinstance(result.exception, SystemExit)
    assert "'--count'" in result.output
    assert f"{bad!r} is not a valid integer" in result.output
    assert "'1,000'" not in result.output


def test_fault_garbage_int_with_fraction(runner):
    cli = make_cli(click.INT, multiple=True)
    result = runner.invoke(cli, ["--count", "2,000", "--count", "1,000.5"])
    assert result.exit_code == 2
    assert "'--count'" in result.output
    assert "'1,000.5' is not a valid integer" in result.output
    assert "'2,000'" not in result.output


def test_fault_garbage_float_comma_in_fraction(runner):
    cli = make_cli(click.FLOAT, multiple=True)
    result = runner.invoke(cli, ["--count", "1,000.5", "--count", "1,000.0,5"])
    assert result.exit_code == 2
    assert "'--count'" in result.output
    assert "'1,000.0,5' is not a valid float" in result.output
    assert "'1,000.5'" not in result.output
