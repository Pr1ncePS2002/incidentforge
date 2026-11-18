# Make user updates safe to apply twice

`app.crud.update_user` applies a `UserUpdate` to a stored user. Clients retry a PATCH when it times out, and background jobs that change users can be redelivered. Today every delivery is applied again, which causes two problems:

- A repeated password change re-hashes the password with a new salt, so the stored `hashed_password` changes again even though nothing new was requested.
- A late redelivery of an older update overwrites any change made after it. For example, update A sets the name to "A", update B sets it to "B", then A is delivered again and the name goes back to "A".

Make `update_user` idempotent when the caller provides an idempotency key.

Requirements:

1. `update_user` accepts a new optional keyword argument `idempotency_key: str | None = None`. All existing arguments and their meaning stay the same.
2. When `idempotency_key` is `None`, behaviour does not change: every call applies the update.
3. When a key is given, the key is scoped to the user being updated. The first successful call with a given (user, key) pair applies the update. Any later call with the same pair is a repeat and must not change any stored field of the user. That includes `hashed_password`, and it includes fields changed by other updates in the meantime.
4. A repeat is not an error. It returns the user record (same `id`) with its current stored state.
5. Different keys for the same user are separate updates and must all apply. The same key used for two different users is also two separate updates, and both must apply.
6. If an attempt fails before it is committed (for example, the commit raises after the change has been flushed), the half-applied change must be discarded: roll back the session so the stored state is unchanged, re-raise the original exception, and do not record the key. A retry with the same key must then apply the update exactly once.
7. Two deliveries of the same key that arrive at the same time must not both apply.
8. The record of applied keys may be kept in process memory. It must not grow without bound.
9. The existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
