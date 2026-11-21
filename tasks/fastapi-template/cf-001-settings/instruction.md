# Reject token-lifetime and SMTP settings that cannot work together

The backend loads its configuration through `app.core.config.Settings`. Today it accepts several combinations where each value is valid alone but the combination is not. The app starts normally and only misbehaves later:

- `ACCESS_TOKEN_EXPIRE_MINUTES` or `EMAIL_RESET_TOKEN_EXPIRE_HOURS` can be zero or negative. Tokens then expire as soon as they are issued, so logins or password resets fail with no clear cause.
- A password-reset token (`EMAIL_RESET_TOKEN_EXPIRE_HOURS`, in **hours**) can be set to outlive a normal login session (`ACCESS_TOKEN_EXPIRE_MINUTES`, in **minutes**). A reset link is a credential that bypasses the password, so it must never stay valid longer than a session.
- `SMTP_TLS` (STARTTLS) and `SMTP_SSL` (implicit TLS) can both be enabled. These modes exclude each other, and sending mail fails at runtime.

Make `Settings` reject these combinations when it validates, so a misconfigured deployment fails at startup.

Requirements:

1. `ACCESS_TOKEN_EXPIRE_MINUTES` must be strictly positive (greater than 0). Zero or a negative value must be rejected, and the error must name `ACCESS_TOKEN_EXPIRE_MINUTES`.
2. `EMAIL_RESET_TOKEN_EXPIRE_HOURS` must be strictly positive. Zero or a negative value must be rejected, and the error must name `EMAIL_RESET_TOKEN_EXPIRE_HOURS`.
3. When both lifetimes are positive, the reset-token lifetime converted to minutes (`EMAIL_RESET_TOKEN_EXPIRE_HOURS * 60`) must not be greater than `ACCESS_TOKEN_EXPIRE_MINUTES`. **Boundary rule: equal values are allowed.** For example, 2 hours with 120 minutes is valid, and 2 hours with 119 minutes is rejected. The error must name both `EMAIL_RESET_TOKEN_EXPIRE_HOURS` and `ACCESS_TOKEN_EXPIRE_MINUTES`.
4. Setting `SMTP_TLS` and `SMTP_SSL` both to true must be rejected, and the error must name both `SMTP_TLS` and `SMTP_SSL`. Either one alone, or neither, stays valid.
5. When several of these problems occur together, one error must name **every** offending variable, not only the first one found.
6. Rejection means that constructing `Settings` raises a `ValueError`. Pydantic's `ValidationError` counts.
7. The shipped defaults (8-day access token, 48-hour reset token, TLS on and SSL off) must still validate, and the existing test suite must still pass.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
