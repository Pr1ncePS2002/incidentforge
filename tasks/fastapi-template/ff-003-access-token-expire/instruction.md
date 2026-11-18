# Fail fast on unusable token lifetimes

`app.core.config.Settings` holds two token lifetimes:

- `ACCESS_TOKEN_EXPIRE_MINUTES` sets how long a login access token lasts.
- `EMAIL_RESET_TOKEN_EXPIRE_HOURS` sets how long a password-reset token lasts.

Both values go into `timedelta(...)` on every login and every password-reset request. Today the settings accept values that break the service later:

- A lifetime of `0` or a negative number lets the app start, but every token it issues has already expired.
- A huge value such as `99999999999` lets the app start, then makes `datetime + timedelta` overflow on the first login.
- A blank value or a template placeholder fails only with pydantic's generic "unable to parse string as an integer" message. That message does not tell the operator that the variable was never filled in.

Make the settings reject bad token lifetimes when they are built, with a clear message.

## Requirements

1. **Blank values.** If either setting is given a string that is empty or only whitespace (for example `"   "`), it must be rejected. The error text must contain the word `blank`.
   - An environment variable set to exactly `""` keeps today's behaviour: it is ignored and the default is used. This comes from the existing `env_ignore_empty=True`.
2. **Placeholders.** If either setting still holds a template placeholder, it must be rejected. The error text must contain the word `placeholder`. Ignore surrounding whitespace and letter case when checking. These count as placeholders:
   - `changethis`, `changeme`, `change-me`, `todo`, `tbd`, `fixme`, `fill-me`, `fill_me`
   - any value wrapped in angle brackets, such as `<fill-me>` or `<minutes>`
3. **Allowed ranges.**
   - `ACCESS_TOKEN_EXPIRE_MINUTES` must be a whole number from 1 to 525600 inclusive (one year).
   - `EMAIL_RESET_TOKEN_EXPIRE_HOURS` must be a whole number from 1 to 8760 inclusive (one year).
   - Any value outside these ranges must be rejected.
4. **Timing.** Rejection happens when `Settings(...)` is constructed, not when a token is first issued. Constructing `Settings` must raise a `ValueError`; pydantic's `ValidationError` counts.
5. **One error for all problems.** If both settings are bad at once, for any mix of the reasons above, a single error must name both `ACCESS_TOKEN_EXPIRE_MINUTES` and `EMAIL_RESET_TOKEN_EXPIRE_HOURS`.
6. **Valid values unchanged.**
   - The shipped defaults (`ACCESS_TOKEN_EXPIRE_MINUTES` = 11520 and `EMAIL_RESET_TOKEN_EXPIRE_HOURS` = 48) must still load.
   - Valid values must load whether they arrive as integers or as numeric strings from the environment (for example `"120"`).
   - The existing test suite must still pass.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
