## Validate `nargs` when a parameter is declared

At the moment, `click.Parameter` (and so `click.Option`, `click.Argument`, `@click.option` and `@click.argument`) accepts some `nargs` declarations that can never work. The mistake only shows up later, when parsing goes wrong. Add two checks to `Parameter.__init__` in `src/click/core.py`. They run when the parameter is constructed, which for the decorators means when the command is declared. They go next to the existing `nargs`/composite-type check and the `required`/`deprecated` check.

### 1. `nargs` below -1

`nargs` means a fixed count of values (`1`, `2`, ...) or "any number of values" (`-1`). Any value **less than -1** (for example `-2` or `-3`) has no meaning. Reject it with a `ValueError`. The message must contain the word `nargs` and the value that was given (for example `-2`).

Boundary rule: **`nargs=-1` is the smallest value allowed.** A value equal to -1 is accepted, so `@click.argument("files", nargs=-1)` keeps working exactly as it does now. Only values strictly below -1 are rejected.

### 2. `multiple=True` together with `nargs=-1`

A parameter cannot both repeat (`multiple=True`) and take an open-ended number of values (`nargs=-1`). Reject this combination with a `ValueError` whose message names both keyword arguments: it must contain `multiple` and `nargs`.

For `click.Option(..., multiple=True, nargs=-1)` and `@click.option(..., multiple=True, nargs=-1)`, this new `ValueError` is raised instead of the generic error that options give today for `nargs=-1`. `click.Option(..., nargs=-1)` without `multiple` keeps its current behaviour.

### Must keep working

- `@click.argument(..., nargs=-1)` with zero or more values.
- Options with `multiple=True` and the default `nargs`, or with a fixed `nargs` such as `2` (which produce a tuple of tuples).
- Options and arguments with a fixed `nargs >= 1`.
- Every combination that click's existing test suite accepts.

No new public names are added. The errors are plain `ValueError`s raised from the constructors.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
