import datetime

import pytest

import click


def _cli(**option_kwargs):
    @click.command()
    @click.option("--timeout", type=click.types.Duration(), **option_kwargs)
    def cli(timeout):
        if timeout is None:
            click.echo("none")
        else:
            click.echo(f"{timeout.total_seconds()!r}")

    return cli


def test_plain_seconds_still_parse(runner):
    result = runner.invoke(_cli(), ["--timeout", "30"])
    assert result.exit_code == 0, result.output
    assert result.output == "30.0\n"


def test_plain_fractional_seconds_parse(runner):
    result = runner.invoke(_cli(), ["--timeout", "2.5"])
    assert result.exit_code == 0, result.output
    assert result.output == "2.5\n"


def test_missing_option_is_none(runner):
    result = runner.invoke(_cli(), [])
    assert result.exit_code == 0, result.output
    assert result.output == "none\n"


def test_python_defaults_convert(runner):
    assert runner.invoke(_cli(default=45), []).output == "45.0\n"
    assert runner.invoke(_cli(default="1m"), []).output == "60.0\n"
    td = datetime.timedelta(minutes=2)
    assert runner.invoke(_cli(default=td), []).output == "120.0\n"


def test_metavar_in_help(runner):
    result = runner.invoke(_cli(), ["--help"])
    assert result.exit_code == 0, result.output
    assert "DURATION" in result.output


def test_direct_convert_returns_timedelta():
    dur = click.types.Duration()
    assert dur.convert("5m", None, None) == datetime.timedelta(minutes=5)
    td = datetime.timedelta(hours=3)
    assert dur.convert(td, None, None) is td
    assert dur.convert(10, None, None) == datetime.timedelta(seconds=10)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("30s", "30.0"),
        ("5m", "300.0"),
        ("2h", "7200.0"),
        ("1d", "86400.0"),
        ("1.5h", "5400.0"),
        ("90S", "90.0"),
        ("2H", "7200.0"),
        ("  10m  ", "600.0"),
    ],
)
def test_fault_duration_suffix(runner, raw, expected):
    result = runner.invoke(_cli(), ["--timeout", raw])
    assert result.exit_code == 0, result.output
    assert result.output == f"{expected}\n"


def test_fault_duration_suffix_matches_canonical(runner):
    suffixed = runner.invoke(_cli(), ["--timeout", "5m"])
    canonical = runner.invoke(_cli(), ["--timeout", "300"])
    assert suffixed.exit_code == canonical.exit_code == 0
    assert suffixed.output == canonical.output
    dur = click.types.Duration()
    assert dur.convert("1d", None, None) == dur.convert("86400", None, None)


def test_fault_duration_suffix_from_envvar(runner):
    result = runner.invoke(
        _cli(envvar="APP_TIMEOUT"), [], env={"APP_TIMEOUT": "2h"}
    )
    assert result.exit_code == 0, result.output
    assert result.output == "7200.0\n"


@pytest.mark.parametrize(
    "raw",
    ["5x", "abc", "", "s", "-5s", "nan", "inf", "1e400s", "5 minutes"],
)
def test_fault_garbage_names_option_and_value(runner, raw):
    result = runner.invoke(_cli(), [f"--timeout={raw}"])
    assert result.exit_code == 2, result.output
    assert "--timeout" in result.output
    assert repr(raw) in result.output
    assert "is not a valid duration" in result.output


def test_fault_garbage_from_envvar(runner):
    result = runner.invoke(
        _cli(envvar="APP_TIMEOUT"), [], env={"APP_TIMEOUT": "ten"}
    )
    assert result.exit_code == 2, result.output
    assert "--timeout" in result.output
    assert "'ten'" in result.output
    assert "is not a valid duration" in result.output


def test_fault_garbage_direct_convert_raises_bad_parameter():
    with pytest.raises(click.BadParameter, match="oops"):
        click.types.Duration().convert("oops", None, None)
