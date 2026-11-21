# Reject impossible timezone offset windows for parsed feed dates

When Miniflux parses a feed date, it keeps the date's timezone only if the offset is between UTC-12:00 and UTC+14:00. Any date outside that range is converted to UTC. Today that range is hard-coded in `checkTimezoneRange` (package `internal/reader/date`). We want the range to be a value that can be configured. A configurable range can also be set to something that can never work, so it must be validated before use:

- **Inverted range:** the lower bound is above the upper bound, so no offset can ever be kept.
- **Range that excludes UTC:** out-of-range dates fall back to UTC (offset 0). If offset 0 is outside the range, the fallback result breaks the range it was meant to enforce.

Add this to package `internal/reader/date` (`miniflux.app/v2/internal/reader/date`):

1. A struct type `OffsetWindow` with two exported `int` fields, `MinOffsetSeconds` and `MaxOffsetSeconds`. Both are offsets in seconds east of UTC, and both bounds are inclusive.
2. `func DefaultOffsetWindow() OffsetWindow` returns the shipped range: `MinOffsetSeconds = -12*60*60` and `MaxOffsetSeconds = 14*60*60`.
3. `func (w OffsetWindow) Validate() error`:
   - returns an error when `MinOffsetSeconds > MaxOffsetSeconds`;
   - returns an error when the range does not contain offset 0 (`MinOffsetSeconds > 0` or `MaxOffsetSeconds < 0`);
   - in both cases, the error message must contain both field names, `MinOffsetSeconds` and `MaxOffsetSeconds`;
   - returns `nil` for any other range, including the default.
   - **Equal-values rule:** `MinOffsetSeconds == MaxOffsetSeconds` is allowed. It is not an inverted range. It is still subject to the UTC rule: `{0, 0}` is valid (only UTC dates keep their zone), and `{3600, 3600}` is rejected because it excludes UTC.
4. `func (w OffsetWindow) Apply(t time.Time) time.Time` returns `t` unchanged when its zone offset is within `[MinOffsetSeconds, MaxOffsetSeconds]` (bounds included). Otherwise it returns `t.UTC()`. For the default range, `Apply` must give the same result as the existing `checkTimezoneRange`.
5. The existing behaviour of `checkTimezoneRange` and of date parsing does not change, and the existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
