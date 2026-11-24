## Add a `Duration` parameter type

Timeouts, intervals and TTLs are common CLI options. Today they have to be declared as `type=int` or `type=float`, so a user who writes `--timeout 30s` or sets `APP_TIMEOUT=5m` gets an error. Add a parameter type that accepts the spellings people actually use.

### Public API

- Add a new class `Duration` to `click.types`, so it is usable as `click.types.Duration`. It is a `click.ParamType` subclass and takes no constructor arguments: `type=click.types.Duration()`.
- Its `name` is `"duration"`, so the help metavar is `DURATION`.
- A successful conversion returns a `datetime.timedelta`.

### Accepted input

- **Canonical form:** a plain number is a number of seconds. `"30"` becomes `timedelta(seconds=30)` and `"2.5"` becomes `timedelta(seconds=2.5)`.
- **Unit suffixes:** a number followed by `s` (seconds), `m` (minutes), `h` (hours) or `d` (days). For example, `"30s"`, `"5m"`, `"1.5h"` and `"1d"`. The suffix is case-insensitive (`"2H"` is the same as `"2h"`). Every suffixed spelling must give the same `timedelta` as the equivalent plain number of seconds (`"5m"` equals `"300"`).
- Whitespace around the value is ignored (`"  10m  "` is 10 minutes).
- Values that are already Python values also convert: an `int` or `float` (not `bool`) is a number of seconds, and a `datetime.timedelta` is returned unchanged. This means defaults such as `default=45`, `default="1m"` and `default=timedelta(...)` all work.
- Values from environment variables (`envvar=...`) follow the same rules.

### Rejected input

The following must fail through the type's normal failure path (`self.fail`), which raises `click.BadParameter`:

- anything that is not a number with an optional single suffix, such as `"5x"`, `"abc"`, `"5 minutes"`, `"s"` or the empty string
- negative durations, such as `"-5s"`
- non-finite values, such as `"nan"`, `"inf"` or `"1e400s"`
- values too large for `timedelta`

The error message must quote the bad value using its `repr` and contain the words `is not a valid duration`. For example: `'5x' is not a valid duration.` Wrap the message in `_()` like the other messages in the module. When a command is invoked, this is a usage error with exit code 2, and the output names the option (for example `Invalid value for '--timeout'`) and the offending value. This applies whether the value came from the command line or from an environment variable.

Existing parameter types, including `FuncParamType`, must behave exactly as before.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
