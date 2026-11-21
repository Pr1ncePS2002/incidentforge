# Reject scheduler interval ranges whose minimum is above their maximum

Miniflux's refresh scheduler uses two minimum/maximum pairs, both in minutes:

- `SCHEDULER_ENTRY_FREQUENCY_MIN_INTERVAL` / `SCHEDULER_ENTRY_FREQUENCY_MAX_INTERVAL` (used by the `entry_frequency` scheduler)
- `SCHEDULER_ROUND_ROBIN_MIN_INTERVAL` / `SCHEDULER_ROUND_ROBIN_MAX_INTERVAL` (used by the `round_robin` scheduler)

Each value is checked on its own, but nothing checks the pair. An operator can set a minimum above its maximum, for example `SCHEDULER_ENTRY_FREQUENCY_MIN_INTERVAL=120` with `SCHEDULER_ENTRY_FREQUENCY_MAX_INTERVAL=60`. Miniflux accepts it, and feeds are later polled on a schedule nobody asked for. Catch this during configuration validation.

Requirements:

1. Add a method `ValidateIntervalRanges() error` on the parsed configuration options type (`*configOptions`, package `internal/config`). Put the new logic in a new file in that package. Do not modify `parser.go`.
2. If `SCHEDULER_ENTRY_FREQUENCY_MIN_INTERVAL` is greater than `SCHEDULER_ENTRY_FREQUENCY_MAX_INTERVAL`, return an error that names **both** variables.
3. If `SCHEDULER_ROUND_ROBIN_MIN_INTERVAL` is greater than `SCHEDULER_ROUND_ROBIN_MAX_INTERVAL`, return an error that names **both** of those variables.
4. An error about one pair must not name the variables of the other pair. Check the entry-frequency pair first.
5. **Boundary rule:** a minimum equal to its maximum is valid. It means a fixed interval and must not produce an error.
6. The shipped defaults and any combination where each minimum is at or below its maximum must still validate (return `nil`).
7. The existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
