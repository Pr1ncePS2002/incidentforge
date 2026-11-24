## Accept quoted spellings for boolean parameters

Boolean values often come from env files and config tooling that keeps the quotes. For example, `docker run --env-file` passes `APP_DEBUG="true"` through with the double quotes still in the value. Today `click.BOOL` (`click.types.BoolParamType`) rejects `"true"` and `'yes'` because the quotes are part of the string. The program then stops with a usage error, even though the operator clearly meant `true` or `yes`.

Extend `BoolParamType.convert` (used by `type=bool` and `type=click.BOOL` on options and arguments, whether the value comes from the command line or from an environment variable) so that it also accepts a value wrapped in **one matching pair of quotes**.

### Rules

- First, the value is looked up exactly as it is today. Every spelling that works now (`1/0`, `yes/no`, `true/false`, `on/off`, `t/f`, `y/n`, any case, surrounding whitespace, and the empty string meaning `False`) must keep giving the same result.
- If that lookup fails and the value is a string, strip the surrounding whitespace. If what remains is at least two characters long, starts and ends with the same quote character, and that character is `"` or `'`, remove that one pair of quotes and look up the inside again using the normal rules: case-insensitive, whitespace inside the quotes ignored, and the recognized words unchanged. So `"YES"`, `'off'`, `" 1 "` and ` "true" ` give the same value as `yes`, `off`, `1` and `true`. A quoted empty value (`""` or `''`) is `False`, the same as the empty string.
- Only one pair of quotes is removed. Doubly quoted values (`""yes""`), mismatched quotes (`"true'`), a single quote character on its own (`"`), and quoted text that is not a recognized boolean word (`"maybe"`) are still rejected.
- Rejection uses the existing failure path: a `click.BadParameter` usage error (exit code 2) whose message names the parameter (for example `--debug`), contains `is not a valid boolean`, and quotes the original value the user gave, including its quotes.

No new public names are added, and the set of recognized words and the listed "Recognized values" do not change.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
