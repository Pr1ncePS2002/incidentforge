# Apply new settings at runtime without a restart

The backend keeps its configuration in one shared `Settings` instance (`app.core.config.settings`, class `app.core.config.Settings`). Every module imports that object once at startup, so the only way to change a value today, such as `ACCESS_TOKEN_EXPIRE_MINUTES` or the `SMTP_*` settings, is a redeploy. Operators want to push a new configuration into a running process and have the next read use it.

Add an explicit reload path to `Settings`.

Requirements:

1. Add an instance method `reload(values)` to `Settings`. `values` is a mapping from setting name (the field name, e.g. `"SMTP_PORT"`) to its **raw** value. Raw values may be strings as they would come from the environment (for example `"15"` for an int setting) and must be parsed and validated the same way they are at startup, including the existing field and model validators.
2. `values` is the **complete** new configuration. Reload does not read process environment variables or the dotenv file. A setting that is missing from `values` falls back to its default declared in `Settings`, not to the value it had before the reload (for example, `ACCESS_TOKEN_EXPIRE_MINUTES` goes back to 8 days in minutes and `SMTP_HOST` goes back to `None`). A missing required setting (such as `SECRET_KEY`) makes the reload invalid.
3. The reload updates the existing instance **in place** and returns that same instance. Any code that already holds a reference to it (a module-level import of `settings`, or an object that stored it in a constructor) sees the new values on its very next attribute read, with no restart and no re-import.
4. The reload is all-or-nothing. If any value is invalid, `reload` raises a `ValueError` (pydantic's `ValidationError` counts) whose message names the offending setting. Nothing changes: every setting, including the valid ones in the same reload, keeps its previous value, and a later valid reload still works.
5. Related values swap together. After a successful reload, every value comes from the new configuration, including values derived by validators (for example `EMAILS_FROM_NAME` defaulting to `PROJECT_NAME`, and the computed `emails_enabled`). A reader must never see a new value next to a stale one.
6. If no reload happens, behaviour is unchanged: constructing `Settings` works exactly as it does today and the existing test suite still passes. You do not need to rebuild objects that are created once from settings at startup (the DB engine, CORS middleware).

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
