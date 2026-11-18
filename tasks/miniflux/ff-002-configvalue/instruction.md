# Refuse to start when required settings are missing or still hold template placeholders

Miniflux can create its first admin account at startup. With `CREATE_ADMIN` enabled, it creates a user from `ADMIN_USERNAME` and `ADMIN_PASSWORD`. The password can also come from `ADMIN_PASSWORD_FILE`. Deployment templates often ship these values as placeholders such as `changethis`, `TODO` or `<fill-me>`, and `DATABASE_URL` is often left the same way. Today the configuration check accepts all of these. The process then either fails later, after connecting to the database and running migrations, or it creates an admin account whose password is literally `changethis`.

Make the configuration check catch these problems before anything else starts.

## What to build

Extend `Validate() error` on the parsed configuration options (`*configOptions` in package `internal/config`, the method that `NewConfigParser()` → `ParseEnvironmentVariables()` / `ParseFile()` callers already run) so that it reports these problems:

1. **Conditional requirement.** When `CREATE_ADMIN` is enabled, `ADMIN_USERNAME` and `ADMIN_PASSWORD` must be set. A value that is missing, empty or whitespace-only counts as not set. A password supplied through `ADMIN_PASSWORD_FILE` counts as set. The error must mention `CREATE_ADMIN` so the operator knows why the credentials are required.
2. **Placeholders.** A value counts as a template placeholder when, after trimming surrounding whitespace and ignoring case, it is exactly one of `changethis`, `changeme`, `change-me`, `change_me`, `todo`, `tbd`, `fixme`, `placeholder` or `replaceme`, or when it is wrapped in angle brackets such as `<fill-me>`. A real value that only *contains* one of those words (for example `todo-list-2024`) is not a placeholder. The rules are:
   - When `CREATE_ADMIN` is enabled, a placeholder in `ADMIN_USERNAME` or `ADMIN_PASSWORD` is an error. This includes a password read from `ADMIN_PASSWORD_FILE`.
   - A placeholder in `DATABASE_URL` is always an error.
3. **One aggregated error.** All problems found must be reported in one returned error, and its message must name every offending key. The error must not name a key that is fine. For example, if only `ADMIN_USERNAME` is missing, the message must not mention `ADMIN_PASSWORD`.
4. **Unchanged behaviour for valid configurations.** The shipped defaults must still validate with no error. That includes `CREATE_ADMIN` disabled and the default `DATABASE_URL`. With `CREATE_ADMIN` disabled, the admin credentials are not checked at all. Complete, non-placeholder credentials and a real database DSN must validate.
5. Existing validation rules, such as the OIDC discovery endpoint check, keep working, and the existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
