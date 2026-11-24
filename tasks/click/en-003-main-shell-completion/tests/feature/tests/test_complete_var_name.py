import pytest

import click

BODY = "command-body-executed"


def _make_cli(cls=None):
    kwargs = {} if cls is None else {"cls": cls}

    @click.command(**kwargs)
    def cli():
        click.echo(BODY)

    return cli


def test_plain_names_stay_stable():
    cli = _make_cli()
    assert cli.get_complete_var("cli") == "_CLI_COMPLETE"
    assert cli.get_complete_var("foo-bar.baz") == "_FOO_BAR_BAZ_COMPLETE"
    assert cli.get_complete_var("my_tool2") == "_MY_TOOL2_COMPLETE"
    assert cli.get_complete_var("Foo") == "_FOO_COMPLETE"


def test_group_inherits_helper():
    @click.group()
    def grp():
        pass

    assert grp.get_complete_var("my-group") == "_MY_GROUP_COMPLETE"


def test_plain_invocation_without_completion_runs(runner):
    cli = _make_cli()
    result = runner.invoke(cli, [], prog_name="my app")
    assert result.exception is None
    assert result.exit_code == 0
    assert result.output == BODY + "\n"


def test_dashed_name_completion_still_triggers(runner):
    cli = _make_cli()
    result = runner.invoke(
        cli, [], prog_name="foo-bar", env={"_FOO_BAR_COMPLETE": "zsh_source"}
    )
    assert result.exit_code == 0
    assert "_FOO_BAR_COMPLETE=zsh_complete" in result.output
    assert BODY not in result.output


def test_valid_explicit_complete_var_is_used(runner):
    cli = _make_cli()
    result = runner.invoke(
        cli,
        [],
        prog_name="tool",
        complete_var="MY_COMPLETE",
        env={"MY_COMPLETE": "zsh_source"},
    )
    assert result.exit_code == 0
    assert "MY_COMPLETE=zsh_complete" in result.output
    assert BODY not in result.output


def test_fault_separator_injection_space_in_prog_name(runner):
    cli = _make_cli()
    result = runner.invoke(
        cli, [], prog_name="my app", env={"_MY_APP_COMPLETE": "zsh_source"}
    )
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert result.exit_code == 0
    assert "_MY_APP_COMPLETE=zsh_complete" in result.output
    assert BODY not in result.output


def test_fault_separator_injection_helper_normalises():
    cli = _make_cli()
    assert cli.get_complete_var("my app") == "_MY_APP_COMPLETE"
    assert cli.get_complete_var("my+app/x") == "_MY_APP_X_COMPLETE"
    assert cli.get_complete_var("café") == "_CAF__COMPLETE"
    for name in ("my app", "a+b", "x/y", "café", "t=1"):
        var = cli.get_complete_var(name)
        assert all(c.isascii() and (c.isalnum() or c == "_") for c in var), var


def test_fault_unscoped_key_distinct_programs(runner):
    cli = _make_cli()
    assert cli.get_complete_var("app one") != cli.get_complete_var("app two")
    assert cli.get_complete_var("tool.a") != cli.get_complete_var("tool.b")

    result = runner.invoke(
        cli, [], prog_name="app one", env={"_APP_TWO_COMPLETE": "zsh_source"}
    )
    assert result.exit_code == 0
    assert result.output == BODY + "\n"


def test_fault_wrong_env_source_override_is_used(runner):
    class CustomCommand(click.Command):
        def get_complete_var(self, prog_name: str) -> str:
            return "CUSTOM_" + prog_name.upper() + "_COMPLETE"

    cli = _make_cli(CustomCommand)

    result = runner.invoke(
        cli, [], prog_name="tool", env={"CUSTOM_TOOL_COMPLETE": "zsh_source"}
    )
    assert result.exit_code == 0
    assert "CUSTOM_TOOL_COMPLETE=zsh_complete" in result.output
    assert BODY not in result.output

    # the hardcoded default name no longer triggers completion
    result = runner.invoke(
        cli, [], prog_name="tool", env={"_TOOL_COMPLETE": "zsh_source"}
    )
    assert result.exit_code == 0
    assert result.output == BODY + "\n"

    # an explicit complete_var still wins over the override
    result = runner.invoke(
        cli,
        [],
        prog_name="tool",
        complete_var="EXPLICIT_COMPLETE",
        env={"EXPLICIT_COMPLETE": "zsh_source"},
    )
    assert result.exit_code == 0
    assert "EXPLICIT_COMPLETE=zsh_complete" in result.output


@pytest.mark.parametrize("prog_name", ["", "   ", "---"])
def test_fault_unknown_env_unusable_prog_name(runner, prog_name):
    cli = _make_cli()
    with pytest.raises(ValueError, match="prog_name"):
        cli.get_complete_var(prog_name)

    result = runner.invoke(cli, [], prog_name=prog_name)
    assert isinstance(result.exception, ValueError)
    assert "prog_name" in str(result.exception)
    assert BODY not in result.output


@pytest.mark.parametrize("complete_var", ["", "BAD VAR", "1ABC", "A=B"])
def test_fault_unknown_env_invalid_complete_var(runner, complete_var):
    cli = _make_cli()
    result = runner.invoke(cli, [], prog_name="tool", complete_var=complete_var)
    assert isinstance(result.exception, ValueError)
    assert "complete_var" in str(result.exception)
    assert BODY not in result.output
