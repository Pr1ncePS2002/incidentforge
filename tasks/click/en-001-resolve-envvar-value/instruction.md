## Validate the environment variable names a parameter reads

The `envvar=` setting of `click.option(...)` and `click.argument(...)` can be a single string or a list of names. Click currently passes these names to `os.environ` without checking them. A mistyped name, such as an empty entry in the list, a name containing `=`, or a name containing a space, fails silently: the parameter never reads a value, or it reads a variable that no shell can export in the usual way. When several deployments share one process environment (for example `STAGING_URL` and `PROD_URL`), a mangled name can also make two parameters read the same variable.

Add validation of these names when click reads the parameter's value from the environment. This happens in `Parameter.resolve_envvar_value` in `src/click/core.py`, so it covers both options and arguments. It runs whenever the parameter falls back to the environment because no value was given on the command line.

### Rules

Every name listed in `envvar` (the single string, or each entry of a list or tuple) must:

- not be empty (`""` as an entry of a list or tuple is rejected),
- not contain the `=` character,
- not contain any whitespace character (space, tab, newline, ...),
- not contain a NUL character.

If any name breaks a rule, raise a **`ValueError`**. Every listed name is checked before any environment lookup happens, so an invalid entry is rejected even if an earlier entry in the list would have supplied a value. The error message must contain:

- the word `envvar`,
- the `repr` of the offending name (for example `'MY VAR'` or `'A=B'`),
- the `repr` of the parameter's name (for example `'token'`).

This is a developer error, not a usage error. It is not converted into a `UsageError`, so it reaches the caller (and appears as `result.exception` when invoked through `CliRunner`).

### Unchanged behaviour

- `envvar=None` and `envvar=""` (a single empty string) still mean "no environment variable", and no error is raised.
- Valid names (letters, digits, underscores, and other non-whitespace characters other than `=`) are read exactly as before, including the "first non-empty value wins" rule for lists.
- Names derived from `auto_envvar_prefix` (for example `APP_LOG_LEVEL` for `--log-level` with prefix `APP`) stay exactly the same.
- Different names for the same logical setting (for example `STG_URL` and `PRD_URL`) keep reading their own separate variables.

No new public symbol is added. The behaviour is reached through `click.option(..., envvar=...)` and `click.argument(..., envvar=...)`.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
