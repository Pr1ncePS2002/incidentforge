# Fail fast on a half-configured mailer

The backend reads its email settings (`SMTP_*`, `EMAILS_FROM_EMAIL`) in `app.core.config.Settings`.
Today a partial email configuration is accepted without complaint: if, for example, `SMTP_HOST` is set but
no sender address is, the app starts normally and quietly never sends email. Operators only find out when
password-reset mails never arrive.

Make the settings refuse inconsistent email configuration at startup, so a misconfigured deployment crashes
immediately with a clear message instead of degrading silently.

Requirements:

1. `SMTP_HOST` set without `EMAILS_FROM_EMAIL` must be rejected.
2. `SMTP_USER` and `SMTP_PASSWORD` must be provided together; one without the other must be rejected.
3. Enabling both `SMTP_TLS` and `SMTP_SSL` at the same time must be rejected.
4. `SMTP_PORT` must be a valid TCP port (1 to 65535 inclusive); anything else must be rejected.
5. When several of these problems exist at once, a single error must name **every** offending variable,
   not just the first one found.
6. Rejection means constructing `Settings` raises a `ValueError` (pydantic's `ValidationError` counts).
7. With no email configuration at all, behaviour is unchanged and the existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
