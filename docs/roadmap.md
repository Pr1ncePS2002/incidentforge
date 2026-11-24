# Roadmap

IncidentForge is built in five phases. Each phase ends with a gate that must pass before the next starts.

| Phase | Scope | Exit gate |
|---|---|---|
| 1. Foundation | Harbor running locally; primary target repo (`fastapi/full-stack-fastapi-template`, pinned commit) boots with Postgres inside a single task container and its test suite passes; one hand-written gold task (fail-fast config) | gold task scores 1.0 with the oracle agent and 0.0 with the no-op agent |
| 2. Factory core | pluggable generator backends (Claude Code headless, Gemini); Python code-surface finder; validation gates; families 1-4 | ≥12 accepted generated tasks, each with a validation log |
| 3. Scale | families 5-8; frequency-weighted family sampling; Go target repo | ~40 accepted tasks across 8 families and 2 languages |
| 4. Evaluation | `forge eval` over the dataset with one generic harness; `forge report` static HTML | report regenerates from a clean clone with one command |
| 5. Packaging | README, architecture, technical explanation, demo; dry run on an unseen repo | end-to-end run on a fresh repo succeeds |

## Task families

Derived from recurring production failure classes in a large e-commerce microservice fleet.

1. fail-fast config: refuse to start on missing or empty required settings, with a clear error
2. tolerant typed config: parse list/number/bool settings from the formats operators actually write, reject garbage cleanly
3. cross-field validation: reject impossible combinations (start after end, min above max)
4. idempotent consumer: duplicate or retried messages must not apply twice
5. hot-reload config: dynamic values take effect without a restart
6. environment-aware naming: cache/queue keys stay correct across environments
7. resource-aware defaults: pool/worker sizes derive from limits instead of hardcoded values
8. config round-trip: regenerating config never drops or silently defaults a field

## Validation gates (every task)

- feature tests fail on the base commit and pass with the reference solution
- the repository's existing test suite stays green
- mutated variants of the reference solution are caught by the tests
- the instruction does not leak the solution; tests are stable across three reruns
