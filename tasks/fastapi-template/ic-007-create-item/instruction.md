# Make `POST /api/v1/items/` safe to retry

Clients retry item creation when they don't get a response. This happens on client timeouts, dropped connections and restarted workers. Today every retry creates another item. A request whose commit succeeded but whose response was lost will produce a duplicate when the client sends it again. Two copies of one request sent close together will also both create rows.

Add opt-in idempotency to item creation through an `Idempotency-Key` request header.

Requirements:

1. **Key source.** The idempotency key is the value of the `Idempotency-Key` HTTP header. Each user has their own keys: the same key sent by two different users is two different requests, and each user gets their own item.
2. **Apply once.** The first request with a given key creates the item as it does today. Any later request from the same user with the same key and the same payload (same `title` and `description`) must not create another item. It must respond `200` with the same body as the original response, including the original item's `id`.
3. **Retry after a failed attempt.** The item and the record of its key must be stored atomically.
   - If an attempt fails before its transaction commits, nothing from it may remain, and a retry with the same key creates exactly one item.
   - If an attempt's commit landed but the request still failed (for example, the connection dropped right after the commit), a retry with the same key must return that already-created item instead of creating a second one.
4. **Concurrent duplicates.** If two requests with the same user and key are processed at the same time, exactly one item is created. Both requests receive `200` with that item.
5. **Distinct requests still apply.** Requests with different keys must each create their own item, even if their payloads are identical. Requests without an `Idempotency-Key` header behave exactly as before: every one creates a new item.
6. **Key misuse.** Reusing a key with a different payload must be rejected with `422`, and no item may be created for it. A key that is empty, whitespace-only or longer than 255 characters must be rejected with `422`. A key of exactly 255 characters is valid.
7. Whatever storage you add must work against the existing database without a manual migration step. The repository's existing test suite must still pass.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
