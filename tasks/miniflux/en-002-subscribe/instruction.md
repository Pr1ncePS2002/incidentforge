# Scope Google Reader subscription names to the deployment environment

When a Google Reader client subscribes to a feed (`subscribe` in `internal/googlereader/handler.go`), nothing records which deployment the subscription belongs to. Staging and production often share caches, brokers and log pipelines. Any identifier built for a subscription without the environment is the same in every deployment, so staging entries overwrite production ones and the other way round. Add a single helper that builds every such name from the configured deployment environment, and make `subscribe` use it.

## Setting

- The deployment environment is read from the environment variable `MINIFLUX_ENVIRONMENT`.
- Allowed values, matched case-sensitively: `production`, `staging`, `development`, `test`.
- If the variable is **not set at all**, the default environment is `production`.
- If the variable is set but is empty or whitespace only, do **not** fall back to the default. Building a name must fail.

## API (package `internal/googlereader`)

1. A struct type `NameSettings` with one exported string field, `Environment`.
2. `NameSettingsFromEnv() NameSettings` reads `MINIFLUX_ENVIRONMENT` as described above. An unset variable gives `production`. A set value is passed through unchanged, even when it is empty.
3. `ScopedName(settings NameSettings, parts ...string) (string, error)`:
   - It returns an error when `settings.Environment` is empty, whitespace only, or not one of the allowed values. The error message must contain the setting name `MINIFLUX_ENVIRONMENT`.
   - It returns an error when no parts are given.
   - Otherwise the name is the environment followed by each part, joined with `:`. Every part (not the environment) is escaped with Go's `url.QueryEscape`. A part that contains `:` (or `%`, `+`, a space and so on) therefore cannot be mistaken for several parts or collide with a different name.
4. `SubscriptionName(settings NameSettings, userID int64, feedURL string) (string, error)` returns the scoped name for the parts `googlereader`, `subscription`, the decimal user ID and the feed URL. Errors are the same as for `ScopedName`.

The format for the shipped default environment must be stable. For example, user 42 subscribing to `https://example.org/feed.xml` in `production` must produce exactly:
`production:googlereader:subscription:42:https%3A%2F%2Fexample.org%2Ffeed.xml`

The same logical name built for two different environments must produce two different strings.

## Wiring

At the very start of `subscribe`, build the subscription name with `NameSettingsFromEnv()` and `SubscriptionName`. If that fails because the environment is misconfigured, return the error before creating any category or feed.

## Constraints

- No behaviour changes when `MINIFLUX_ENVIRONMENT` is unset.
- The existing test suite must still pass.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
