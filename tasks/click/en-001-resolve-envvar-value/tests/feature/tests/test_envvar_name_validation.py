import pytest

import click


def _make(envvar):
    @click.command()
    @click.option("--token", envvar=envvar, default="none")
    def cli(token):
        click.echo(f"token={token}")

    return cli


def _assert_rejected(result, bad_name, param_name="token"):
    assert result.exit_code != 0
    assert isinstance(result.exception, ValueError)
    message = str(result.exception)
    assert "envvar" in message
    assert repr(bad_name) in message
    assert repr(param_name) in message


def test_fault_unknown_env_empty_entry_in_list(runner):
    cli = _make(["", "APP_TOKEN"])
    result = runner.invoke(cli, [], env={"APP_TOKEN": "secret"})
    _assert_rejected(result, "")


def test_fault_unknown_env_empty_entry_after_valid(runner):
    cli = _make(["APP_TOKEN", ""])
    result = runner.invoke(cli, [], env={"APP_TOKEN": "secret"})
    _assert_rejected(result, "")


def test_fault_separator_injection_equals(runner):
    cli = _make("STG=PRD")
    result = runner.invoke(cli, [])
    _assert_rejected(result, "STG=PRD")


def test_fault_separator_injection_space(runner):
    cli = _make("APP TOKEN")
    result = runner.invoke(cli, [], env={"APP TOKEN": "x"})
    _assert_rejected(result, "APP TOKEN")


def test_fault_separator_injection_tab_in_list(runner):
    cli = _make(["GOOD_TOKEN", "BAD\tTOKEN"])
    result = runner.invoke(cli, [], env={"GOOD_TOKEN": "x"})
    _assert_rejected(result, "BAD\tTOKEN")


def test_fault_separator_injection_argument(runner):
    @click.command()
    @click.argument("src", envvar="SRC PATH", required=False)
    def cli(src):
        click.echo(f"src={src}")

    result = runner.invoke(cli, [], env={"SRC PATH": "x"})
    _assert_rejected(result, "SRC PATH", param_name="src")


def test_plain_envvar_still_read(runner):
    cli = _make("APP_TOKEN")
    result = runner.invoke(cli, [], env={"APP_TOKEN": "secret"})
    assert result.exit_code == 0, result.output
    assert result.output == "token=secret\n"


def test_list_first_non_empty_still_wins(runner):
    cli = _make(["A_TOKEN", "B_TOKEN"])
    result = runner.invoke(cli, [], env={"A_TOKEN": "", "B_TOKEN": "b"})
    assert result.exit_code == 0, result.output
    assert result.output == "token=b\n"


def test_two_environments_read_distinct_names(runner):
    stg = _make("STG_TOKEN")
    prd = _make("PRD_TOKEN")
    env = {"STG_TOKEN": "stg", "PRD_TOKEN": "prd"}
    r1 = runner.invoke(stg, [], env=env)
    r2 = runner.invoke(prd, [], env=env)
    assert r1.output == "token=stg\n"
    assert r2.output == "token=prd\n"


def test_empty_string_envvar_still_disabled(runner):
    cli = _make("")
    result = runner.invoke(cli, [])
    assert result.exit_code == 0, result.output
    assert result.output == "token=none\n"


def test_command_line_value_still_used(runner):
    cli = _make("APP_TOKEN")
    result = runner.invoke(cli, ["--token", "cli"], env={"APP_TOKEN": "env"})
    assert result.exit_code == 0, result.output
    assert result.output == "token=cli\n"


def test_auto_envvar_prefix_names_unchanged(runner):
    @click.command()
    @click.option("--log-level", default="info")
    def cli(log_level):
        click.echo(f"level={log_level}")

    result = runner.invoke(
        cli, [], auto_envvar_prefix="APP", env={"APP_LOG_LEVEL": "debug"}
    )
    assert result.exit_code == 0, result.output
    assert result.output == "level=debug\n"
