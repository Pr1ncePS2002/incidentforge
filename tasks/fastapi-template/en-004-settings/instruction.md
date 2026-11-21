# Environment-scoped secret paths

All environments (local, staging, production) keep their credentials in one shared secret store. Today the backend has no single place that decides which path a secret lives under. Tooling builds paths by hand, and a rotation script that runs without an explicit environment quietly falls back to a default environment. That lets one environment's rotation overwrite or delete another environment's credentials.

Add the setting and the helper to `app.core.config.Settings` so that every secret path comes from the configured deployment environment.

Requirements:

1. Add a setting `DEPLOYMENT_ENVIRONMENT` (normal settings source, so it can be read from the environment variable of the same name). It defaults to `local`, which is what the repo ships with. The only allowed values are exactly `local`, `staging` and `production`. Matching is case-sensitive and no normalisation is done.
2. Constructing `Settings` with an empty or unknown `DEPLOYMENT_ENVIRONMENT` (for example `""`, `prod`, `Production`, `staging/production`) must fail with a `ValueError` (pydantic's `ValidationError` counts). The message must contain the text `DEPLOYMENT_ENVIRONMENT`.
3. Add an instance method `secret_name(name: str) -> str` on `Settings`. It returns the store path for the logical secret `name` in the **configured** environment, in the form `<DEPLOYMENT_ENVIRONMENT>/<name>`. For example, with the default settings `secret_name("smtp-password")` returns `local/smtp-password`, and with `DEPLOYMENT_ENVIRONMENT=production` it returns `production/smtp-password`. It must never use a hardcoded or default environment in place of the configured one.
4. `secret_name` must check the environment again every time it is called. If the attribute was changed to an empty or unknown value after construction, the call must raise `ValueError` with `DEPLOYMENT_ENVIRONMENT` in the message instead of building a path.
5. `/` is the separator. A `name` that contains `/`, or that is empty or only whitespace, must be rejected with `ValueError`, so that two different (environment, name) pairs can never produce the same path.
6. Existing behaviour is unchanged: settings with no `DEPLOYMENT_ENVIRONMENT` still load, and the existing test suite still passes.

## background

This protection comes from a public incident report (https://blog.cloudflare.com/cloudflare-incident-march-21-2025/). What set that incident off: During a credential rotation, the secret-update and deploy commands were run without an explicit environment flag. They fell back to the default (non-production) Worker, so the production gateway kept the old credentials, and those were then deleted from the storage backend.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
