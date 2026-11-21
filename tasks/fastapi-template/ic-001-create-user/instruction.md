# Make user creation safe to run twice

`app.crud.create_user(*, session, user_create)` is called by sign-up, by the admin "create user" endpoint and by provisioning jobs. Those callers retry: a client times out and sends the request again, a job restarts after a crash, or a worker gets the same provisioning event twice. Today a second call for the same user fails with a raw database `IntegrityError` from the unique email constraint. This happens even when the first call already committed the user and only the response was lost. Retries fail noisily, and callers can't tell "already done" apart from "real conflict".

Make `create_user` idempotent. The **email address** of the `UserCreate` payload is the idempotency key, matched exactly as stored.

Requirements:

1. **Replay returns the original.** If a user with the same email already exists and the payload matches it, `create_user` returns the existing `User` row (same `id`). It inserts nothing, changes nothing and raises nothing. The payload matches when the password verifies against the stored hash and `full_name`, `is_active` and `is_superuser` are all equal. This must work when the repeat uses the same session and when it uses a fresh one.
2. **Retry after a partial failure.** Sometimes the first attempt commits the user and then fails before it returns, for example when the refresh after the commit raises. A retry with the same payload must return that committed user and must not insert a second row.
3. **Back-to-back duplicates.** Look up an existing user through `get_user_by_email` in `app.crud`. Another delivery of the same payload may commit the user after that check but before this call's own insert, which hits the unique constraint. In that case, roll back and treat the call as a replay: return the row that won the race, not an error.
4. **Real conflicts are still rejected.** If a user with that email exists but the payload differs (different password, `full_name`, `is_active` or `is_superuser`), raise a `ValueError` (a subclass is fine). Leave the stored user unchanged. The error message must not include the email address or the password.
5. **Distinct users are never deduplicated.** Payloads with different emails always create separate users, even if every other field is the same.
6. The existing API behaviour (the routes still check for an existing email first and return 400) and the existing test suite are unchanged.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
