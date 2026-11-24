## output contract (pallets/click)

The repository is the click library itself, installed in editable mode (`pip install -e .`). There is no
application, service, database or settings class: "settings" are the arguments a developer passes to
`click.option`/`click.argument`/parameter types and the values an end user passes on the command line or
through environment variables. "Startup" means declaring the command (decorator time) or invoking it.

Reply with exactly one json object and nothing else (no prose, no code fences). Keys:

- `title` (string): short task title, lower case, no trailing period, phrased as new behaviour
  (e.g. "add a duration parameter type", "reject an int range whose min exceeds its max").
- `instruction` (string, markdown): a feature request for click maintainers. Say what to add or change:
  the public api (new parameter type, new keyword argument, new error), the accepted inputs, the exact
  error behaviour (exception class, which words the message must contain), and the boundary rules,
  precisely enough that the hidden tests are fair. Write it as new behaviour ("add", "support",
  "reject ... with a clear error"), never as a bug report, regression or fix. Name every new public
  symbol and keyword the tests use, and the module it is imported from (e.g. `click.types.Duration`). Never include
  code from the solution, never mention the hidden tests.
- `solution_patch` (string): a unified diff (`git diff` format, `--- a/<path>` / `+++ b/<path>` headers,
  paths relative to the repository root such as `src/click/types.py`, correct `@@` hunk line counts) that
  applies with `git apply` on the pinned commit. Context lines must match the pinned code exactly. Change
  only library code under `src/click/`; do not add or edit test files, docs or CHANGES.md in the patch.
  You only see the excerpt above, so edit only code shown there (or insert next to it); every context line
  must be copied from the excerpt. Do not edit `src/click/__init__.py` or any file you were not shown: a new
  public name is imported from the module that defines it (e.g. `from click.types import Duration`), and the
  instruction says so. Keep click's style: type hints on public signatures and `_()` around user-facing
  messages where the surrounding code uses it.
- `feature_tests` (object): file name -> file content. One or two pytest files named `test_*.py`; a bare
  file name is placed in the repository's `tests/` directory, so click's `runner` fixture (a
  `click.testing.CliRunner`) from `tests/conftest.py` is available. Import from `click` only
  (`import click`, `from click.testing import CliRunner`, `from click.types import ...`). Exercise the feature the way a user would: build a
  small command with `@click.command()` and `@click.option(...)`, invoke it with
  `runner.invoke(cli, [...])` or `runner.invoke(cli, [...], env={...})`, and assert on `result.exit_code`,
  `result.output` and `result.exception`; construction-time errors are asserted with `pytest.raises`.
  Set environment variables through `runner.invoke(..., env=...)` or `monkeypatch.setenv`, never by
  mutating `os.environ`. The suite runs with `filterwarnings = error`, so tests and patch must not emit any
  warning (no deprecated api, no unclosed files). They must fail on the pinned commit and pass with the
  patch applied. Each fault you list below needs at least one test that injects it, named
  `test_fault_<fault_id>` (fault id with `-` turned into `_`, an extra suffix is fine, e.g.
  `test_fault_garbage_names_value`). Tests of normal, unchanged behaviour must not contain the word `fault`
  in their names (e.g. `test_plain_int_still_parses`). Tests must be deterministic, use no network, no
  sleeps, no real terminal, editor or pager, and no files outside `tmp_path`.
- `fault_cases` (array of strings): one line per injected fault, starting with its catalogue id, e.g.
  `"garbage: --timeout 5x is rejected naming --timeout and 5x"`.
- `difficulty` (string): `easy`, `medium` or `hard`.

The feature must not already exist in click, neither at the pinned commit nor on click's main branch:
if this surface already supports the behaviour (for example `BoolParamType` already accepts yes/no/on/off),
pick a different behaviour it does not yet have. Existing behaviour that click's own test suite checks
must keep working unchanged; extend rather than redefine.

Already on click main after the pinned release, so never propose them: a `context_settings` argument for
`CliRunner.invoke`, `Parameter.spec`, deprecation warnings for parameter names that are not lower-case
python identifiers, help text that no longer breaks lines inside hyphenated words, and `CliRunner` echoing
`\x04`/`\x1a` input as `^D`/`^Z`.
