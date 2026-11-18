# Task format

Every task is a [Harbor](https://github.com/harbor-framework/harbor) task directory, written by
`package.write_task`:

```
tasks/<target>/<task-id>/
├── task.toml            # metadata: family, difficulty, timeouts, environment_mode = "shared"
├── instruction.md       # what the agent is asked to build; never contains the solution
├── environment/
│   ├── Dockerfile       # the target repo at its pinned commit, deps installed, services inside
│   └── run_tests.sh     # runs the repo's own test suite
├── solution/
│   ├── solve.sh         # applies the reference patch with git apply (used by the oracle agent)
│   └── solution.patch
└── tests/
    ├── test.sh          # runs feature tests + repo suite, writes the reward (1 or 0)
    └── test_*.py | *_test.go   # feature and fault-injection tests
```

The agent sees only the environment and `instruction.md`. Tests are copied in after the agent finishes, so
they cannot be read or edited during the attempt. Reward is 1 only when every feature test **and** the
repo's existing suite pass.

## Validation gates

A task is accepted only when all gates pass. Results are written to `reports/validation/<task_id>.json`.

| Gate | What it runs | What it proves |
|---|---|---|
| `fail_on_base` | feature tests on the untouched base commit | the feature really is missing; the task is not already solved |
| `pass_on_reference` | feature tests after the reference patch | the task is solvable and the tests are correct |
| `regression` | the repo's own suite with the reference patch | the requested change does not require breaking existing behaviour |
| `mutation` | feature tests against mutated copies of the reference patch (dropped checks, flipped conditions, removed fault handling) | the tests are strong enough to catch a plausible but wrong solution, including on the failure paths |
| `leak` | the instruction compared against the patch | the instruction describes behaviour, not the code to write |
| `flakiness` | the passing run repeated three times | the reward does not depend on timing or ordering |

The fault-injection tests are what make a family more than a feature request: each recreates the
production failure (missing setting, malformed value, duplicate delivery, …) and checks the code now
handles it.

## Harbor checks

```bash
harbor run -p tasks -a oracle    # every task must score 1.0
harbor run -p tasks -a nop       # every task must score 0.0
```

CI runs both on every committed task before `main` and nightly on `develop`.
