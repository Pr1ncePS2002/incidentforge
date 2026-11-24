In click the names built at runtime are environment variable names: `auto_envvar_prefix` plus the
option name in `Option.resolve_envvar_value` (prefix normalised in `Context.__init__`), the nested
command prefix `PARENT_CHILD`, the `_{PROG}_COMPLETE` completion variable, and the app directory built by
`click.get_app_dir`. "The environment" in the generic text is the prefix or program name these names are
scoped by; a collision means two options or commands resolving the same variable name, and an ambiguous
separator means characters such as `-`, `.` or spaces leaking into a variable name.

Good features: normalise every character that is not valid in an environment variable name, reject at
declaration time two parameters of one command that resolve the same environment variable, expose a
helper that returns the variable name a parameter reads, or make the completion variable name derivable
and overridable. Names click derives today for plain identifiers must stay exactly the same.
