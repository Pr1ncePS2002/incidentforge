import pytest

import click


def _make_cli():
    @click.command()
    @click.option("--debug", type=bool, envvar="APP_DEBUG")
    def cli(debug):
        click.echo(repr(debug))

    return cli


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('"true"', True),
        ("'YES'", True),
        ('"On"', True),
        ('" 1 "', True),
        ("'t'", True),
        (' "y" ', True),
        ('"no"', False),
        ("'OFF'", False),
        ('"0"', False),
        ('"False"', False),
        ("'n'", False),
    ],
)
def test_fault_bool_words_quoted_on_command_line(runner, raw, expected):
    result = runner.invoke(_make_cli(), ["--debug", raw])
    assert result.exception is None, result.output
    assert result.exit_code == 0
    assert result.output == f"{expected!r}\n"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [('"true"', True), ("'Yes'", True), ('"off"', False), ("'0'", False)],
)
def test_fault_bool_words_quoted_from_envvar(runner, raw, expected):
    result = runner.invoke(_make_cli(), [], env={"APP_DEBUG": raw})
    assert result.exception is None, result.output
    assert result.exit_code == 0
    assert result.output == f"{expected!r}\n"


@pytest.mark.parametrize("raw", ['""', "''", ' "" '])
def test_fault_bool_words_quoted_empty_is_false(runner, raw):
    result = runner.invoke(_make_cli(), ["--debug", raw])
    assert result.exit_code == 0, result.output
    assert result.output == "False\n"


def test_fault_bool_words_quoted_argument(runner):
    @click.command()
    @click.argument("flag", type=click.BOOL)
    def cli(flag):
        click.echo(repr(flag))

    result = runner.invoke(cli, ["'ON'"])
    assert result.exit_code == 0, result.output
    assert result.output == "True\n"


def test_fault_bool_words_type_converts_directly():
    assert click.BOOL.convert('"yes"', None, None) is True
    assert click.BOOL.convert("'no'", None, None) is False


def test_fault_garbage_quoted_word_names_option_and_value(runner):
    result = runner.invoke(_make_cli(), ["--debug", '"maybe"'])
    assert result.exit_code == 2
    assert "--debug" in result.output
    assert "maybe" in result.output
    assert "is not a valid boolean" in result.output


@pytest.mark.parametrize("raw", ['""yes""', "\"true'", '"', "'", '"yes', "no'"])
def test_fault_garbage_bad_quoting_rejected(runner, raw):
    result = runner.invoke(_make_cli(), ["--debug", raw])
    assert result.exit_code == 2, result.output
    assert "--debug" in result.output
    assert "is not a valid boolean" in result.output


def test_fault_garbage_from_envvar_names_value(runner):
    result = runner.invoke(_make_cli(), [], env={"APP_DEBUG": "'perhaps'"})
    assert result.exit_code == 2
    assert "--debug" in result.output
    assert "perhaps" in result.output


def test_fault_garbage_direct_convert_raises():
    with pytest.raises(click.BadParameter) as exc_info:
        click.BOOL.convert('"maybe"', None, None)
    assert "maybe" in str(exc_info.value)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("yes", True),
        ("TRUE", True),
        (" on ", True),
        ("1", True),
        ("no", False),
        ("Off", False),
        ("0", False),
        ("", False),
    ],
)
def test_unquoted_values_still_parse(runner, raw, expected):
    result = runner.invoke(_make_cli(), ["--debug", raw])
    assert result.exit_code == 0, result.output
    assert result.output == f"{expected!r}\n"


def test_unquoted_garbage_still_rejected(runner):
    result = runner.invoke(_make_cli(), ["--debug", "maybe"])
    assert result.exit_code == 2
    assert "--debug" in result.output
    assert "maybe" in result.output


def test_native_bool_passthrough():
    assert click.BOOL.convert(True, None, None) is True
    assert click.BOOL.convert(False, None, None) is False
