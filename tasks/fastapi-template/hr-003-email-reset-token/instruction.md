# Reload password-reset link settings at runtime, as one pair

Password-reset emails depend on two settings in `app.core.config.Settings`:

- `EMAIL_RESET_TOKEN_EXPIRE_HOURS` sets how long the reset token is valid. The email also prints it as "valid for N hours".
- `FRONTEND_HOST` is the host that the reset link points to.

Both are read once, when the settings are built at startup. If an operator wants a shorter reset window or needs to move the frontend to a new host, today they must redeploy. The two values also belong together: an email whose link uses the new host but whose token uses the old lifetime (or the reverse) is confusing and hard to debug. Add a runtime reload path for these two values.

## Requirements

1. Add a method `Settings.reload_password_reset_settings(raw)`. `raw` is a mapping from setting name to a raw value, as an operator or config watcher would supply it. Values may be strings, as they come from an environment or config file, or ints. Ignore any keys other than `EMAIL_RESET_TOKEN_EXPIRE_HOURS` and `FRONTEND_HOST`.
2. Add a method `Settings.get_password_reset_settings()` that returns the current pair as a tuple `(email_reset_token_expire_hours: int, frontend_host: str)`. The pair must be read together, so a caller never gets one value from before a reload and the other from after it, even while another thread is reloading.
3. After a successful reload, the next read returns the new values. This applies to the accessor and to plain attribute reads (`settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS`, `settings.FRONTEND_HOST`) on the **same** settings object that existing code already imported. No restart and no re-import.
4. Validation:
   - `EMAIL_RESET_TOKEN_EXPIRE_HOURS` must be an integer from 1 to 720 inclusive. A numeric string such as `"6"` is accepted and stored as an `int`. Booleans, floats, non-numeric strings and out-of-range numbers are invalid.
   - `FRONTEND_HOST` must be a URL with an `http` or `https` scheme and a non-empty host, such as `https://app.example.com`. Anything else is invalid, for example `localhost:5173`, `ftp://...` or `http://`.
5. An invalid reload raises `ValueError`. The message must name **every** offending key. The whole reload is rejected: neither value changes, even if the other value in the same reload was valid, and the last good pair keeps serving.
6. Unset keys: a key that is missing from `raw`, or whose value is `None` or an empty or whitespace-only string, falls back to its documented default (`48` and `http://localhost:5173`). It does not keep its previous value.
7. Startup behaviour with no reload stays exactly as it is today. This includes not adding any new startup validation. The existing test suite must still pass.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
