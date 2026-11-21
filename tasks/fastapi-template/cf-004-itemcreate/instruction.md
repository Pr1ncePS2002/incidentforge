# Reject impossible order-quantity limits when creating an item

Clients that create items (`POST /api/v1/items/`, schema `ItemCreate` in `app.models`) need to send order-quantity limits with the item. Today the creation payload has no such fields, and any limits a client sends are dropped without a warning. A downstream integration that reads these limits needs them to be consistent. A limit pair where the minimum is above the maximum can never be met, and it only shows up much later, when no order can satisfy it.

Add the limits to the item-creation schema and reject impossible combinations when the request is validated.

Requirements:

1. `ItemCreate` accepts two new optional integer fields, `min_order_quantity` and `max_order_quantity`. Both default to `None`, which means "no limit". They are part of the creation payload only. This change does not need to persist them or add them to the item response.
2. Each field, when provided, must be a positive integer. Zero or a negative value must be rejected, and the error must name the offending field.
3. When both are provided, `min_order_quantity` greater than `max_order_quantity` must be rejected. The error message must name **both** `min_order_quantity` and `max_order_quantity`.
4. Boundary rule: equal values are **allowed**. `min_order_quantity == max_order_quantity` is valid and means a single fixed order quantity.
5. Giving only one of the two limits is valid.
6. Rejection means constructing `ItemCreate` raises pydantic's `ValidationError`. Through the API, it means the item-creation endpoint returns HTTP 422 and creates no item.
7. Items created without these fields, and without these fields only, behave exactly as before, and the existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
