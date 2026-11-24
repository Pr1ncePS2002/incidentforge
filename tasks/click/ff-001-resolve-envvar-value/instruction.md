## Feature: strict environment variable values for parameters

Today, when a parameter reads its value from an environment variable (`envvar=`), click treats a variable set to an empty string as if it were unset. A whitespace-only value, or a template placeholder left over from a `.env` template such as `changethis` or `<fill-me>`, is passed to the command unchanged. The command starts anyway and only fails later, when the value is used. We want parameters to be able to opt in so that this kind of value stops the command at invocation time.

### Opt-in

Add support for a `strict_envvar` attribute on `click.core.Parameter`. This covers `click.Option` and `click.Argument`. When the attribute is missing or false, behaviour must stay exactly as it is now. A developer turns strict mode on by subclassing and passing the subclass with `cls=`:

- `class StrictOption(click.Option): strict_envvar = True`, used as `@click.option("--token", envvar="APP_TOKEN", cls=StrictOption)`
- an `Argument` subclass with `strict_envvar = True` works the same way.

### Behaviour when `strict_envvar` is true

Whenever the parameter resolves its value from its own `envvar` setting (`Parameter.resolve_envvar_value`), check **every** variable named in `envvar` that is present in the environment. `envvar` can be a single name or a list of names. A present variable is *offending* if its value:

- is the empty string, or
- is whitespace only, or
- after stripping surrounding whitespace and comparing case-insensitively, equals one of `changeme`, `change-me`, `change_me`, `changethis`, `fixme`, `placeholder`, `replaceme`, `tbd`, `todo`, `xxx`, or
- after stripping, starts with `<` and ends with `>` (for example `<fill-me>`, `<your-token>`).

Variables that are absent from the environment are not offending. They keep today's behaviour: fall through to the next variable, then to the default, or to the usual missing-parameter error if the parameter is required.

If one or more variables are offending, raise a single `click.BadParameter` for this parameter (pass `ctx` and `param`). Its message must name **every** offending variable, so if several are bad they are all reported in that one error. Variables that are not offending must not be named. The standard formatting then adds the parameter hint, so a user running the command sees exit code 2 and output like `Error: Invalid value for '--token': ...`. That output contains the option name (or the argument's metavar, such as `NAME`) and each offending variable name. Wrap the message in `_()`.

Values that merely contain a placeholder word, such as `todo-list` or `my-changeme-token`, are valid. If no variable is offending, the value is resolved exactly as it is now: the first non-empty value is returned.

### Unchanged

- Parameters without `strict_envvar` (or with it set to false) behave exactly as they do now. An empty variable is still treated as unset, and whitespace or placeholder values are still passed through.
- Values given on the command line, defaults, and absent environment variables all work as before.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
