In click the fields are the keyword arguments of one declaration: `click.Option(...)`/`@click.option(...)`
(flag, count, multiple, nargs, prompt, default, envvar, required), a range type such as
`click.IntRange(min, max, min_open, max_open, clamp)`, or two options of the same command. "Validation
time" means construction of the parameter or type (raise `TypeError`/`ValueError` from the constructor,
like the existing checks in `Option._validate`) or, for options that depend on each other at runtime, the
command invocation (raise `click.UsageError`/`click.BadParameter`, exit code 2, message naming both
options).

Good features: reject an impossible range (min above max, an open bound equal to the other bound),
reject keyword combinations that cannot work together and are not checked yet, or add a declarative way
for one option to require or exclude another with a clear usage error. The error must name both
arguments. State in the instruction whether equal values are allowed. Keep every combination that click's
test suite accepts today working.
