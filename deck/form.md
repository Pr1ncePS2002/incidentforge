# Submission form text

Character counts are checked by `uv run python deck/check_form.py` (limit 1024 each).

## Prototype brief

IncidentForge is a coding task factory. Given any repository pinned at a commit, it generates feature-development tasks in Harbor format, validates each one automatically, evaluates AI models on them and reports results. Its tasks come from what actually breaks in production: 8 task families derived from recurring outage classes in a large e-commerce microservice fleet (missing or malformed config, impossible settings, stale hot reload, environment-blind keys, duplicate messages, lossy config regeneration, resource-blind defaults). Each task asks the model to add the protection that would have prevented the outage and ships fault-injection tests that recreate the failure. A task is kept only if its tests fail on the base commit, pass with the reference solution, the repo's own suite stays green, mutated solutions are caught, the instruction does not leak the answer and reruns agree. One command per repo; shown on a Python and a Go repo.

## Tech stack

Python 3.12 with uv, typer and pydantic for the CLI pipeline (forge run / validate / eval / report / budget). Harbor as the task format and Docker-based runner; one Docker image per target repo with its services inside. Generation backends: Claude Code in headless mode and the Gemini API behind one pluggable interface; Gemini models and Harbor's Claude Code agent as the evaluated systems. Code-surface finders for Python and Go; pytest and go test for feature, fault-injection and regression tests; a mutation gate over the reference patch. Static HTML report. A local spend ledger enforces a hard cap on paid API use before every call. GitHub Actions CI: ruff, mypy strict, unit tests with 75% branch coverage, secret scan, dependency audit, and nightly Docker integration that re-checks every task with the oracle (reward 1.0) and no-op (0.0) agents. MIT licence.
