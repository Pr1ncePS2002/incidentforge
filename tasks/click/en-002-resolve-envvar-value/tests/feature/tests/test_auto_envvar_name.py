import pytest

import click


def _make_cli():
    @click.command()
    @click.option("--token")
    def cli(token):
        ctx = click.get_current_context()
        opt = next(p for p in ctx.command.params if p.name == "token")
        click.echo(f"{opt.get_auto_envvar_name(ctx)} {token}")

    return cli


def _make_group():
    @click.group()
    def grp():
        pass

    @grp.command("deploy")
    @click.option("--token")
    def deploy(token):
        ctx = click.get_current_context()
        opt = next(p for p in ctx.command.params if p.name == "token")
        click.echo(f"{opt.get_auto_envvar_name(ctx)} {token}")

    @grp.command("db.migrate")
    @click.option("--token")
    def migrate(token):
        ctx = click.get_current_context()
        opt = next(p for p in ctx.command.params if p.name == "token")
        click.echo(f"{opt.get_auto_envvar_name(ctx)} {token}")

    return grp


def test_plain_names_are_unchanged(runner):
    cli = _make_cli()
    result = runner.invoke(
        cli, [], auto_envvar_prefix="app", env={"APP_TOKEN": "abc"}
    )
    assert result.exception is None, result.output
    assert result.exit_code == 0
    assert result.output == "APP_TOKEN abc\n"


def test_dashed_names_are_unchanged(runner):
    @click.command()
    @click.option("--user-name")
    def cli(user_name):
        click.echo(f"user={user_name}")

    result = runner.invoke(
        cli, [], auto_envvar_prefix="my-app", env={"MY_APP_USER_NAME": "alice"}
    )
    assert result.exit_code == 0, result.output
    assert result.output == "user=alice\n"


def test_command_line_value_still_wins(runner):
    cli = _make_cli()
    result = runner.invoke(
        cli, ["--token", "cli"], auto_envvar_prefix="app", env={"APP_TOKEN": "env"}
    )
    assert result.exit_code == 0, result.output
    assert result.output == "APP_TOKEN cli\n"


def test_helper_returns_none_without_prefix():
    cli = _make_cli()
    ctx = click.Context(cli)
    assert cli.params[0].get_auto_envvar_name(ctx) is None


def test_helper_returns_none_when_autoenv_disabled():
    @click.command()
    @click.option("--token", allow_from_autoenv=False)
    def cli(token):
        pass

    ctx = click.Context(cli, auto_envvar_prefix="app")
    assert cli.params[0].get_auto_envvar_name(ctx) is None


def test_no_prefix_reads_nothing(runner):
    @click.command()
    @click.option("--token")
    def cli(token):
        click.echo(f"token={token}")

    result = runner.invoke(cli, [], env={"TOKEN": "x", "_TOKEN": "y"})
    assert result.exit_code == 0, result.output
    assert result.output == "token=None\n"


def test_fault_unscoped_key_two_environments_differ(runner):
    cli = _make_cli()
    env = {"TOKEN": "unscoped", "STAGING_TOKEN": "stg", "PROD_TOKEN": "prd"}
    stg = runner.invoke(cli, [], auto_envvar_prefix="staging", env=env)
    prd = runner.invoke(cli, [], auto_envvar_prefix="prod", env=env)
    assert stg.exit_code == 0, stg.output
    assert prd.exit_code == 0, prd.output
    assert stg.output == "STAGING_TOKEN stg\n"
    assert prd.output == "PROD_TOKEN prd\n"


def test_fault_unscoped_key_bare_name_not_read(runner):
    cli = _make_cli()
    result = runner.invoke(
        cli, [], auto_envvar_prefix="prod", env={"TOKEN": "unscoped"}
    )
    assert result.exit_code == 0, result.output
    assert result.output == "PROD_TOKEN None\n"


def test_fault_wrong_env_source_uses_given_context():
    cli = _make_cli()
    opt = cli.params[0]
    assert opt.get_auto_envvar_name(click.Context(cli, auto_envvar_prefix="stg")) == (
        "STG_TOKEN"
    )
    assert opt.get_auto_envvar_name(click.Context(cli, auto_envvar_prefix="prd")) == (
        "PRD_TOKEN"
    )


def test_fault_wrong_env_source_nested_command(runner):
    grp = _make_group()
    result = runner.invoke(
        grp,
        ["deploy"],
        auto_envvar_prefix="app",
        env={"APP_TOKEN": "wrong", "APP_DEPLOY_TOKEN": "right"},
    )
    assert result.exit_code == 0, result.output
    assert result.output == "APP_DEPLOY_TOKEN right\n"


@pytest.mark.parametrize("prefix", ["", "-", "__", ". "])
def test_fault_unknown_env_rejected_on_invoke(runner, prefix):
    cli = _make_cli()
    result = runner.invoke(cli, [], auto_envvar_prefix=prefix, env={"_TOKEN": "x"})
    assert result.exit_code != 0
    assert isinstance(result.exception, ValueError)
    assert "auto_envvar_prefix" in str(result.exception)


def test_fault_unknown_env_helper_raises():
    cli = _make_cli()
    ctx = click.Context(cli, auto_envvar_prefix="")
    with pytest.raises(ValueError, match="auto_envvar_prefix"):
        cli.params[0].get_auto_envvar_name(ctx)


@pytest.mark.parametrize("prefix", ["my.app", "my app", "my/app"])
def test_fault_separator_injection_prefix_normalised(runner, prefix):
    cli = _make_cli()
    env = {"MY_APP_TOKEN": "ok", f"{prefix.upper()}_TOKEN": "raw"}
    result = runner.invoke(cli, [], auto_envvar_prefix=prefix, env=env)
    assert result.exit_code == 0, result.output
    assert result.output == "MY_APP_TOKEN ok\n"


def test_fault_separator_injection_raw_name_not_read(runner):
    cli = _make_cli()
    result = runner.invoke(
        cli, [], auto_envvar_prefix="my.app", env={"MY.APP_TOKEN": "raw"}
    )
    assert result.exit_code == 0, result.output
    assert result.output == "MY_APP_TOKEN None\n"


def test_fault_separator_injection_subcommand_name(runner):
    grp = _make_group()
    result = runner.invoke(
        grp,
        ["db.migrate"],
        auto_envvar_prefix="app",
        env={"APP_DB_MIGRATE_TOKEN": "ok", "APP_DB.MIGRATE_TOKEN": "raw"},
    )
    assert result.exit_code == 0, result.output
    assert result.output == "APP_DB_MIGRATE_TOKEN ok\n"
