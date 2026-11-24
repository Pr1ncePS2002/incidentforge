Click works out the name of the environment variable that triggers shell completion (`_{PROG_NAME}_COMPLETE`) inline in `Command._main_shell_completion`. Today only `-` and `.` are normalised, so a program name such as `my app` or `my+app` produces a name that is not a valid environment variable (`_MY APP_COMPLETE`). No shell can set that variable, so completion can never fire. An empty or punctuation-only program name produces a meaningless name like `__COMPLETE` that is not tied to any program. Also, the name can't be inspected or customised without passing `complete_var` on every call.

Please add a public, overridable helper and route the completion variable name through it.

## New API

Add a method `get_complete_var(self, prog_name: str) -> str` to `click.Command` (defined in `click.core`; `click.Group` inherits it).

- It returns `"_" + <normalised prog_name> + "_COMPLETE"`, upper-cased.
- Normalising replaces every character that is not an ASCII letter (`A-Z`, `a-z`), an ASCII digit or `_` with `_`. That covers `-`, `.`, spaces, `+`, `/` and non-ASCII letters such as `é`.
- Names click derives today for plain program names must not change. For example, `cli` gives `_CLI_COMPLETE`, `foo-bar.baz` gives `_FOO_BAR_BAZ_COMPLETE` and `my_tool2` gives `_MY_TOOL2_COMPLETE`. New examples: `my app` gives `_MY_APP_COMPLETE`, `my+app/x` gives `_MY_APP_X_COMPLETE` and `café` gives `_CAF__COMPLETE`.
- If `prog_name` contains no ASCII letter or digit at all (for example `""`, `"   "` or `"---"`), raise `ValueError`. The message must contain the word `prog_name`.

## Use it when running a command

- When `Command.main` (and so `CliRunner.invoke`) is called without `complete_var`, the completion variable name must come from `self.get_complete_var(prog_name)`. A subclass that overrides `get_complete_var` therefore changes the variable that triggers completion, and the default `_{PROG}_COMPLETE` variable is then ignored.
- An explicit `complete_var` passed to `main` / `invoke` still takes priority over `get_complete_var`.
- Validate an explicit `complete_var` before reading the environment. It must be a valid environment variable name: non-empty, only ASCII letters, digits and `_`, and not starting with a digit. Otherwise raise `ValueError` with a message that contains the word `complete_var`. Examples of invalid values: `""`, `"BAD VAR"`, `"1ABC"`, `"A=B"`.
- Both `ValueError`s are raised whenever the command is invoked, even if no completion variable is set in the environment. (`CliRunner.invoke` reports them through `result.exception`.)
- Different program names that differ in letters or digits must still produce different variable names. Completion for one program must not be triggered by another program's variable.

Everything else about completion (instruction values such as `zsh_source`, exit codes, the generated scripts) is unchanged.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
