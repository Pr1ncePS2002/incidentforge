Add two new construction-time checks to `click.Option` (and therefore `@click.option`). They reject keyword combinations that are each valid alone but cannot work together. Today click accepts both combinations silently and then behaves wrongly only when the command runs.

1. **`confirmation_prompt` on a boolean flag.** A boolean flag is prompted with a yes/no confirmation, so a confirmation prompt (re-entering the value) can never apply. Reject any truthy `confirmation_prompt` (`True` or a non-empty string) on an option that is a boolean flag. This covers `is_flag=True` with the default boolean `flag_value`, and on/off pairs such as `"--shout/--no-shout"`. Raise `TypeError` when the option is constructed, which for the decorator means when the decorated command is built. The message must contain both `confirmation_prompt` and `is_flag`. Nothing else changes:
   - `confirmation_prompt` on a non-flag option such as a string option with `prompt=True` keeps working.
   - A boolean flag with `prompt=True` and no confirmation prompt keeps working.
   - A falsy `confirmation_prompt` (`False`, the default) is still accepted on boolean flags.

2. **Negative `default` on a counting option.** A `count=True` option counts how many times it was given, so its value can never be negative. Reject an explicit integer `default` below zero on an option with `count=True`. Raise `TypeError` at construction time. The message must contain both `default` and `count`.
   - **Boundary rule:** a default equal to zero is allowed, and so is any positive integer. Only values strictly below `0` are rejected.
   - When no default is given, the default stays `0`, so a counting option still reports `0` when it is not passed.
   - Non-integer defaults (for example callables) are not checked.

Both checks go in `Option._validate` next to the existing keyword-combination checks in `src/click/core.py`. They use the same exception class (`TypeError`) and the same style as those checks. No new public names are added. Everything stays reachable through `click.Option` and `click.option`.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
