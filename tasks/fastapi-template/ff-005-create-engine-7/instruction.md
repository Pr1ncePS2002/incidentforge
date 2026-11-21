# Refuse to start with an unauthenticated or half-configured database connection

The backend builds its SQLAlchemy engine in `app/core/db.py` from `settings.DATABASE_URL` (defined on `app.core.config.Settings`). Today the settings accept a database URL with no username or password in it. The service starts without complaint and only fails, or tries to connect without credentials, when the first query reaches the database. A rollout that forgets to give one batch of instances its credentials looks healthy until real traffic arrives.

We are also adding opt-in TLS for the database connection. Like the credentials, the new setting it needs must be checked at startup and must not be trusted on first use.

Requirements:

1. Add two new settings to `Settings`:
   - `DATABASE_SSL_ENABLED` (bool, default `False`)
   - `DATABASE_SSL_ROOT_CERT` (optional string, default unset): the path to the CA root certificate.

   When the flag is on, the engine in `app/core/db.py` must connect with `sslmode=verify-full` and use that root certificate. When the flag is off, the engine must behave as it does today.
2. `DATABASE_URL` must contain a database user and a password. If either one is missing, empty or whitespace-only, `DATABASE_URL` is rejected.
3. When `DATABASE_SSL_ENABLED` is on, `DATABASE_SSL_ROOT_CERT` is required:
   - It is rejected if it is unset, empty or whitespace-only.
   - It is rejected if it still holds a template placeholder. Placeholders are `changethis`, `changeme`, `change-me`, `todo`, `tbd` and `fixme` (matched case-insensitively), plus any value wrapped in angle brackets, such as `<fill-me>`.

   When the flag is off, `DATABASE_SSL_ROOT_CERT` is not checked.
4. Rejection happens when `Settings` is constructed, not on first use. Constructing it must raise a `ValueError` (pydantic's `ValidationError` counts).
5. If several problems are present, a single error must name **every** offending setting (for example both `DATABASE_URL` and `DATABASE_SSL_ROOT_CERT`), not just the first one found.
6. Valid configurations must load unchanged. This includes the repository's shipped configuration, where the URL has a user and password and TLS is off. The existing test suite must still pass.

## background

This protection comes from a public incident report (https://www.heroku.com/blog/how-i-broke-git-push-heroku-main). What set that incident off: New code that needed a new auth config variable went out to a batch of production Git server instances. The variable had been set but never pushed to those instances, so the processes started without it and sent unauthenticated calls to a private internal API.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
