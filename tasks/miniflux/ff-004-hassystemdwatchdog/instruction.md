# Fail fast on missing or placeholder systemd watchdog settings

Miniflux supports the systemd watchdog. `systemd.HasSystemdWatchdog()` (package `internal/systemd`) only checks whether `WATCHDOG_USEC` is non-empty. Any non-empty value counts as "watchdog on", including whitespace or a template value left in a unit or env file (`WATCHDOG_USEC=changethis`). The interval is parsed later, and the keep-alive messages need `NOTIFY_SOCKET`, which nothing checks. With a bad value the service starts fine, but systemd then kills and restarts it in a loop because no keep-alive ever arrives. Nothing in the logs points at the bad setting.

Add one place that reads and checks all watchdog settings at once, so the daemon can refuse to start when they are wrong.

## API

In package `internal/systemd`, add:

- an exported struct type `WatchdogSettings` with the fields
  - `Enabled bool`
  - `Interval time.Duration`
  - `NotifySocket string`
- an exported function `LoadWatchdogSettings() (WatchdogSettings, error)` that reads the process environment.

Leave the existing functions (`HasSystemdWatchdog`, `WatchdogInterval`, and the others) unchanged.

## Behaviour

1. If `WATCHDOG_USEC` is absent or the empty string, the watchdog is off. The function returns `Enabled == false` and a nil error, whatever `NOTIFY_SOCKET` holds. This is the default, and it must keep loading.
2. Any other value of `WATCHDOG_USEC` turns the watchdog on. Then:
   - After trimming surrounding whitespace, `WATCHDOG_USEC` must be a positive integer number of microseconds. A whitespace-only value, a placeholder, a non-number, zero or a negative number is invalid.
   - `NOTIFY_SOCKET` becomes required. If it is absent, empty, whitespace-only or a placeholder, it is invalid. Any other value is accepted as is (trimmed), including abstract sockets such as `@/org/freedesktop/systemd1/notify`.
3. A value counts as a placeholder when, trimmed and compared case-insensitively, it is one of `changethis`, `changeme`, `todo`, `fixme` or `placeholder`, or when it is wrapped in angle brackets (for example `<fill-me>`).
4. If any setting is invalid, the function returns a non-nil error. That single error must name **every** offending variable (`WATCHDOG_USEC` and/or `NOTIFY_SOCKET`) and must not name a variable that is valid. For example, a placeholder `WATCHDOG_USEC` with a good `NOTIFY_SOCKET` must not mention `NOTIFY_SOCKET`.
5. With valid settings, the function returns `Enabled == true`, `Interval` equal to the configured microseconds as a `time.Duration` (for example, `30000000` → 30s), and `NotifySocket` set to the socket path.
6. The existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
