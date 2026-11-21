# Reject feed filter rules that would drop every entry

When a feed is created, Miniflux accepts two optional regular-expression filters: `blocklist_rules` (`BlocklistRules`) and `keeplist_rules` (`KeeplistRules`). During refresh the blocklist runs first and removes every entry that matches it. Then the keeplist removes every entry that does **not** match it. When both are set to the same expression, each entry is removed by one filter or the other, so the feed stays empty forever. Today `ValidateFeedCreation` checks each rule on its own (is it a valid regex?) and accepts this combination without a word. Users only notice days later, when nothing ever shows up.

Reject this combination when the feed is validated.

Requirements:

1. Add an exported function to package `internal/validator` (import path `miniflux.app/v2/internal/validator`):

   `func ValidateFeedRuleCombination(request *model.FeedCreationRequest) error`

   It needs no database access. It returns `nil` when the combination is acceptable. Otherwise it returns a non-nil error.
2. If `BlocklistRules` and `KeeplistRules` are both non-empty and identical, the function must return an error. The error message must name **both** fields, using the strings `blocklist_rules` and `keeplist_rules`.
3. Equality rule: compare the two rules after removing leading and trailing whitespace. Rules that are equal after trimming count as identical and are **rejected**. Rules that still differ after trimming are allowed, even if they differ only in letter case (regexes are case-sensitive).
4. These are allowed: both rules empty (the default), or one rule empty and the other set. Rules made only of whitespace count as empty. A `nil` request returns `nil`.
5. `ValidateFeedCreation` must apply the same check, so feed creation through the API and UI refuses the combination.
6. Leave the other validation rules alone. The existing test suite must still pass.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
