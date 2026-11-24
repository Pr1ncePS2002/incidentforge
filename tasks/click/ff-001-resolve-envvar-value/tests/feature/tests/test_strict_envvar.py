import pytest

import click


class StrictOption(click.Option):
    strict_envvar = True


class StrictArgument(click.Argument):
    strict_envvar = True


def _make_cli(envvar="APP_TOKEN", cls=StrictOption, **kwargs):
    @click.command()
    @click.option("--token", envvar=envvar, cls=cls, **kwargs)
    def cli(token):
        click.echo(f"token={token!r}")

    return cli


def test_fault_empty_value_rejected(runner):
    result = runner.invoke(_make_cli(), [], env={"APP_TOKEN": ""})
    assert result.exit_code == 2
    assert "APP_TOKEN" in result.output
    assert "--token" in result.output
    assert "token=None" not in result.output


@pytest.mark.parametrize("value", [" ", "   ", "\t\n"])
def test_fault_empty_whitespace_rejected(runner, value):
    result = runner.invoke(_make_cli(), [], env={"APP_TOKEN": value})
    assert result.exit_code == 2
    assert "APP_TOKEN" in result.output
    assert "--token" in result.output


@pytest.mark.parametrize(
    "value",
    [
        "changethis",
        "changeme",
        "TODO",
        "todo",
        "  ChangeMe  ",
        "<fill-me>",
        "<your-token>",
        "xxx",
        "FIXME",
        "placeholder",
    ],
)
def test_fault_placeholder_rejected(runner, value):
    result = runner.invoke(_make_cli(), [], env={"APP_TOKEN": value})
    assert result.exit_code == 2
    assert "APP_TOKEN" in result.output
    assert "--token" in result.output


def test_fault_placeholder_argument(runner):
    @click.command()
    @click.argument("name", envvar="APP_NAME", cls=StrictArgument)
    def cli(name):
        click.echo(f"name={name}")

    result = runner.invoke(cli, [], env={"APP_NAME": "<fill-me>"})
    assert result.exit_code == 2
    assert "APP_NAME" in result.output
    assert "NAME" in result.output
    assert "name=" not in result.output


def test_fault_several_bad_all_named(runner):
    cli = _make_cli(envvar=["APP_TOKEN_A", "APP_TOKEN_B", "APP_TOKEN_C"])
    result = runner.invoke(
        cli,
        [],
        env={"APP_TOKEN_A": "", "APP_TOKEN_B": "todo", "APP_TOKEN_C": "real"},
    )
    assert result.exit_code == 2
    assert "APP_TOKEN_A" in result.output
    assert "APP_TOKEN_B" in result.output
    assert "APP_TOKEN_C" not in result.output
    assert result.output.count("Error:") == 1


def test_fault_several_bad_raises_single_bad_parameter():
    cli = _make_cli(envvar=["APP_TOKEN_A", "APP_TOKEN_B"])
    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [],
        env={"APP_TOKEN_A": "changethis", "APP_TOKEN_B": "  "},
        standalone_mode=False,
    )
    assert isinstance(result.exception, click.BadParameter)
    message = result.exception.format_message()
    assert "APP_TOKEN_A" in message
    assert "APP_TOKEN_B" in message
    assert "--token" in message


def test_strict_valid_value_loads(runner):
    result = runner.invoke(_make_cli(), [], env={"APP_TOKEN": "s3cr3t"})
    assert result.exit_code == 0, result.output
    assert "token='s3cr3t'" in result.output


def test_strict_value_containing_placeholder_word_is_valid(runner):
    result = runner.invoke(_make_cli(), [], env={"APP_TOKEN": "todo-list"})
    assert result.exit_code == 0, result.output
    assert "token='todo-list'" in result.output


def test_strict_absent_uses_default(runner):
    cli = _make_cli(default="fallback")
    result = runner.invoke(cli, [], env={"APP_TOKEN": None})
    assert result.exit_code == 0, result.output
    assert "token='fallback'" in result.output


def test_strict_absent_first_valid_second(runner):
    cli = _make_cli(envvar=["APP_TOKEN_A", "APP_TOKEN_B"])
    result = runner.invoke(
        cli, [], env={"APP_TOKEN_A": None, "APP_TOKEN_B": "good"}
    )
    assert result.exit_code == 0, result.output
    assert "token='good'" in result.output


def test_strict_command_line_value_without_env(runner):
    result = runner.invoke(_make_cli(), ["--token", "abc"], env={"APP_TOKEN": None})
    assert result.exit_code == 0, result.output
    assert "token='abc'" in result.output


def test_non_strict_whitespace_passes_through(runner):
    cli = _make_cli(cls=click.Option)
    result = runner.invoke(cli, [], env={"APP_TOKEN": "   "})
    assert result.exit_code == 0, result.output
    assert "token='   '" in result.output


def test_non_strict_placeholder_passes_through(runner):
    cli = _make_cli(cls=click.Option)
    result = runner.invoke(cli, [], env={"APP_TOKEN": "changethis"})
    assert result.exit_code == 0, result.output
    assert "token='changethis'" in result.output


def test_non_strict_empty_treated_as_unset(runner):
    cli = _make_cli(cls=click.Option, default="fallback")
    result = runner.invoke(cli, [], env={"APP_TOKEN": ""})
    assert result.exit_code == 0, result.output
    assert "token='fallback'" in result.output
