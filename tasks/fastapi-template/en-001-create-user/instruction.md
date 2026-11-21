# Scope shared cache, queue and topic names by deployment environment

Our deployments (development, staging, production) are about to share one cache cluster and one message broker. Any key, queue or topic name built without the deployment environment, or with a hardcoded one, would let staging overwrite production entries, and one environment's consumers would pick up another environment's jobs. The backend has no single place that builds these names yet, and nothing checks that the environment setting is usable before user records are written.

Add a module `app.core.naming` that becomes the only place where environment-scoped names are built.

Requirements:

1. The environment comes from the existing `FASTAPI_ENV` field on the settings object `app.core.config.settings`. Read it **every time a name is built**, not once at import, and never fall back to a hardcoded or default value.
2. The allowed environments are exactly `local`, `development`, `staging` and `production`, and the check is case-sensitive.
3. `current_environment()` returns the configured environment. If `FASTAPI_ENV` is missing, `None`, empty or only whitespace, or is not one of the allowed values, it raises `ValueError`, and the message must contain the setting name `FASTAPI_ENV`.
4. `scoped_name(*parts)` returns the environment followed by each part converted with `str()`, all joined with `:`. For example, with `FASTAPI_ENV=development`, `scoped_name("user", 42)` returns `"development:user:42"`. It raises `ValueError` if no parts are given, if a part is an empty string, or if a part contains `:`, because such names could collide with other names. It also raises the same environment errors as in requirement 3.
5. `user_cache_key(user_id)` returns the cache key for one user record, which is `scoped_name("user", user_id)`. For example: `"development:user:<id>"`.
6. The same logical key built under two different environments must give two different names.
7. `app.crud.create_user` must check the environment (as in requirement 3) **before** it adds anything to the session. If the environment is misconfigured, it raises that `ValueError` and does not write anything.
8. Names for the default `development` environment must follow the format above exactly. With a valid environment, user creation works as before, and the existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
