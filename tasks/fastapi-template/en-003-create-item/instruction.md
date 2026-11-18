# Environment-scoped names for item events

Several of our deployments (local, staging, production) share one message broker. We are starting to publish an event every time an item is created. If the event name does not include the deployment environment, or uses a hardcoded one, staging consumers will pick up production events and the other way round. Every such name must come from one helper that reads the environment from configuration and refuses to build an ambiguous or unscoped name.

Build the following:

1. **Setting.** Add a new module `app.core.namespacing` with a pydantic-settings class `NamespaceSettings`. It has one field, `DEPLOYMENT_ENV`, read from the environment variable of the same name. The default is `"local"`, the environment the repo ships with. The allowed values are exactly `local`, `staging` and `production`. Matching is case-sensitive and whitespace is not stripped. If you construct `NamespaceSettings` with an empty or unknown value, it must raise a `ValueError` whose message contains `DEPLOYMENT_ENV` (pydantic's `ValidationError` counts). The module also exposes a module-level instance named `namespace_settings`.
2. **Helper.** Add `scoped_name(*parts, settings=None) -> str` to `app.core.namespacing`.
   - It reads `DEPLOYMENT_ENV` from `settings` when one is given. The argument can be any object with that attribute. Otherwise it reads the module's `namespace_settings`, looked up at call time, so replacing that attribute changes the result.
   - It returns the environment followed by each part converted with `str()`, joined with `:`. For example, `local:items:created:<id>`. The format for the default `local` environment must be exactly this.
   - If the environment is missing, empty or not one of the allowed values, it raises `ValueError` and the message names `DEPLOYMENT_ENV`. Never fall back to a default environment.
   - If no parts are given, or any part is `None`, empty or contains the separator `:`, it raises `ValueError`. This prevents two different part lists, such as `("a:b", "c")` and `("a", "b:c")`, from producing the same name.
3. **Event outbox.** Add a module `app.core.events` with a module-level list `OUTBOX` and a function `publish(name: str, payload: dict) -> None`. The function appends `(name, payload)` to `OUTBOX`, which is looked up at call time.
4. **Attach to `app.crud.create_item`.**
   - When an item is created, publish one event through `app.core.events.publish`. Its name is `scoped_name("items", "created", <item id>)` and its payload is `{"item_id": str(item.id), "owner_id": str(owner_id)}`.
   - Build the name **before** anything is written. If the environment is invalid, `create_item` must raise the `ValueError` without calling `session.add`, `session.commit` or `publish`.
   - Otherwise `create_item` behaves and returns exactly as before.
5. The same logical name built for two different environments must produce two different strings. The existing test suite must still pass.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
