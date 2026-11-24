## Expose and harden the automatic environment variable name of an option

When a command is run with `auto_envvar_prefix`, every `click.Option` reads a value from an environment variable named `{PREFIX}_{NAME}`. That prefix is how one program's options are kept apart from another program's options (for example `STAGING` and `PROD`, or a parent command and its subcommand). Today, though, there is no public way to ask an option which variable it reads. Two cases also go wrong without any warning:

* Characters other than `-` in the prefix or in a subcommand name (`.`, spaces, `/`, …) end up in the variable name as they are. For example, `auto_envvar_prefix="my.app"` makes click read `MY.APP_TOKEN`, which is not a usable shell variable name.
* An empty prefix, or one made only of separator characters such as `""`, `"-"` or `"__"`, quietly produces a name like `_TOKEN` that no other program prefix scopes.

### New public API

Add a method `get_auto_envvar_name(self, ctx: Context) -> str | None` to `click.core.Option`, so it is available on every option, for example `cli.params[0]`.

* The method returns the name of the variable that the option reads through `ctx.auto_envvar_prefix`. It must use the prefix of the context passed in, not the root context's prefix or a fixed default. For a subcommand `deploy` under a group run with prefix `app`, the result is `APP_DEPLOY_TOKEN`.
* It returns `None` in three cases: the context has no `auto_envvar_prefix`, the option was declared with `allow_from_autoenv=False`, or the option has no name.
* The name is `{prefix}_{NAME}`, where `NAME` is the option name in upper case. In both parts, replace every character that is not a letter, a digit or an underscore (as decided by `str.isalnum()`) with `_`. So prefix `my.app`, `my app` and `my/app` all give `MY_APP_TOKEN` for `--token`. A subcommand named `db.migrate` under prefix `app` gives `APP_DB_MIGRATE_TOKEN`.
* If the prefix contains no letter and no digit (for example `""`, `"-"`, `"__"` or `". "`), raise `ValueError`. The message must contain the setting name `auto_envvar_prefix`.

### Use it when resolving values

`Option.resolve_envvar_value` must use this method to build the variable it falls back to:

* With a valid prefix, read the normalised name and never the raw, unnormalised one. Do not read the bare option name without the prefix either.
* With an unusable prefix, invoking a command whose option falls back to its automatic variable raises that `ValueError`, so the command fails instead of running.
* A value given on the command line, and an explicit `envvar=`, still take precedence as they do today.

### Stability

Names for ordinary prefixes and option names must stay exactly as they are now: `auto_envvar_prefix="app"` with `--token` still reads `APP_TOKEN`, and `auto_envvar_prefix="my-app"` with `--user-name` still reads `MY_APP_USER_NAME`. Behaviour when no prefix is configured does not change.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
