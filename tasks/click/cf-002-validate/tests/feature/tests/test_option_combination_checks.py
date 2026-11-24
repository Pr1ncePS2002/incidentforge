import pytest

import click


def _assert_names(excinfo, *names):
    message = str(excinfo.value)
    for name in names:
        assert name in message, (name, message)


def test_fault_mutually_exclusive_confirmation_on_is_flag():
    with pytest.raises(TypeError) as excinfo:
        click.Option(["--yes"], is_flag=True, prompt=True, confirmation_prompt=True)
    _assert_names(excinfo, "confirmation_prompt", "is_flag")


def test_fault_mutually_exclusive_confirmation_on_secondary_flag():
    with pytest.raises(TypeError) as excinfo:
        click.Option(["--shout/--no-shout"], prompt=True, confirmation_prompt=True)
    _assert_names(excinfo, "confirmation_prompt", "is_flag")


def test_fault_mutually_exclusive_confirmation_text_via_decorator():
    with pytest.raises(TypeError) as excinfo:

        @click.command()
        @click.option(
            "--force", is_flag=True, prompt=True, confirmation_prompt="Again?"
        )
        def cli(force):
            pass

    _assert_names(excinfo, "confirmation_prompt", "is_flag")


def test_fault_negative_or_zero_count_default_negative():
    with pytest.raises(TypeError) as excinfo:
        click.Option(["-v"], count=True, default=-1)
    _assert_names(excinfo, "default", "count")


def test_fault_negative_or_zero_count_default_via_decorator():
    with pytest.raises(TypeError) as excinfo:

        @click.command()
        @click.option("-v", "--verbose", count=True, default=-5)
        def cli(verbose):
            pass

    _assert_names(excinfo, "default", "count")


def test_fault_boundary_equal_count_default_zero(runner):
    with pytest.raises(TypeError):
        click.Option(["-v"], count=True, default=-1)

    @click.command()
    @click.option("-v", "--verbose", count=True, default=0)
    def cli(verbose):
        click.echo(f"verbose={verbose}")

    result = runner.invoke(cli, [])
    assert result.exit_code == 0, result.output
    assert "verbose=0" in result.output

    result = runner.invoke(cli, ["-vv"])
    assert result.exit_code == 0, result.output
    assert "verbose=2" in result.output


def test_count_positive_default_still_used(runner):
    @click.command()
    @click.option("-v", "--verbose", count=True, default=3)
    def cli(verbose):
        click.echo(f"verbose={verbose}")

    result = runner.invoke(cli, [])
    assert result.exit_code == 0, result.output
    assert "verbose=3" in result.output


def test_count_without_default_reports_zero(runner):
    @click.command()
    @click.option("-v", "--verbose", count=True)
    def cli(verbose):
        click.echo(f"verbose={verbose}")

    result = runner.invoke(cli, [])
    assert result.exit_code == 0, result.output
    assert "verbose=0" in result.output
    result = runner.invoke(cli, ["-vvv"])
    assert result.exit_code == 0, result.output
    assert "verbose=3" in result.output


def test_confirmation_prompt_on_string_option_still_works(runner):
    @click.command()
    @click.option("--password", prompt=True, confirmation_prompt=True)
    def cli(password):
        click.echo(f"got={password}")

    result = runner.invoke(cli, [], input="secret\nsecret\n")
    assert result.exit_code == 0, result.output
    assert "got=secret" in result.output


def test_bool_flag_prompt_without_confirmation_still_works(runner):
    @click.command()
    @click.option("--yes", is_flag=True, prompt=True)
    def cli(yes):
        click.echo(f"yes={yes}")

    result = runner.invoke(cli, ["--yes"])
    assert result.exit_code == 0, result.output
    assert "yes=True" in result.output


def test_bool_flag_with_false_confirmation_accepted():
    opt = click.Option(["--yes"], is_flag=True, confirmation_prompt=False)
    assert opt.is_flag
