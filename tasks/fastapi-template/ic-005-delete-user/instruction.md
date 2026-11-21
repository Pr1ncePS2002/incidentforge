# Make admin user deletion safe to retry

Superusers delete accounts with `DELETE {API_V1_STR}/users/{user_id}`. This request is not idempotent. When an admin console or automation job times out and sends the same delete again, the first attempt has already removed the user and their items. The retry then gets `404 User not found`, and the caller logs the deletion as failed even though it worked. Retry tooling can't tell "already done" apart from "never existed".

Let callers mark a delete as one logical operation with an idempotency key. The operation must take effect exactly once, and every repeat must return the original result.

Requirements:

1. The endpoint accepts an optional HTTP request header `Idempotency-Key` (any non-empty string). Treat a missing, empty or whitespace-only header as "no key".
2. **No key:** behaviour is exactly the same as today. A successful delete returns 200 with `{"message": "User deleted successfully"}`. A missing user returns 404. A superuser deleting themselves gets 403. The existing test suite must still pass.
3. **First successful delete with a key:** delete the user and all of their items, as today. Return 200 with `{"message": "User deleted successfully"}`, and record the key together with the target `user_id` and the response.
4. **Repeat with the same key and the same `user_id`:** do not touch the database again. Return 200 with a body identical to the original response, even though the user no longer exists. This holds for any number of repeats.
5. **Same key reused for a different `user_id`:** reject with **409 Conflict** and change nothing. The other user and their items must stay.
6. **Only successful deletions are recorded.** If an attempt fails, nothing about it is remembered and its partial work is rolled back. Failures include 404, 403, or an unexpected exception after some rows were already removed in the transaction, such as the items being deleted but not the user. A retry with the same key must then do the deletion normally, once, and later repeats replay that success.
7. Different keys are independent: deletes of different users with different keys must all apply.
8. Two deliveries of the same key that arrive at the same time must not both run the deletion. Serialize them so one applies and the other replays its result.
9. A process-local store for idempotency records is acceptable. No database migration is required.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
