# Submission form text

Character counts are checked by `uv run python deck/check_form.py` (limit 1024 each).

## Prototype brief

IncidentForge turns any repo pinned at a commit into validated Harbor coding tasks built from what breaks in production: 8 families from recurring outage classes in a large e-commerce microservice fleet (missing or malformed config, impossible settings, stale reload, environment-blind keys, duplicate messages, lossy config regeneration, resource-blind defaults). Each task asks the model to add the missing protection and ships fault-injection tests. A task is kept only if its tests fail on the base commit, pass with the reference, the repo suite stays green, mutants are caught, the instruction doesn't leak the answer and reruns agree. Dataset: 34 tasks on a Python and a Go repo, all gates passed, 89% of 201 mutants killed. Claude Code agent passes 98%; Gemini 2.5/3.8 Flash via terminus-2 pass 33%/28%, and their failures hit fault tests 49 times vs 21 on the happy path. An unseen repo yielded 3 accepted tasks in 20 minutes.

## Tech stack

Python 3.12 with uv, typer and pydantic for the CLI pipeline (forge run / validate / eval / report / budget). Harbor as the task format and Docker-based runner; one Docker image per target repo with its services inside. Generation backends: Claude Code in headless mode and the Gemini API behind one pluggable interface. Evaluated: Harbor's Claude Code agent, and gemini-2.5-flash and gemini-3.8-flash through Harbor's terminus-2 agent. Code-surface finders for Python and Go; pytest and go test for feature, fault-injection and regression tests; a mutation gate over the reference patch. Static HTML report. A local spend ledger enforces a $70 hard cap on paid API use before every call (total spend $43.96). GitHub Actions CI: ruff, mypy strict, unit tests with 75% branch coverage, secret scan, dependency audit, and nightly Docker integration that re-checks every task with the oracle (reward 1.0) and no-op (0.0) agents. MIT licence.
