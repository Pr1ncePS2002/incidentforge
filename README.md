# IncidentForge

**A coding task factory whose tasks come from what actually breaks in production.**

IncidentForge takes any repository pinned at a commit and turns it into feature-development tasks for
evaluating AI coding systems. Each task asks the model to add the protection that would have prevented a
recurring class of production outage, ships in [Harbor](https://github.com/harbor-framework/harbor) format,
and is kept only after six automatic validation gates pass.

> Innodata AI Hackathon 2026 · Track 1 (Coding Task Factory) · Team CHAOS · MIT licence

## The problem

Most generated coding benchmarks ask a model to "invent a feature for this repo". The resulting tasks
are generic, exercise the happy path, and say little about whether the code would survive production.
In a large e-commerce microservice fleet, a small number of failure classes cause a large share of real
outages: services that crash on a missing setting, configs written in a format the parser does not
accept, impossible settings combinations, reloads that never take effect, and so on. These are exactly
the paths AI-written code tends to skip.

## Task families

Eight families, each derived from a recurring production failure class. Every task pairs feature tests
with **fault-injection tests** that recreate the failure.

| # | Family | The model must… | Fault the tests inject |
|---|---|---|---|
| 1 | `fail-fast-config` | refuse to start on missing or empty required settings, with a clear error | required setting unset / blank |
| 2 | `tolerant-typed-config` | parse list/number/bool settings from the formats operators actually write | `"a, b"`, `"1_000"`, `"Yes"`, garbage |
| 3 | `cross-field-validation` | reject impossible combinations | start after end, min above max |
| 4 | `idempotent-consumer` | apply a duplicate or retried message only once | redelivery, retry after partial failure |
| 5 | `hot-reload-config` | make dynamic values take effect without a restart | value changed at runtime |
| 6 | `env-aware-naming` | keep cache/queue keys correct across environments | same key in two environments |
| 7 | `resource-aware-defaults` | derive pool/worker sizes from limits, not constants | small container limit |
| 8 | `config-round-trip` | regenerate config without dropping or defaulting fields | load → save → load diff |

Details and a sample task per family: [docs/families.md](docs/families.md).

## How it works

![pipeline](docs/img/pipeline.svg)

1. **Target**: a repo URL + pinned commit + an environment template (Dockerfile and a `run_tests` helper) in
   `src/incidentforge/targets/`.
2. **Surface finder**: locates code a family can attach to (settings classes, env reads, validators,
   message handlers, cache keys, config writers, pool settings), for Python and Go.
3. **Generator**: a family prompt plus the surface go to a backend (Claude Code headless or Gemini), which
   returns the instruction, a reference patch, feature tests and the fault cases.
4. **Validation gates**: the task is accepted only if the tests fail on the base commit, pass with the
   reference patch, the repo's own suite stays green, mutated reference patches are caught, the
   instruction does not leak the solution, and the tests are stable across reruns. A rejected task gets
   one retry with the failure reason fed back.
5. **Package**: a complete Harbor task directory (see [docs/task-format.md](docs/task-format.md)).
6. **Evaluate and report**: Harbor runs each model on every task in Docker; `forge report` writes a static
   HTML report and `reports/summary.json`.

Module map and data flow: [docs/architecture.md](docs/architecture.md).

## Quickstart

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), Docker, and the Harbor CLI
(`uv tool install harbor==0.26.0`). For generation, either the Claude Code CLI or a Gemini API key.

```bash
git clone https://github.com/Pr1ncePS2002/incidentforge && cd incidentforge
uv sync
cp .env.example .env            # add GEMINI_API_KEY (free tier is enough to generate)

# generate, validate and keep tasks for a target
uv run forge run --target fastapi-template --family fail-fast-config --n 2

# re-run every validation gate on the dataset
uv run forge validate tasks

# check the tasks in Harbor: the reference solution scores 1.0, doing nothing scores 0.0
harbor run -p tasks -a oracle
harbor run -p tasks -a nop

# evaluate models and build the report
uv run forge eval --tasks tasks --model gemini/gemini-3.8-flash
uv run forge report             # writes reports/index.html

# paid-key spend against the hard cap
uv run forge budget
```

## Adding a new target repo

1. Add `src/incidentforge/targets/<name>.yaml` with `repo_url`, `commit`, `language` (`python` | `go`),
   `env_template`, `test_command` and `source_root`.
2. Copy the closest env template under `src/incidentforge/targets/env/` and adjust the Dockerfile so the
   repo's own test suite passes via `run_tests`.
3. `uv run forge run --target <name> --n 3`.

`scripts/finale_dry_run.sh <repo_url> <commit> <language>` does all three and prints timings; the event
playbook is in [docs/finale-playbook.md](docs/finale-playbook.md).

## Results

<!-- results:start (generated by scripts/readme_results.py from reports/summary.json) -->

Evaluation results land here once `forge eval` + `forge report` have run on the full dataset.

<!-- results:end -->

Refresh this block with `uv run python scripts/readme_results.py` after `forge report`.

## Validation evidence

Every accepted task has a JSON log in `reports/validation/<task_id>.json` with the result and timing of each
gate and the number of mutants killed. CI re-runs the oracle and no-op agents on every committed task
before anything reaches `main`, and nightly on `develop`.

## Cost control

All Gemini calls go through one backend that tries the free key first. The paid key is used only under a
hard spend cap checked **before** each call against a local ledger; `forge budget` shows spend against the
cap and whether the remaining evaluation fits.

## Limitations

- Task families target configuration, startup and message-handling code; they do not cover UI or
  performance work.
- Targets need a Dockerised test suite that runs offline in a single container.
- Generated tasks are only as diverse as the surfaces found in the repo; a small repo yields fewer tasks
  per family.
- Model results are from single runs (k=1) on the full set plus k=3 on a subset, so small differences are
  within noise.

## Development

```bash
uv lock --check && uv run ruff check src tests && uv run ruff format --check src tests \
  && uv run mypy && uv run pytest -q --cov
```

Branches: `ftr/*` → `develop` → `main`. CI gates: lint (ruff, mypy strict), unit tests (branch coverage
≥ 75%), security (secret scan, dependency audit), and a Docker integration stage before `main`.

## Licence

[MIT](LICENSE)
