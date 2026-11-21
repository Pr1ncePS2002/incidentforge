# Derive the password-reset link lifetime from configured bounds

The backend reads how long password-reset links stay valid from `EMAIL_RESET_TOKEN_EXPIRE_HOURS` in `app.core.config.Settings`. Today that setting falls back to a fixed built-in number. If a config change drops the key, or leaves it empty, nothing complains. The app quietly uses the hard-coded value, whatever the rest of the deployment is configured for. Nothing sets a floor or a ceiling either, so an operator can set a lifetime of zero, which breaks every reset link at once. They can also set one far longer than the security policy allows.

Change the settings so that the reset-link lifetime comes from configured limits, and so that impossible combinations stop the app at startup.

## Settings

- `EMAIL_RESET_TOKEN_MIN_EXPIRE_HOURS` (integer, default `1`): the shortest allowed lifetime.
- `EMAIL_RESET_TOKEN_MAX_EXPIRE_HOURS` (integer, default `168`): the longest allowed lifetime.
- `EMAIL_RESET_TOKEN_EXPIRE_HOURS` (integer, optional): the lifetime an operator chooses explicitly. It counts as unset when it is missing or set to an empty string.

## Required behaviour

1. **Explicit value:** if `EMAIL_RESET_TOKEN_EXPIRE_HOURS` is set and valid, it is used as given.
2. **Unset value, derived default:** if `EMAIL_RESET_TOKEN_EXPIRE_HOURS` is unset, the lifetime is derived instead of using a fixed constant:
   `ACCESS_TOKEN_EXPIRE_MINUTES // 240` (a quarter of the access-token lifetime, in whole hours), clamped to `[EMAIL_RESET_TOKEN_MIN_EXPIRE_HOURS, EMAIL_RESET_TOKEN_MAX_EXPIRE_HOURS]`.
   With the shipped defaults (8-day access tokens), this gives 48 hours, the same as today.
3. **Resolved value is stored on the settings:** after `Settings` is built, `settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS` must hold the resolved integer. Existing code that reads this attribute, such as reset-token generation and the reset email, then uses it without further changes.
4. **Startup rejection:** building `Settings` must raise a `ValueError` (pydantic's `ValidationError` counts) when:
   - `EMAIL_RESET_TOKEN_MIN_EXPIRE_HOURS` or `EMAIL_RESET_TOKEN_MAX_EXPIRE_HOURS` is zero or negative. The message names the offending setting.
   - `EMAIL_RESET_TOKEN_MIN_EXPIRE_HOURS` is greater than `EMAIL_RESET_TOKEN_MAX_EXPIRE_HOURS`. The message names both settings.
   - An explicit `EMAIL_RESET_TOKEN_EXPIRE_HOURS` is zero or negative. The message names `EMAIL_RESET_TOKEN_EXPIRE_HOURS`.
   - An explicit `EMAIL_RESET_TOKEN_EXPIRE_HOURS` is above the maximum or below the minimum. The message names `EMAIL_RESET_TOKEN_EXPIRE_HOURS` and the bound it breaks.
5. **Compatibility:** the default configuration still loads, and the existing test suite still passes.

## background

This protection comes from a public incident report (https://aws.amazon.com/message/74876-2/). What set that incident off: A configuration update accidentally deleted the minimum-healthy-hosts setting for the regional DNS resolver fleet. With the key gone, the system quietly used a very low built-in default, which let far too many resolver hosts be taken out of service.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
