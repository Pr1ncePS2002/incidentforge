# Reject impossible scheduler and TLS setting combinations at startup

Miniflux checks its parsed configuration with `Validate()` on the configuration options (package `internal/config`, method `func (c *configOptions) Validate() error`). Today that check accepts two combinations that cannot work. Each setting is valid on its own, so nothing fails at startup and the problem only shows up much later.

1. **Inverted entry-frequency window.** With `POLLING_SCHEDULER=entry_frequency`, the next check time of a feed is clamped between `SCHEDULER_ENTRY_FREQUENCY_MIN_INTERVAL` and `SCHEDULER_ENTRY_FREQUENCY_MAX_INTERVAL` (both in minutes). If the minimum is greater than the maximum, the clamp makes no sense and feeds get polled at unexpected intervals.
2. **Two exclusive TLS modes.** `CERT_DOMAIN` turns on automatic (Let's Encrypt) certificates. `CERT_FILE` / `KEY_FILE` supply certificates by hand. When both are set, the server quietly picks one mode and ignores the other.

Requirements:

1. `Validate()` must return an error when `SCHEDULER_ENTRY_FREQUENCY_MIN_INTERVAL` is strictly greater than `SCHEDULER_ENTRY_FREQUENCY_MAX_INTERVAL`. The error message must name both `SCHEDULER_ENTRY_FREQUENCY_MIN_INTERVAL` and `SCHEDULER_ENTRY_FREQUENCY_MAX_INTERVAL`. This check runs whatever `POLLING_SCHEDULER` is set to.
2. **Boundary rule:** equal values are allowed. A minimum equal to the maximum (a fixed interval) must validate.
3. `Validate()` must return an error when `CERT_DOMAIN` is non-empty and `CERT_FILE` or `KEY_FILE` (or both) is also non-empty. The error message must name `CERT_DOMAIN` and every conflicting variable that is set (`CERT_FILE`, `KEY_FILE`). It must not name a file variable that is not set.
4. Valid setups still validate: the shipped defaults, `CERT_DOMAIN` alone, `CERT_FILE` + `KEY_FILE` without `CERT_DOMAIN`, and any min ≤ max interval pair.
5. The existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
