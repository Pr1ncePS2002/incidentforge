In click the "settings" are option values that may come from an environment variable, and "startup" is
the command invocation. Today an environment variable that is set but empty is treated as unset, a
whitespace-only value is passed through, and a missing required value is only reported for the first
option that lacks it.

Good features: an opt-in keyword (for example on `click.option`) that rejects an empty, whitespace-only
or placeholder value coming from the environment with a usage error naming the variable and the option,
report every missing required option in one error instead of only the first, or require an option only
when another flag is on. Keep the default behaviour unchanged for parameters that do not opt in.
