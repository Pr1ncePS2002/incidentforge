# Accept the duration spellings operators actually write

The backend reads two expiry durations in `app.core.config.Settings`:

- `ACCESS_TOKEN_EXPIRE_MINUTES`: an integer number of **minutes** (default 8 days = `11520`)
- `EMAIL_RESET_TOKEN_EXPIRE_HOURS`: an integer number of **hours** (default `48`)

Operators often write these with a unit suffix, for example `ACCESS_TOKEN_EXPIRE_MINUTES=2h` or `EMAIL_RESET_TOKEN_EXPIRE_HOURS=2d`. Right now that crashes the service at startup with a generic integer parsing error. Make both settings accept unit-suffixed durations and convert them to the setting's own unit. Input that cannot be parsed must still fail at startup, with a clear message.

Requirements:

1. Both settings accept a whole number followed by a unit suffix: `s` (seconds), `m` (minutes), `h` (hours) or `d` (days). The suffix is case-insensitive. Whitespace around the value, and between the number and the suffix, is allowed (for example `" 45 M "`).
2. The value is converted to the setting's unit, so `ACCESS_TOKEN_EXPIRE_MINUTES="2h"` gives `120`, `"1d"` gives `1440` and `"120s"` gives `2`. `EMAIL_RESET_TOKEN_EXPIRE_HOURS="2d"` gives `48` and `"3600s"` gives `1`. The result is a plain `int` equal to what the canonical integer form would give.
3. If the duration does not convert to a whole number of the setting's unit, it must be rejected. Examples: `"30s"` for the minutes setting, or `"90m"` for the hours setting.
4. Anything else that is not a plain integer must be rejected. This includes an unknown suffix (`"5x"`), a fractional number (`"1.5h"`), a spelled-out unit (`"30 minutes"`) and non-numeric text (`"abc"`).
5. Rejection means constructing `Settings` raises a `ValueError` (pydantic's `ValidationError` counts). The error message must include the setting's name and the offending value as written.
6. The new spellings must work both from environment variables and from keyword arguments passed to `Settings(...)`.
7. The canonical forms keep working exactly as before: integers, plain integer strings such as `"60"`, and the defaults when nothing is set. The existing test suite must still pass.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
