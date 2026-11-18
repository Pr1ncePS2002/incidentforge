# Task families

Each family is a recurring production failure class seen across a large e-commerce microservice fleet,
rewritten as a feature request: "add the protection that would have prevented this outage". Definitions live
in `src/incidentforge/families/<slug>/` (`family.yaml` + `prompt.md`); this page is generated from them by
`uv run python scripts/gen_families_doc.py`.

`forge run` without `--family` samples families by the share of incidents each class accounts for
(`families/taxonomy.json`), so the dataset mix follows production reality rather than being uniform.

## 1. fail-fast-config

**fail fast on missing or placeholder settings.** the service refuses to start when a required setting is missing, empty, whitespace or still a placeholder, and reports every bad key in one aggregated error instead of crashing later on first use.

Attaches to: `settings-class`, `env-read`, `pool-config` · languages: python, go · sampling weight: 16%

Injected faults:

- `missing`: a required setting is absent from the environment
- `empty`: a required setting is set to an empty or whitespace-only string
- `placeholder`: a required setting still holds a template placeholder such as "changethis", "todo" or "<fill-me>"
- `conditional-missing`: a setting that becomes required only when a feature flag is on is missing while the flag is on
- `several-bad`: two or more settings are bad at once and the error must name all of them

Example: when outbound email is enabled, the mail host and sender address must both be set, and a missing one fails startup naming the key

Accepted tasks (2): [`fastapi-template/ff-001-email-config`](../tasks/fastapi-template/ff-001-email-config/instruction.md), [`miniflux/ff-001-create-admin-credentials`](../tasks/miniflux/ff-001-create-admin-credentials/instruction.md)

## 2. tolerant-typed-config

**accept the formats operators actually write.** typed settings accept the spellings operators really use for lists, booleans, numbers and durations, and reject garbage with a clear message naming the key and the bad value instead of a raw parser trace.

Attaches to: `settings-class`, `env-read`, `pool-config`, `validator` · languages: python, go · sampling weight: 12%

Injected faults:

- `csv-list`: a list setting is written as a comma-separated string, e.g. "a, b,c"
- `json-list`: a list setting is written as a json array string, e.g. '["a","b"]'
- `empty-list`: a list setting is set to an empty string and must become an empty list
- `bool-words`: a boolean setting is written as yes/no, on/off, 1/0 in any case
- `duration-suffix`: a duration setting is written with a unit suffix such as "30s", "5m", "2h" or "1d"
- `garbage`: a value that cannot be parsed must fail with an error naming the key and the bad value

Example: an allowed-origins list accepts "a.com,b.com", '["a.com","b.com"]' and "" alike

Accepted tasks: none yet.

## 3. cross-field-validation

**reject impossible combinations of settings or inputs.** configuration or request models reject combinations of fields that cannot both be true, such as a window that ends before it starts, a minimum above a maximum, or two mutually exclusive flags both on.

Attaches to: `settings-class`, `validator`, `pool-config` · languages: python, go · sampling weight: 10%

Injected faults:

- `inverted-range`: a lower bound is greater than its upper bound (min > max, start after end)
- `mutually-exclusive`: two flags that cannot both be enabled are both enabled
- `dependent-bound`: one value must stay below or within another, e.g. a timeout shorter than a total deadline
- `boundary-equal`: the equal-values boundary must follow the documented rule (allowed or rejected)
- `negative-or-zero`: a count, size or duration that must be positive is zero or negative

Example: a maintenance window with an end time before its start time is rejected

Accepted tasks: none yet.

## 4. idempotent-consumer

**make handlers safe to apply twice.** a handler that applies an external event, request or retried job produces the same end state when it runs twice or is retried after a partial failure, instead of duplicating rows, emails or counters.

Attaches to: `consumer`, `cache-key` · languages: python, go · sampling weight: 10%

Injected faults:

- `duplicate-delivery`: the same event or request is delivered twice with the same idempotency key
- `retry-after-partial`: the first attempt fails after a partial write and the retry must not double-apply
- `back-to-back-duplicate`: two deliveries of the same event are applied back to back before either reports a result
- `distinct-events`: two different events with different keys must both still apply

Example: a "create item" request retried by a client with the same request id creates one item, not two

Accepted tasks: none yet.

## 5. hot-reload-config

**dynamic settings take effect without a restart.** a setting that operators change at runtime is read through one accessor every time it is used, so a new value takes effect without a restart; a copy captured at import or construction time is the bug.

Attaches to: `settings-class`, `env-read`, `pool-config`, `validator` · languages: python, go · sampling weight: 8%

Injected faults:

- `stale-capture`: a module-level or struct-level copy of the value is taken once at startup and never refreshed
- `invalid-reload`: a reload supplies an invalid value; the previous good value must stay active and the error must be reported
- `partial-reload`: a reload changes two related values; readers must never observe the new one paired with the old one
- `reload-unset`: a key is removed on reload; the value must fall back to its documented default, not keep the stale one

Example: a request timeout raised by an operator applies to the next request, not only after a redeploy

Accepted tasks: none yet.

## 6. env-aware-naming

**environment-scoped cache, queue and topic names.** every cache key, queue, topic or bucket name is derived from the configured deployment environment or namespace, so two environments sharing infrastructure never read or overwrite each other's data.

Attaches to: `cache-key`, `consumer`, `settings-class`, `env-read` · languages: python, go · sampling weight: 10%

Injected faults:

- `unscoped-key`: a key or name is built without the environment prefix, so staging and production collide
- `wrong-env-source`: the name uses a hardcoded or default environment instead of the configured one
- `unknown-env`: the configured environment is empty or not one of the allowed values; building a name must fail fast
- `separator-injection`: an environment or id containing the separator character produces an ambiguous key that collides with another

Example: a session cache key carries the environment so a staging login never resolves against production

Accepted tasks: none yet.

## 7. resource-aware-defaults

**pool and worker sizes derive from configured limits.** connection pool, worker, batch and buffer sizes are derived from the limits the service is given (cpu, memory, max connections) instead of hardcoded numbers, and combinations that cannot work are rejected at startup.

Attaches to: `pool-config`, `settings-class`, `env-read` · languages: python, go · sampling weight: 14%

Injected faults:

- `hardcoded-size`: a size ignores the configured limit and uses a fixed number
- `min-over-max`: a minimum (pool min, workers) is configured above its maximum
- `exceeds-limit`: the derived total (workers x pool size, batch x item size) exceeds the configured hard limit
- `zero-or-negative`: a size or limit is zero or negative and would deadlock or crash later
- `unset-limit`: the limit is not configured; a documented safe default derived from the available resources must be used

Example: a database pool whose size is capped so workers times connections never exceeds the server's connection limit

Accepted tasks: none yet.

## 8. config-round-trip

**config load, modify, save never drops a field.** reading a configuration or settings record, changing one field and writing it back preserves every other field exactly, including ones that were explicitly set to a value equal to the default or to an empty value.

Attaches to: `config-writer`, `settings-class`, `validator` · languages: python, go · sampling weight: 20%

Injected faults:

- `dropped-field`: a field the writer does not know about, or did not change, disappears after save
- `default-overwrite`: an explicitly set value equal to the default, or an explicit empty or zero value, is replaced or omitted
- `type-drift`: a value changes type across the round trip (number to string, duration to integer, list to scalar)
- `partial-write`: a save that fails half-way leaves a truncated or mixed record instead of the previous one

Example: toggling one user preference and saving keeps every other preference the user had set

Accepted tasks: none yet.
