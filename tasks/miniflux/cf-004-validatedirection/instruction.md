# Reject entry query filters that can never match

The entries API (`GET /v1/entries`, `/v1/feeds/{id}/entries`, `/v1/categories/{id}/entries`) takes several pairs of optional range filters next to `order`/`direction`/`offset`/`limit`:

| lower bound (query param) | upper bound (query param) | meaning |
|---|---|---|
| `after` | `before` | published date, Unix seconds |
| `published_after` | `published_before` | published date, Unix seconds |
| `changed_after` | `changed_before` | changed date, Unix seconds |
| `after_entry_id` | `before_entry_id` | entry ID |

Each value is accepted on its own, but nothing checks the pairs against each other. A client that swaps the two bounds (for example `published_after=2000&published_before=1000`) gets back an empty list with HTTP 200. That looks like "no new entries", so sync clients silently stop getting updates. Negative values are also accepted and then silently ignored.

Add a validator for these combinations to package `internal/validator` (`miniflux.app/v2/internal/validator`), next to the existing `ValidateDirection`/`ValidateRange` helpers.

## API

- An exported struct type `EntryQueryWindow` with these `int64` fields: `After`, `Before`, `PublishedAfter`, `PublishedBefore`, `ChangedAfter`, `ChangedBefore`, `AfterEntryID`, `BeforeEntryID`.
- `func ValidateEntryQueryWindow(w EntryQueryWindow) error`

## Rules

1. A value of `0` means the bound is not set. A pair is only compared when **both** of its bounds are non-zero. If only one bound is set, the window is valid.
2. Any negative value is rejected. The error must name that field's query parameter (for example `after_entry_id`).
3. **Inverted range:** if both bounds of a pair are set and the lower bound is greater than the upper bound, return an error. The error must name **both** query parameters of that pair (for example `published_after` and `published_before`; for the legacy pair, `after` and `before`). The error must not name parameters from a different pair: an error about the `after`/`before` pair must not contain `published_`.
4. **Equal values are rejected.** Both bounds are exclusive (strictly greater than the lower bound, strictly less than the upper bound), so equal values describe an empty range. Return the same kind of error that names both parameters. Adjacent values are valid, for example `after_entry_id=10` with `before_entry_id=11`.
5. Valid combinations still return `nil`. That includes the all-zero window (no filters, the default) and any pair where lower < upper.
6. The existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
