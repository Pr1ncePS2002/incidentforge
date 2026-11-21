# Environment-scoped names for user change events

Staging and production share one message broker and one cache cluster. When a user is updated, other components need to hear about it so they can drop cached copies of that user. Today `app.crud.update_user` does not publish anything. If it did so with a fixed topic name, staging updates would invalidate production caches and the reverse. Add the event, and build every name it uses from the configured deployment environment.

The environment comes from the existing setting `FASTAPI_ENV` on `app.core.config.settings`. Its shipped default is `development`.

## Requirements

1. **Naming helper.** Add a module `app.core.naming` with a function `scoped_name(*parts: str) -> str`.
   - It returns the environment followed by the parts, joined with `:`, in the form `<env>:<part1>:<part2>...`. For example, with `FASTAPI_ENV=development`, `scoped_name("user", "42")` returns `development:user:42`.
   - It reads `FASTAPI_ENV` from `app.core.config.settings` **each time it is called**. Don't cache the value at import time, and don't fall back to a hardcoded default.
2. **Allowed environments.** The only accepted values are `development`, `staging` and `production`. Matching is exact: no trimming and no case-folding. If `FASTAPI_ENV` is empty, missing, not a string or any other value, `scoped_name` must raise `ValueError`, and the message must contain the setting name `FASTAPI_ENV`.
3. **Unambiguous parts.** Each part must be a non-empty string with no `:` in it. Otherwise `scoped_name` raises `ValueError`. This way `("a:b", "c")` and `("a", "b:c")` can never produce the same name. Calling it with no parts at all also raises `ValueError`.
4. **Broker stand-in.** Add a module `app.core.broker` with:
   - a module-level list `published`
   - a function `publish(topic: str, key: str) -> None` that appends the tuple `(topic, key)` to that list
5. **Publish on update.** After a successful commit, `app.crud.update_user` must publish exactly one message:
   - topic: `scoped_name("users", "updated")`, for example `development:users:updated`
   - key: `scoped_name("user", str(db_user.id))`, for example `development:user:<uuid>`
6. **Fail fast.** Resolve both names **before** the user row is modified or committed. With an invalid `FASTAPI_ENV`, `update_user` must raise the `ValueError` without changing the user object, without calling `session.add`/`commit`, and without publishing anything.
7. **Stable default.** Names for the default `development` environment follow exactly the format above. The rest of `update_user`'s behaviour is unchanged, including password hashing and the return value, and the existing test suite must still pass.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
