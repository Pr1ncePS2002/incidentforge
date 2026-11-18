# Make item creation safe to deliver twice

`app.crud.create_item(*, session, item_in, owner_id)` inserts a new `Item` on every call. Clients that retry after a timeout, queue consumers that receive the same message again, and jobs that restart after a crash all call it a second time for the same logical request, and each call adds another row. Users end up with duplicate items.

Add idempotency support to `create_item` so that a repeated request creates nothing new and returns the item from the first request.

Requirements:

1. `create_item` takes a new optional keyword argument `idempotency_key: str | None = None`. All existing arguments and the return type (`Item`) stay the same.
2. **No key (`None`):** behaviour does not change. Every call creates a new item.
3. **Key given:** the first call for a pair of (`owner_id`, `idempotency_key`) creates the item. Any later call with the same owner and key creates no row and returns the item from the first call (same `id`, `title`, `description`, `owner_id`). It must not raise. If the later call carries a different payload, the key still wins: the original item comes back unchanged and nothing is updated or created.
4. The key belongs to one owner. Two different owners can use the same key string, and each gets their own item. Different keys for the same owner always create different items.
5. The guarantee must hold across separate database sessions and process restarts, so it cannot rely on in-memory state. In particular:
   - If an earlier attempt committed the item but then failed before reporting success (for example, the connection dropped after the commit), a retry with the same key returns the stored item and does not insert a second one.
   - If an earlier attempt failed before anything was persisted, a retry with the same key creates the item exactly once.
   - If two deliveries with the same key run concurrently in different sessions, and both check for an existing item before either commits, the database must end up with exactly one item. Both calls must return that item, and neither may raise.
6. A key that is empty or only whitespace is a caller error: `create_item` must raise `ValueError` and must not create anything.
7. You must not change the database schema. No new tables or columns, and no migrations.
8. The existing test suite must still pass.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
