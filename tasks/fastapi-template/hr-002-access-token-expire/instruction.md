# Change token lifetimes at runtime without a restart

Two values in `app.core.config.Settings` control how long the backend's tokens stay valid:

- `ACCESS_TOKEN_EXPIRE_MINUTES`: lifetime of the access tokens issued by the login endpoint. Default `60 * 24 * 8`.
- `EMAIL_RESET_TOKEN_EXPIRE_HOURS`: lifetime of password-reset tokens. Default `48`.

Today the only way to change either value is to edit the environment and redeploy. During a security incident, operators need to shorten token lifetimes right away, and the change must apply to the very next token issued.

Add a module `app.core.runtime_config` that exposes the following.

1. `reload_token_lifetimes(raw)` takes a mapping of raw values keyed by the setting names above (`"ACCESS_TOKEN_EXPIRE_MINUTES"`, `"EMAIL_RESET_TOKEN_EXPIRE_HOURS"`). It validates both values and then applies them. Values can be ints or strings (for example `"30"`). Any other keys in the mapping are ignored. On success it returns the new lifetimes (same shape as in point 2).
2. `get_token_lifetimes()` returns the lifetimes currently in effect as a named tuple with the fields `access_token_expire_minutes` and `email_reset_token_expire_hours`. The two fields must always be a consistent pair.

Required behaviour:

- **Takes effect immediately.** After a successful reload, the next read returns the new values, with no restart and no re-import. This applies to `get_token_lifetimes()`, to `settings.ACCESS_TOKEN_EXPIRE_MINUTES` / `settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS` on the shared `app.core.config.settings` object (including in modules that imported it at startup), and to tokens issued by `POST {API_V1_STR}/login/access-token`. For example, after reloading `ACCESS_TOKEN_EXPIRE_MINUTES` to `5`, a newly issued access token must expire about 5 minutes from now.
- **Validation.** Each value must be a positive integer (≥ 1). Booleans, floats, non-numeric strings, decimal strings such as `"1.5"`, zero and negative numbers are all invalid.
- **Invalid reload is rejected as a whole.** If any value is invalid, raise `ValueError`. The message must name every offending key. Neither value is changed, so the last good pair keeps serving.
- **Related values swap together.** A reload that changes both values applies both or neither. Readers must never see a new access-token lifetime paired with an old reset-token lifetime, or the other way round.
- **Unset keys fall back to defaults.** A key that is missing from the mapping, `None`, or an empty or blank string reverts to the default declared on `Settings`. It must not keep the previous runtime value.
- **No reload, no change.** Startup behaviour stays exactly as it is today. Constructing `Settings` with no overrides still gives the defaults above, and the existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
