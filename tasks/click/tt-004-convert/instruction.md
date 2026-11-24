## Support comma-separated and JSON array lists for `DateTime` values from environment variables

When a `click.DateTime` option takes more than one value (`multiple=True` and/or `nargs > 1`) and the values come from an environment variable (`envvar=...` or `auto_envvar_prefix`), click currently splits the variable on whitespace. That does not work for datetimes. The default format `%Y-%m-%d %H:%M:%S` contains a space, and operators usually write lists as `2020-01-01, 2020-02-03` or as a JSON array. Today both spellings end in a confusing "does not match the formats" error.

Add an override of `split_envvar_value(rv: str)` to `click.types.DateTime` (also available as `click.DateTime`) with these rules, applied in this order:

1. **JSON array.** If the value starts with `[` after surrounding whitespace is stripped, parse it as JSON. It must be a JSON array whose items are all strings. Each item is stripped of surrounding whitespace and returned in order. `[]` returns an empty list.
2. **Comma-separated.** Otherwise, if the value contains a comma, split it on `,` and strip surrounding whitespace from each item. For example, `"2020-01-01, 2020-02-03,2021-12-31"` becomes `["2020-01-01", "2020-02-03", "2021-12-31"]` and `"2020-01-01 10:00:00, 2020-01-02T11:30:00"` becomes `["2020-01-01 10:00:00", "2020-01-02T11:30:00"]`.
3. **Otherwise.** Keep the current behaviour: split on whitespace, as `ParamType.split_envvar_value` does.

Every item is then converted by `DateTime.convert` as usual. Each spelling must give exactly the same `datetime` values as the existing whitespace-separated spelling and as passing the values on the command line.

### Errors
- If a value starts with `[` but is not valid JSON, or is JSON that is not an array of strings (for example `[2020` or `[1, 2]`), fail through the type's normal failure path (`ParamType.fail`, which raises `click.BadParameter`). The message must contain the offending raw value (repr-quoted) and the words `JSON list`. The command then exits with code 2 and a usage error that names the option (for example `--when`).
- If a comma-separated item cannot be parsed as a datetime, the usual `DateTime` error is raised for that single item. For example, `2020-01-01,notadate` produces `'notadate' does not match the formats ...`, which quotes only the bad item. The usage error names the option, and the exit code is 2.

### Unchanged
- Whitespace-separated env var lists (`"2020-01-01 2021-02-03"`) still work.
- Values given on the command line are not affected.
- Single-value (`nargs=1`, not `multiple`) options read from env vars are not split, as before.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
