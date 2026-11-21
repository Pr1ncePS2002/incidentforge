# Make account creation safe to retry, keyed on the normalized email

`app.crud.create_user(session=..., user_create=UserCreate(...))` is called by the signup route, by the admin "create user" route and by bootstrap code. Callers retry it: a client resends after a timeout, a job replays a signup event after a crash, and a worker can crash after the row is committed but before it reports success. Today two things go wrong:

- Sending the same signup again fails with a database integrity error. The caller never gets back the account it already created.
- Emails are stored with whatever letter case the caller sent. A retry that spells the address differently (`Alice@example.com` and later `alice@example.com`) quietly creates a **second account** for the same mailbox.

Make user creation idempotent, using the normalized email as the idempotency key.

Requirements:

1. **Idempotency key.** The key is the email address with surrounding whitespace removed, lower-cased. New users are stored with this normalized email.
2. **Repeat with the same credentials.** If a user already exists for the key and the supplied password matches that user's stored password, `create_user` returns the existing user (same `id`) and does not create a row. It must not raise an error, and it must not change the stored record. Other fields in the repeated payload (for example a different `full_name`) are ignored, and the original values are kept.
3. **Same key, different password.** This is not a retry. `create_user` must raise a `ValueError` (a subclass is fine). No row is added, and the existing user keeps its original password. The error message must not contain the email address.
4. **Crash after commit.** If an earlier attempt committed the user but then failed before returning (for example while refreshing the object), calling `create_user` again with the same payload must return that user. It must not create a second row or raise an integrity error.
5. **Distinct emails are never merged.** Different normalized emails must still produce separate users, even when one of them is redelivered between the creates.
6. **Lookups match the stored form.** `app.crud.get_user_by_email` must find a user whether the caller passes the email exactly as stored or with different letter case. It still returns `None` when no user matches.
7. Existing behaviour otherwise stays the same, and the repository's existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
