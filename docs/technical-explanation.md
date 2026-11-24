# Technical explanation

This document covers what the submission guide asks for: design decisions, core assumptions, reused
components, model choices, the task variation strategy, the validation matrix and reward rule, mutation
testing, and the manual fixes applied to the dataset. Every tool and model the pipeline uses is listed in
[Reused components](#reused-components) and [Model choices](#model-choices).

The submission target is **pallets/click 8.5.1** (commit `cf19179e8e2fd54c601378cec9e0d21bb12b6fb1`,
BSD-3-Clause). The pipeline also runs on two other repositories (fastapi-template in Python and miniflux in
Go); their tasks are kept in `tasks/` as extra evidence that the factory is not tied to one repo, and their
numbers are reported separately from the click results.

## Design decisions

**Tasks come from outage classes, not from "invent a feature".** A generator asked to invent a feature for
a repo produces generic, happy-path work. Real outages cluster into a small number of recurring classes:
a service that starts with a missing setting and fails on first use, a value written in a format the parser
rejects, two settings that cannot both be true, a reload that never takes effect, a retried message applied
twice. Each class becomes a family (eight in total, see [families.md](families.md)). A task asks for the
feature that would have prevented that class of failure on a specific piece of the target's code, and its
tests inject the fault that caused it. The families were derived from the failure classes of a large
e-commerce platform's microservice fleet; their sampling weights follow how often each class occurs.

**A failure map decides where tasks go.** `forge map build` builds a code graph of the repo
(code-review-graph, plus our own nodes for config reads, environment reads and handlers), tags each node
with the families that can attach to it, computes its blast radius (how many files a change there reaches),
and runs the repo's test suite once with coverage to mark which nodes are tested. Surfaces are ranked so
untested, risky code comes first. The flat AST surface finders (`surfaces/python.py`, `surfaces/go.py`)
remain as the fallback when no map exists.

**Six validation gates, all automatic.** A generated task is kept only if:

| Gate | Check |
|---|---|
| `leak` | the instruction shares under 30% of the reference patch's 8-grams and copies no code line |
| `fail_on_base` | feature tests fail on the untouched start commit |
| `pass_on_reference` | feature tests pass with the reference patch applied |
| `regression` | the repo's own test suite still passes with the reference patch |
| `mutation` | at least one mutated copy of the reference patch is caught (up to 6 mutants per task) |
| `flakiness` | three oracle runs give the same reward |

A rejected candidate gets one retry with the failing gate's reason added to the prompt; a second rejection
drops it. Each task's gate results and timings are written to `reports/validation/<target>/<task>.json`.

**Harbor packaging.** Every task is a Harbor task directory (layout in [task-format.md](task-format.md)), so
the same package is used for validation (Harbor's `oracle` and `nop` agents), for evaluation (Harbor's
model agents), and by judges. The verifier runs in the agent's container (`environment_mode = "shared"`),
so the tests see exactly the code the agent left. Feature tests are copied in only after the agent stops.

**Parallel workers per map cluster.** `forge run --workers N` splits the map into clusters that share no
file and runs one worker per cluster. A candidate patch may only edit its own cluster's files, so two tasks
from the same run never edit the same file. All workers share one pool of Docker slots (4 containers by
default), and task ids are assigned once, at merge, under a file lock.

**Postmortem entry point.** `forge from-postmortem <url> --target <name>` reads a public incident report,
classifies it into a family and a trigger, picks the best matching surface from the map, and runs the same
generator and gates. The report URL is stored as `source_url` in `task.toml`. `--family` overrides the
classifier; when it is used, the classifier's own answer is kept as `classifier_family`.

**One cause per failed model run.** The report assigns every failed evaluation run exactly one cause: it
used every turn, it broke the repo's own tests, it missed an injected fault, or it wrote wrong code. This
makes the results explain where models fail rather than only how often.

## Core assumptions

- The start commit builds and its existing test suite passes inside one Docker container, offline. For
  click this is `pip install -e .` and `pytest` at the 8.5.1 commit.
- Tasks are feature additions or changes to existing behaviour, never bug fixes, and every task starts from
  the unmodified start commit.
- The generated feature does not already exist upstream; `fail_on_base` checks this mechanically.
- Tests need no network access and no real credentials. Fault injection is done with environment variables,
  temporary files and in-process fakes.
- The instruction is the only thing the agent sees; it describes behaviour, not the code to write.
- One reference solution per task is enough to prove solvability; the mutation gate is what shows the
  tests are not satisfied by a plausible but wrong solution.
- The family taxonomy generalises beyond the services it was drawn from: configuration loading, input
  validation, retries and reloads exist in any non-trivial codebase, including a CLI toolkit such as click
  (option parsing, defaults, environment-variable fallbacks, parameter types).

## Reused components

| Component | Version | Used for |
|---|---|---|
| [Harbor](https://github.com/harbor-framework/harbor) | 0.25.0 | task format, Docker execution, the `oracle` and `nop` agents for validation, and evaluation |
| Harbor `terminus-2` agent | bundled with Harbor | evaluating Gemini models (calls the model through litellm) |
| Harbor `claude-code` agent adapter | bundled with Harbor | evaluating Claude Code as a coding agent |
| [code-review-graph](https://github.com/tirth8205/code-review-graph) | 2.3.9 | code graph behind the failure map |
| tree-sitter, tree-sitter-language-pack | 0.26.1, 0.13.0 | parsing for the code graph and surface finders |
| Python `ast` | stdlib | Python surface finder and Python mutation operators |
| pytest, pytest-cov | 9.2.0, 7.1.0 | target test suites (click, fastapi-template), coverage for the failure map, our own unit tests |
| `go test` | Go 1.26 toolchain in the task image | miniflux test suite and coverage |
| Docker | host install | every task environment and test run |
| google-genai | 3.5.0 | Gemini API client for the Gemini generator backend |
| Claude Code CLI | host install | headless generator backend (`claude -p`) |
| pydantic, typer, pyyaml | 2.14.3, 0.29.1, 6.0.3 | shared data contracts, CLI, target and family files |
| D3 | 7.9.0 (vendored) | the interactive failure map page `reports/map.html` |
| headless Chrome | host install | PNG export of the failure map |
| mutmut, hypothesis | 3.8.1, 6.170.15 | mutation testing and property tests of our own code |
| ruff, mypy, pip-audit, TruffleHog | 0.17.5, 2.4.1, 2.10.1, 3.99.9 | lint, type checks, dependency audit, secret scan |
| GitHub Actions, GitHub Pages, Codespaces | n/a | CI, the published report, a ready-to-run dev container |
| uv | 0.11 | Python environment and lockfile |

## Model choices

**Task generation.** Generation goes through a `Backend` interface (`backends/base.py`). Supported
implementations:

- `claude-code` (`backends/claude_code.py`, the default): the Claude Code CLI in headless mode,
  `claude -p --output-format json --json-schema <schema>`, with tools, MCP servers and user settings
  turned off so the prompt carries all context. No model is pinned; the CLI's default model is used unless
  `--model` is passed. Every committed task (click and the other repositories) was generated with this
  backend, and the postmortem classifier also runs on it.
- `gemini` (`backends/gemini.py`): the Gemini API through google-genai, default model `gemini-3.8-flash`.
  It implements the same interface and is covered by tests, but no committed task was generated with it.
- `codex`, `opencode`, `gemini-cli` and `command` (`backends/cli.py`): other coding CLIs on their own login,
  headless with tools off (`codex exec -s read-only`, `opencode run` with every permission denied,
  `gemini --output-format json`), or any user command that prints JSON (`--backend-command` /
  `FORGE_GEN_COMMAND`). The JSON schema goes in the prompt and the answer is checked and retried once, as
  for Gemini. They are unit-tested with fake executables; `gemini-cli` is built from its documented flags and
  has not been run against the real binary. None of them generated a committed task: the committed dataset
  is `claude-code` only.

`forge eval` support for non-Claude Harbor CLI agents (codex, gemini-cli, opencode) is a follow-up.

**Evaluated models.** All evaluation runs go through Harbor (`forge eval`):

| Model | Agent | Notes |
|---|---|---|
| Claude Code (default) | Harbor `claude-code` agent | account default model, no turn cap set by us |
| `anthropic/claude-opus-5-5` | Harbor `claude-code` agent | pinned with `-m`; click only |
| `anthropic/claude-sonnet-5-5` | Harbor `claude-code` agent | pinned with `-m`; click only |
| `anthropic/claude-haiku-5-5` | Harbor `claude-code` agent | pinned with `-m`; click only |
| `anthropic/claude-fable-5-2` | Harbor `claude-code` agent | pinned with `-m`; click only |
| `gemini/gemini-2.5-flash` | Harbor `terminus-2` | 30 turns per run; 60-turn ablation on a subset |
| `gemini/gemini-3.8-flash` | Harbor `terminus-2` | 30 turns per run; 60-turn ablation on a subset |
| `gemini/gemini-4-hydrogen` | Harbor `terminus-2` | tried and excluded from scoring: through terminus-2 nearly every turn came back empty or unparseable, so a 0% would measure the harness, not the model (`reports/eval/excluded.json`) |

The two agents differ, so pass rates compare models only within one agent.

Click evaluation: every model above except `gemini-4-hydrogen` ran once (k=1) on each of the 10 click
tasks with Harbor 0.25.0: the two Gemini models through terminus-2 with a 30-turn cap, and five Claude
models through the claude-code agent with no turn cap (the account default plus four pinned with
`forge eval --agent claude-code --model anthropic/<id>`, which passes `-m` to Harbor). All five Claude
models solved 10 of 10; gemini-3.8-flash solved 4 and gemini-2.5-flash 2. 13 of the 14 failed runs used
all 30 turns. Runs that ended without a verifier reward (provider limits, network failures while building
the image or installing the agent) are re-run, not scored. Every click run scored 0.0 or 1.0, so mean
reward equals pass rate here.

## Task variation strategy

The guide requires tasks that differ in behaviour, rules or interactions, not in wording. Variation comes
from three independent axes, and two mechanisms remove what is left over.

1. **Family**: eight failure classes ask for different behaviour (refuse to start, parse leniently, reject
   combinations, deduplicate, reload, namespace, derive limits, round-trip without loss).
2. **Code surface**: each task is pinned to a different node of the failure map; within one run, map
   clusters share no file, so two tasks never ask for a change to the same code.
3. **Injected fault cases**: each task lists its own fault cases (`fault_cases` in `task.toml`), drawn from
   the family's fault catalogue and specialised to the surface, and its tests inject each one.

Near-duplicates are dropped rather than kept as variants. The prompt lists every kept title of the same
family on the same target, `forge run --workers` rejects a title whose word set overlaps a kept one by 80%
or more, and tasks are reviewed by hand for same-behaviour-different-title cases (see
[Manual fixes](#manual-fixes)).

**On click** the 10 tasks cover five of the eight families: tolerant-typed 4, cross-field 2,
env-aware-naming 2, fail-fast 1, resource-aware-defaults 1. The other three were not applied to click
because a CLI library has no natural surface for them: hot-reload would tag every environment read (click
reads env vars once per invocation, there is no long-running process to reload), and click has no config
writer for a round-trip or message handler for an idempotent consumer. The click target profile
(`src/incidentforge/families/targets/click/profile.yaml`) leaves them out so the generator is never asked for them.

Difficulty is labelled by the number of fault cases (easy ≤ 3, medium 4–5, hard ≥ 6); the size of the fix
is a separate `fix_scope` label (1 file, 2–3 files, 4+ files) from the blast radius.

## Validation matrix and reward

Each task must pass the guide's two Harbor checks:

```bash
harbor run -p <task_dir> -a nop    -k 1 -o <out_dir> --no-delete -y   # expected reward 0.0
harbor run -p <task_dir> -a oracle -k 1 -o <out_dir> --no-delete -y   # expected reward 1.0
```

`tests/test.sh` runs the feature tests and the repo's existing regression tests, listed in
`tests/fail_to_pass.json` and `tests/pass_to_pass.json`, and writes the reward:

- 0.0 if any regression test fails;
- 1.0 if every feature test passes;
- otherwise the share of feature tests that pass.

Feature tests that already pass on the base commit (happy-path checks such as "shipped defaults still
validate") are treated SWE-bench style: they are listed in `pass_to_pass.json` as guards rather than in
`fail_to_pass.json`, so a no-op scores exactly 0.0 and breaking a guard scores 0.0 like any regression.
The `fail_on_base` gate does this split automatically from the per-test results of the no-op run.

A null reward means the environment crashed and the run is retried, not scored. The fastapi-template and
miniflux numbers in the README were measured earlier with an all-or-nothing reward and Harbor 0.26.0;
the click numbers use the rule above and Harbor 0.25.0.

Click nop/oracle matrix (Harbor 0.25.0, one run per agent per task, `reports/validation/click/matrix.json`):
the no-op agent scored 0.0 on 10 of 10 tasks and the oracle scored 1.0 on 10 of 10.

## Mutation testing

Mutation testing is applied at two levels.

**Task tests (the `mutation` gate).** For every candidate, up to six mutants of the reference patch are
built by changing only lines the patch adds: for Python, AST operators (`negate_if`, `drop_raise`,
`drop_call`, `flip_compare`, `return_early`); for Go, text operators that keep the code compiling (flip a
comparison or logical operator, negate or disable an `if`, drop an error return or a statement). Each mutant
is run through Harbor's oracle agent; a task is kept only if its tests catch at least one, and the counts
are kept in the validation log. On the 52 tasks of the other repositories the accepted tasks' tests killed
276 of 309 mutants (89%).

On the 10 click tasks the tests killed 55 of 56 mutants (98%).

**Our own code.** mutmut runs nightly over the modules listed in `[tool.mutmut]` in `pyproject.toml`
(the gate code in `validate/`, `ci_checks.py`, `budget.py`); a surviving mutant
outside `tests/mutation-allowlist.txt` fails the job (`scripts/mutation_gate.py`). The last full run
killed 1474 of 1506 mutants (97.9%); the 32 survivors are reviewed equivalent mutants.

## Manual fixes

Generation, validation and packaging are automatic. These are the changes made by hand to the dataset, and
why. Tasks dropped by the gates are not listed; only human decisions are.

| Task | What was done by hand | Why |
|---|---|---|
| fastapi-template/ff-001-email-config | written by hand (`origin = "hand-written"`) | gold task used to prove the Harbor setup and as the prompt's worked example |
| miniflux/ff-001-create-admin-credentials | written by hand (`origin = "hand-written"`) | gold task for the Go target and the Go mutation operators |
| miniflux/hr-002-configoptions | dropped after acceptance | near-duplicate of hr-001 (same reloadable options holder) |
| miniflux/cf-001-configvalue (first version) | dropped after acceptance | the base commit already rejected both configs; its fault tests failed only on error-message wording. The Go output contract now requires fault tests to fail because behaviour is missing |
| miniflux/cf-002 (first version) | dropped after acceptance | near-duplicate of that cf-001 |
| miniflux/rt-003-configparser (first version) | dropped after acceptance | overlapped rt-001's unset path |
| fastapi-template/rd-002-email-reset-token | dropped after acceptance | same pool-from-connection-budget idea as rd-003 |
| fastapi-template/ic-006-create-user | dropped after acceptance | near-duplicate of ic-001 (same idempotent `create_user`, only adds email normalisation) |
| fastapi-template/en-004-settings | family set with `--family env-aware-naming` | the postmortem classifier answered "none" for the source incident; the override and the classifier's answer are both recorded in `task.toml` |
| fastapi-template/rd-004-email-reset-token | family set with `--family resource-aware-defaults` | the classifier answered fail-fast-config; recorded as above |
| fastapi-template/ff-005-create-engine-7 | `classifier_family` line added after generation | generated before the classifier's answer was written automatically |
| `gemini/gemini-4-hydrogen` (evaluation) | excluded from scoring | harness incompatibility, see Model choices |
| click (all tasks) | none: no click task was hand-edited | 4 candidates were dropped: 2 near-duplicates at generation (ff-002, cf-004) and 2 after independent review (cf-001: one rule already enforced on base so its tests only checked wording; en-002: reference applied the new env-var naming to value lookup but not to the `--help` display) |

Dropped tasks are not committed; ids are not reused, which is why some ids are missing from the sequence.

Known limitations kept as generated (no hand edits): `click/tt-001-convert` has no zero-duration test case,
and `click/tt-003-convert` has four `test_fault_garbage_*` tests that already pass on the base commit, so
they are listed in `pass_to_pass.json` and act as guards rather than fault tests.

## Where the evidence lives

| Evidence | Location |
|---|---|
| Gate results, timings, mutants killed per task | `reports/validation/<target>/<task>.json` |
| Evaluation results per run | `reports/eval/results.jsonl`, `reports/eval/trials.jsonl` |
| Excluded models and why | `reports/eval/excluded.json` |
| Aggregated numbers | `reports/summary.json`, `reports/index.html` |
| Failure map | `reports/map.html`, `reports/map/<target>.json` |
| CI runs (oracle and nop on every committed task) | GitHub Actions, `integration` job |
