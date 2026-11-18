# Fail fast when password-recovery email cannot work

The backend turns on outgoing email once `SMTP_HOST` is configured (`app.core.config.Settings`). Password-recovery mails (valid for `EMAIL_RESET_TOKEN_EXPIRE_HOURS`) are then sent from `EMAILS_FROM_EMAIL`. They contain a reset link built from `FRONTEND_HOST`, and they are sent through the SMTP server with `SMTP_USER` / `SMTP_PASSWORD` when credentials are used.

Right now, a deployment where `SMTP_HOST` is set but the related settings are missing, blank or still hold template placeholders starts without any error. The reset flow then fails later. The app either quietly stops sending mail or sends broken links, and nobody notices until a user can't reset their password.

Change the settings so that this problem stops the app from starting.

## Requirements

Treat email as enabled when `SMTP_HOST` is set, meaning it is not `None`. A blank string still counts as set. When email is enabled, constructing `Settings` must fail if any of the following is true:

1. `SMTP_HOST` itself is empty or contains only whitespace.
2. `EMAILS_FROM_EMAIL` is missing.
3. `FRONTEND_HOST` is empty or contains only whitespace.
4. `SMTP_USER` is set and `SMTP_PASSWORD` is missing, empty or whitespace-only.
5. One of the values checked above (`SMTP_HOST`, `EMAILS_FROM_EMAIL`, `FRONTEND_HOST`, and `SMTP_USER` / `SMTP_PASSWORD` when `SMTP_USER` is set) still holds a template placeholder.
   - A value is a placeholder if, after trimming whitespace and ignoring case, it equals one of `changethis`, `changeme`, `change-me`, `todo`, `tbd`, `fixme` or `placeholder`.
   - A value is also a placeholder if it is wrapped in angle brackets, for example `<fill-me>`.

How the failure must work:

- Construction must raise a `ValueError`. Pydantic's `ValidationError` counts.
- The failure must happen when `Settings` is constructed, not when a mail is first sent.
- When several settings are wrong at once, one error must name **every** offending key.
- The message must not name keys that are fine. In particular, don't put the literal names of other settings in a generic prefix.

When `SMTP_HOST` is not set, none of these checks apply and behaviour is unchanged. For example, an unused `SMTP_PASSWORD="changethis"` is still accepted. Valid email setups must keep loading. That includes `SMTP_HOST` plus `EMAILS_FROM_EMAIL` without credentials, and a complete setup with credentials. The repository's shipped defaults must also keep loading, and the existing test suite must still pass.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
