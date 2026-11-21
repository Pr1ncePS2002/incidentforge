# Submission form text

Character counts are checked by `uv run python deck/check_form.py` (limit 1024 each).

## Prototype brief

IncidentForge turns any repo pinned at a commit into validated Harbor coding tasks built from what breaks in production: 8 families from recurring outage classes in a large e-commerce microservice fleet. A Failure Map (code graph tagged by family, with blast radius and real test coverage) decides where tasks go, untested risky code first, and parallel workers generate one task per independent cluster; tasks can also start from a public postmortem. Each task asks the model to add the missing protection and ships fault-injection tests. It is kept only if its tests fail on the base commit, pass with the reference, the repo suite stays green, mutants are caught, the instruction doesn't leak the answer and reruns agree. Dataset: 52 tasks on a Python and a Go repo, all gates passed, 89% of 309 mutants killed. Claude Code passes CC_RATE; Gemini 2.5/3.8 Flash via terminus-2 pass G25_RATE/G38_RATE. Every failed run gets one cause: CAUSE_SUMMARY.

## Tech stack

Python 3.12 with uv, typer and pydantic for the CLI (forge run / map / from-postmortem / validate / eval / report / budget). Harbor as task format and Docker runner; one image per target repo. Failure Map on code-review-graph 2.3.9 and tree-sitter, with real coverage from pytest-cov and go test; map page in D3, inlined so it works offline. Generation: Claude Code headless and the Gemini API behind one interface, parallel workers sharing a Docker slot pool. Evaluated: Harbor's Claude Code agent, and gemini-2.5-flash and gemini-3.8-flash through terminus-2. pytest and go test for feature, fault-injection and regression tests; mutation gate over the reference patch. A spend ledger enforces a $70 hard cap before every paid call (total SPEND). GitHub Actions: ruff, mypy strict, 90% branch coverage, secret scan, dependency audit, Docker integration with oracle 1.0 / no-op 0.0 on every task. Report on GitHub Pages; Codespaces devcontainer. MIT licence.
