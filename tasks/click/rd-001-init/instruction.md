`click.formatting.HelpFormatter` works out its width when `width` is not given. It takes the terminal width (`shutil.get_terminal_size()`, which honours `COLUMNS`), caps it at `max_width` (default 80), subtracts 2, and then raises it to at least 50. The floor of 50 is hardcoded. Also, zero or negative widths are accepted silently and only cause trouble later, during layout.

Change `HelpFormatter.__init__` (in `click.formatting`) so that the floor can be configured and impossible settings are rejected when the formatter is built.

### New keyword

Add a keyword argument `min_width: int | None = None` to `HelpFormatter.__init__`, after `max_width`.

- If `min_width` is `None`, the floor stays at 50, as it is today.
- When `width` is not given (and `click.formatting.FORCED_WIDTH` is `None`), the width is:

  `max(min(terminal_columns, max_width) - 2, min_width)`

  Here `max_width` defaults to 80 and `min_width` defaults to 50. For example, with `COLUMNS=40` and `min_width=30`, the width is 38. With `COLUMNS=10` and `min_width=20`, the width is 20.
- An explicit `width` is still used exactly as given.

### Validation (when the formatter is built)

- If `width`, `max_width` or `min_width` is given (not `None`) and is zero or negative, raise `ValueError`. The message must contain the argument name (`width`, `max_width` or `min_width`) and the value that was given.
- If `min_width` is given and is greater than the effective `max_width`, raise `ValueError`. The effective `max_width` is the value passed, or 80 if none was passed. The message must contain both `min_width` and `max_width`, and both numbers.
- If `min_width` is not given, nothing changes. For example, `max_width=40` with no `min_width` still produces a width of 50, as it does today.

`Context.make_formatter` passes `terminal_width` and `max_content_width` through as `width` and `max_width`. So a zero or negative `terminal_width` or `max_content_width` in `context_settings` now raises this `ValueError` when help is rendered.

When nothing is configured, the defaults must stay the same.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
