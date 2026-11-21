# Record access-token checks once, even when clients retry

Clients call `POST {API_V1_STR}/login/test-token` to check that their access token is still valid. Security wants an audit trail of these checks so it can count active sessions. Mobile clients retry this call when it times out, and the gateway sometimes sends the same request twice. If every delivery wrote its own audit entry, the session counts would be too high. Add the audit trail and make it safe against retries.

## Audit log module

Create the module `app.core.token_audit`. It keeps an in-process audit log of token checks and exposes:

- `list_token_checks(user_id=None)` returns the recorded events in insertion order. With a `user_id` (a `uuid.UUID`), it returns only that user's events. Each event has at least these attributes:
  - `id`: a `uuid.UUID` unique to the event
  - `user_id`: the user's id
  - `idempotency_key`: the key, or `None`
  - `created_at`: a timezone-aware datetime
- `reset_token_checks()` empties the log and forgets every idempotency key.

## Endpoint behaviour

1. Every successful (authenticated) call to `/login/test-token` records one audit event for the current user. The response body stays unchanged: it is still the current user (`UserPublic`).
2. Every successful response carries an `X-Token-Check-Id` header. Its value is the string form of the id of the audit event that the call recorded or replayed.
3. Clients can send an `Idempotency-Key` request header. The idempotency key is the pair **(current user, header value)**.
   - The first request with a given key records an event and responds normally. That response does **not** carry an `Idempotency-Replayed` header.
   - Any later request with the same key from the same user records **nothing new**. It returns `200` with the same body and the **same** `X-Token-Check-Id` as the original request, and it adds the header `Idempotency-Replayed: true`. A repeat is not an error.
   - This must also hold when duplicate requests arrive at the same moment: if several identical requests run in parallel, exactly one event is recorded. All of them report the same check id, and every response except one is marked as replayed.
4. Distinct requests must not be merged. Different keys from the same user each record their own event. The same key value sent by two different users also records one event per user.
5. A request without an `Idempotency-Key` header is not deduplicated: each such call records a new event with a new check id.
6. If the `Idempotency-Key` header is present, it must be 1 to 255 characters long. An empty or longer value is rejected with HTTP `422`, and nothing is recorded.
7. The rest of the login API keeps working as before, and the existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
