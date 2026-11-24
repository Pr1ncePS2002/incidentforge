import click
from click.types import DateTime


def _multi_cli():
    @click.command()
    @click.option("--when", type=click.DateTime(), multiple=True, envvar="WHEN")
    def cli(when):
        click.echo(f"count={len(when)}")
        for d in when:
            click.echo(d.isoformat())

    return cli


def _nargs_cli():
    @click.command()
    @click.option("--span", type=click.DateTime(), nargs=2, envvar="SPAN")
    def cli(span):
        if span is None:
            click.echo("none")
        else:
            click.echo(" | ".join(d.isoformat() for d in span))

    return cli


def test_whitespace_envvar_list_still_works(runner):
    result = runner.invoke(
        _multi_cli(), [], env={"WHEN": "2020-01-01 2021-02-03"}
    )
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        "count=2",
        "2020-01-01T00:00:00",
        "2021-02-03T00:00:00",
    ]


def test_command_line_values_unchanged(runner):
    result = runner.invoke(
        _multi_cli(), ["--when", "2020-01-01", "--when", "2020-01-02 10:00:00"]
    )
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        "count=2",
        "2020-01-01T00:00:00",
        "2020-01-02T10:00:00",
    ]


def test_fault_csv_list_matches_canonical(runner):
    canonical = runner.invoke(
        _multi_cli(), [], env={"WHEN": "2020-01-01 2020-02-03 2021-12-31"}
    )
    csv = runner.invoke(
        _multi_cli(), [], env={"WHEN": "2020-01-01, 2020-02-03,2021-12-31"}
    )
    assert canonical.exit_code == 0, canonical.output
    assert csv.exit_code == 0, csv.output
    assert csv.output == canonical.output
    assert csv.output.splitlines()[0] == "count=3"


def test_fault_csv_list_with_spaced_datetimes(runner):
    result = runner.invoke(
        _multi_cli(),
        [],
        env={"WHEN": " 2020-01-01 10:00:00, 2020-01-02T11:30:00 "},
    )
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        "count=2",
        "2020-01-01T10:00:00",
        "2020-01-02T11:30:00",
    ]


def test_fault_csv_list_nargs(runner):
    result = runner.invoke(
        _nargs_cli(), [], env={"SPAN": "2020-01-01, 2020-01-02 03:04:05"}
    )
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "2020-01-01T00:00:00 | 2020-01-02T03:04:05"


def test_fault_csv_list_split_direct():
    assert DateTime().split_envvar_value("a, b ,c") == ["a", "b", "c"]


def test_fault_json_list(runner):
    result = runner.invoke(
        _multi_cli(),
        [],
        env={"WHEN": '["2020-01-01", "2020-02-03 04:05:06"]'},
    )
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        "count=2",
        "2020-01-01T00:00:00",
        "2020-02-03T04:05:06",
    ]


def test_fault_json_list_empty(runner):
    result = runner.invoke(_multi_cli(), [], env={"WHEN": "[]"})
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == ["count=0"]


def test_fault_json_list_split_direct():
    assert DateTime().split_envvar_value(' ["x", " y "] ') == ["x", "y"]


def test_fault_garbage_csv_item_named(runner):
    result = runner.invoke(
        _multi_cli(), [], env={"WHEN": "2020-01-01,notadate"}
    )
    assert result.exit_code == 2
    assert "--when" in result.output
    assert "'notadate'" in result.output


def test_fault_garbage_invalid_json(runner):
    result = runner.invoke(_multi_cli(), [], env={"WHEN": "[2020"})
    assert result.exit_code == 2
    assert "--when" in result.output
    assert "[2020" in result.output
    assert "JSON list" in result.output


def test_fault_garbage_json_non_strings(runner):
    result = runner.invoke(_multi_cli(), [], env={"WHEN": "[1, 2]"})
    assert result.exit_code == 2
    assert "--when" in result.output
    assert "[1, 2]" in result.output
    assert "JSON list" in result.output
