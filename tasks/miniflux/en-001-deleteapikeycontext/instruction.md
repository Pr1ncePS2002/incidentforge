# Scope client-side cache keys to the deployment environment

Teams that build on the Go API client (package `client`, import path `miniflux.app/v2/client`) cache API resources such as API keys, for example to invalidate an entry after `DeleteAPIKeyContext`. Staging and production often share one cache cluster. Today there is no shared way to build those names, so each caller writes its own, usually without the environment. When that happens, a staging delete evicts or overwrites the production entry for the same API key ID.

Add one helper to the `client` package that builds every such name from an explicit settings object.

Requirements:

1. Add an exported struct `CacheKeySettings` with an exported string field named `Environment`. Also add an exported constant `DefaultCacheEnvironment` with the value `production`.
2. The allowed environments are exactly `development`, `production`, `staging` and `test`. They are lowercase and matched exactly, with no trimming and no case folding.
3. Add `func BuildCacheKey(settings CacheKeySettings, parts ...string) (string, error)`.
   - If `settings.Environment` is empty or not one of the allowed values, return an error. The error message must contain the setting name `Environment`, and nothing should be built.
   - Return an error if no parts are given, if any part is empty, or if any part contains the separator character `:`. Without that last check, `("a:b")` and `("a", "b")` would produce the same name.
   - On success, return the namespace `miniflux`, then the configured environment, then the parts, all joined by `:`. For example, parts `feed` and `7` in environment `staging` give `miniflux:staging:feed:7`.
   - The environment must always come from the settings argument. Never fall back to a hardcoded or default value.
4. Add `func APIKeyCacheKey(settings CacheKeySettings, apiKeyID int64) (string, error)`. It returns the key for an API key resource: the parts `api-key` and the decimal ID, built through `BuildCacheKey`. For `production` and ID `42` the result must be exactly `miniflux:production:api-key:42`. Names for the default environment must stay stable.
5. The same logical key built for two different environments must give two different names.
6. Existing client behaviour, including `DeleteAPIKeyContext`, stays unchanged, and the existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
