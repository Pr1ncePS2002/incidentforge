# Reload configuration at runtime without serving stale values

Miniflux reads its configuration once at startup (`config.NewConfigParser()` → `parseLines` / `ParseEnvironmentVariables`) and keeps the parsed `*configOptions` until the process exits. Operators who change a value, such as an admin credential or an OAuth2 setting, must redeploy. Any code that copied the options at startup keeps serving the old values. We need an explicit reload path and one accessor that always returns the active options.

Add this to package `internal/config` (`miniflux.app/v2/internal/config`):

- An exported type `LiveOptions` that holds the active configuration.
- `func NewLiveOptions(initial *configOptions) *LiveOptions` returns a holder that serves `initial` unchanged: `Current()` must return that same pointer. When `initial` is `nil`, it serves the default options, which are the same values a fresh `NewConfigParser()` produces before any parsing.
- `func (l *LiveOptions) Current() *configOptions` returns the options that are active at the moment of the call. Readers call it on every read. It must be safe to call from many goroutines while a reload runs, with no data races.
- `func (l *LiveOptions) Reload(lines []string) error` takes new raw values in the same `KEY=VALUE` form as the environment (`os.Environ()`). It builds a complete new configuration from those lines on top of the documented defaults, using the existing parser, and then runs the existing `Validate()` check.

Required behaviour:

1. **The next read sees the reload.** After `Reload` succeeds, the very next `Current()` returns the new values. No restart, no new holder and no re-parse by the caller is needed.
2. **Snapshots are immutable.** A `*configOptions` returned earlier by `Current()` is never changed in place. A reload swaps in a whole new set of options atomically. A reader that takes one snapshot therefore never sees a mix of old and new values, for example a new `ADMIN_USERNAME` paired with the old `ADMIN_PASSWORD`.
3. **Invalid reloads are rejected.** If the new values fail parsing or `Validate()`, `Reload` returns a non-nil error and the previously active options keep serving. For example, `OAUTH2_PROVIDER=oidc` without `OAUTH2_OIDC_DISCOVERY_ENDPOINT` fails validation, and the error must name `OAUTH2_OIDC_DISCOVERY_ENDPOINT`. A non-blank line that has no `=` or has an empty key is also rejected, and the error must include the offending line. Blank or whitespace-only lines are ignored.
4. **Unset keys go back to their defaults.** A reload is a full replacement. If a key was set before but is missing from the reload, it returns to its default value; it does not keep the stale value.
5. Startup behaviour without any reload is unchanged, and the existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
