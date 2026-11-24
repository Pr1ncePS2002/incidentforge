In click the typed binding is a parameter type: `ParamType.convert` turns the string a user typed (or an
environment variable value) into a python value and calls `self.fail(...)` on bad input, which click shows
as a usage error (exit code 2) naming the option. "Settings construction" in the generic text means the
command invocation; "the key" is the option name as the user sees it (e.g. `--timeout`).

Good features on this surface: extend the type to accept a realistic spelling it rejects today (unit
suffixes, digit separators, case or surrounding whitespace, an alternative list syntax) or add a new
public parameter type next to it (for example a duration or byte-size type) that reuses the same failure
path. The canonical spelling must keep giving the same value, and garbage must fail with a message that
names the option and quotes the bad value. Map the catalogue faults to inputs this type receives; a list
fault applies to `multiple=True` or `nargs` options and to `ParamType.split_envvar_value` for env values.
Do not re-add what the type already accepts: read its accepted values in the excerpt first.
