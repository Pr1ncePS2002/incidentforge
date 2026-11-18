# Accept JSON arrays for list settings and reject malformed list values

Some Miniflux settings hold a list of values, for example networks or resource types. Today they only work as a comma-separated string such as `10.0.0.0/8, 192.168.0.0/16`. Operators often write these values as JSON arrays instead, for example `["10.0.0.0/8","192.168.0.0/16"]`, because that is how their Helm values, Compose files or secret managers render lists. The parser then splits that string on commas without complaint. The service ends up with list items such as `["10.0.0.0/8"` and `"192.168.0.0/16"]`. Nothing fails at startup, but the setting quietly stops working, for example an allow-list that matches nothing. A truncated or malformed array such as `["10.0.0.0/8",` is also accepted without any error.

Make every list-valued setting accept both spellings, and fail loudly on a list value that is clearly broken.

## Requirements

All of this lives in package `internal/config` (`miniflux.app/v2/internal/config`). Startup parses the options with `NewConfigParser()` and then the parser's line or environment parsing, and calls `Validate() error` on the resulting options right away. The new behaviour must be in place once both steps have run.

1. **JSON array spelling.** For every option whose value type is the string-list type, a value that starts with `[` (after trimming surrounding whitespace) must be read as a JSON array of strings. The parsed list must be exactly what the equivalent comma-separated spelling gives. Each item has its surrounding whitespace trimmed, empty items are dropped and items keep their order. For example, `["10.0.0.0/8", "192.168.0.0/16", "172.16.0.0/12"]` and `10.0.0.0/8, 192.168.0.0/16,172.16.0.0/12` must give the same three-item list.
2. **Empty array.** `[]` must give an empty list (length 0), not a one-item list.
3. **Malformed lists are rejected.** If a list value starts with `[` but is not a valid JSON array of strings, `Validate()` must return an error. This covers unterminated arrays, trailing garbage and non-string elements such as `[1, 2]`. The error message must contain the setting's key (for example `METRICS_ALLOWED_NETWORKS`) and the offending value exactly as written, after trimming surrounding whitespace.
4. If the setting has a value validator, the items decoded from a JSON array must still pass that validator, judged as their comma-separated equivalent. On failure, return an error naming the key and the value.
5. **Unchanged canonical behaviour.** Comma-separated values, defaults and every other setting type behave exactly as before. A default configuration must still validate.
6. The existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
