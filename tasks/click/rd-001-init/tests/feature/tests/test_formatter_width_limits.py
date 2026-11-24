import pytest

import click
import click.formatting
from click.formatting import HelpFormatter


@pytest.fixture(autouse=True)
def _no_forced_width(monkeypatch):
    monkeypatch.setattr(click.formatting, "FORCED_WIDTH", None)


def test_default_width_clamped_to_80(monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")
    assert HelpFormatter().width == 78


def test_default_floor_is_50(monkeypatch):
    monkeypatch.setenv("COLUMNS", "30")
    assert HelpFormatter().width == 50


def test_small_max_width_without_min_keeps_old_floor(monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")
    assert HelpFormatter(max_width=40).width == 50


def test_explicit_width_used_verbatim(monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")
    assert HelpFormatter(width=30).width == 30
    assert HelpFormatter(width=30, min_width=40).width == 30


def test_help_still_renders(runner):
    @click.command()
    @click.option("--name", help="The name.")
    def cli(name):
        pass

    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "--name" in result.output


def test_fault_hardcoded_size_floor_follows_min_width(monkeypatch):
    monkeypatch.setenv("COLUMNS", "40")
    assert HelpFormatter(min_width=30).width == 38


def test_fault_hardcoded_size_floor_raised(monkeypatch):
    monkeypatch.setenv("COLUMNS", "40")
    assert HelpFormatter(min_width=60, max_width=100).width == 60


def test_fault_unset_limit_uses_default_max(monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")
    assert HelpFormatter(min_width=20).width == 78


def test_fault_unset_limit_small_terminal(monkeypatch):
    monkeypatch.setenv("COLUMNS", "10")
    assert HelpFormatter(min_width=20).width == 20


@pytest.mark.parametrize(
    ("kwargs", "name", "value"),
    [
        ({"width": 0}, "width", "0"),
        ({"width": -5}, "width", "-5"),
        ({"max_width": 0}, "max_width", "0"),
        ({"max_width": -1}, "max_width", "-1"),
        ({"min_width": 0}, "min_width", "0"),
        ({"min_width": -3}, "min_width", "-3"),
    ],
)
def test_fault_zero_or_negative(kwargs, name, value):
    with pytest.raises(ValueError) as exc_info:
        HelpFormatter(**kwargs)
    message = str(exc_info.value)
    assert name in message
    assert value in message


def test_fault_zero_or_negative_context_setting(runner):
    @click.command(context_settings={"max_content_width": -5})
    def cli():
        pass

    result = runner.invoke(cli, ["--help"])
    assert result.exit_code != 0
    assert isinstance(result.exception, ValueError)
    assert "max_width" in str(result.exception)
    assert "-5" in str(result.exception)


def test_fault_min_over_max_explicit():
    with pytest.raises(ValueError) as exc_info:
        HelpFormatter(min_width=100, max_width=80)
    message = str(exc_info.value)
    assert "min_width" in message
    assert "max_width" in message
    assert "100" in message
    assert "80" in message


def test_fault_min_over_max_default_max():
    with pytest.raises(ValueError) as exc_info:
        HelpFormatter(min_width=90)
    message = str(exc_info.value)
    assert "min_width" in message
    assert "max_width" in message
    assert "90" in message
    assert "80" in message


def test_min_equal_to_max_allowed(monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")
    assert HelpFormatter(min_width=80, max_width=80).width == 80
