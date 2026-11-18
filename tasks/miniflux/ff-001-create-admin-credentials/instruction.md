# Fail fast when admin bootstrap credentials are missing

Miniflux can create its first admin account at startup: with `CREATE_ADMIN` enabled it creates a user from
`ADMIN_USERNAME` and `ADMIN_PASSWORD` (the password can also come from `ADMIN_PASSWORD_FILE`). Today the
configuration check accepts `CREATE_ADMIN` without those credentials. The process connects to the database,
runs migrations, and only then exits with a user-validation error. During a rollout that looks like a
crash loop, far away from the real cause: a missing setting.

Make the configuration check catch this before anything else starts.

Requirements:

1. `Validate()` on the parsed configuration options (package `internal/config`) must return an error when
   `CREATE_ADMIN` is enabled and `ADMIN_USERNAME` is missing, empty or whitespace only.
2. The same applies to `ADMIN_PASSWORD`. A password supplied through `ADMIN_PASSWORD_FILE` counts as set.
3. When both are missing, one error must name **both** variables, and it must mention `CREATE_ADMIN` so the
   operator knows why they are required. When only one is missing, the error must name only that one.
4. With `CREATE_ADMIN` disabled (the default), no admin credentials are required and behaviour is unchanged.
5. The existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
