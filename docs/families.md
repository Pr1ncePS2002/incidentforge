# Task families

Each family is a recurring production failure class seen across a large e-commerce microservice fleet,
rewritten as a feature request: "add the protection that would have prevented this outage". Family
definitions (surface kinds, prompt, fault cases) live in `src/incidentforge/families/<slug>/`.

Sample task links are filled once the dataset is generated.

## 1. fail-fast-config

**Failure class:** a service starts with a required setting missing or blank, runs in a broken state, and
fails later on the first request that needs it.
**Task:** validate required settings at startup and refuse to start with an error naming the setting.
**Injected faults:** setting unset; set to an empty or whitespace-only string.
**Sample:** _TBD_ (gold task `tasks/fastapi-template/ff-001-*`)

## 2. tolerant-typed-config

**Failure class:** a config value written in a perfectly reasonable format (`"a, b"`, `"1_000"`, `"Yes"`)
fails typed binding and the service crashes, or garbage is silently coerced to a default.
**Task:** accept the formats operators actually write and reject invalid values with a clear message.
**Injected faults:** comma lists with spaces, JSON lists, case variants of booleans, non-numeric numbers.
**Sample:** _TBD_

## 3. cross-field-validation

**Failure class:** each setting is valid on its own but the combination is impossible (a window whose
start is after its end, a minimum above the maximum), and the service behaves wrongly instead of failing.
**Task:** reject impossible combinations at load time.
**Injected faults:** start after end, min above max, equal bounds where the range must be non-empty.
**Sample:** _TBD_

## 4. idempotent-consumer

**Failure class:** a message is redelivered or retried after a partial failure and its effect is applied
twice.
**Task:** make the handler apply each message once, keyed on a stable message identity.
**Injected faults:** exact duplicate, retry after the handler failed midway, concurrent duplicates.
**Sample:** _TBD_

## 5. hot-reload-config

**Failure class:** a dynamic setting is changed at runtime but the code read it once at startup, so the
change silently has no effect.
**Task:** make the value take effect without a restart.
**Injected faults:** value changed after startup; invalid new value (old value must be kept).
**Sample:** _TBD_

## 6. env-aware-naming

**Failure class:** cache or queue names built without the environment, so two environments share or
overwrite each other's data.
**Task:** derive keys from the environment and keep them stable within one.
**Injected faults:** same logical key in two environments; missing environment name.
**Sample:** _TBD_

## 7. resource-aware-defaults

**Failure class:** pool, worker or heap sizes hardcoded for a large machine, so the service is killed or
starves inside a small container.
**Task:** derive defaults from the resource limits available, with an explicit override.
**Injected faults:** small CPU/memory limit, override present, limits unavailable.
**Sample:** _TBD_

## 8. config-round-trip

**Failure class:** a tool regenerates a config file and drops or silently defaults a field it does not know.
**Task:** make load → save → load lossless, including unknown fields.
**Injected faults:** unknown field, field equal to its default, nested optional field.
**Sample:** _TBD_

## Sampling

`forge run` without `--family` picks families with weights proportional to how often each failure class
occurs (`families/taxonomy.json`), so the dataset mix follows production reality rather than being uniform.
