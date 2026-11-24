# Task format

Every task is a [Harbor](https://github.com/harbor-framework/harbor) 0.25 task directory, written by
`package.write_task`:

```
tasks/<target>/<task-id>/
├── task.toml            # metadata (repo_url, 40-char base_commit, licence, family, difficulty,
│                        # fault cases, generator), timeouts, verifier environment_mode = "shared"
├── instruction.md       # what the agent is asked to build; never contains the solution
├── environment/
│   ├── Dockerfile       # the target repo at /app, pinned via ARG REPO_URL / ARG REPO_COMMIT
│   └── run_tests.sh     # installed as `run_tests`; runs the repo's own test suite
├── solution/
│   ├── solve.sh         # git apply of the reference patch (used by the oracle agent)
│   └── reference.patch
└── tests/
    ├── test.sh          # copies feature tests in, runs them, removes them, runs the repo suite
    ├── fail_to_pass.json  # feature test ids: fail on the base commit, pass with the reference patch
    ├── pass_to_pass.json  # tests that pass before and after: the repo suite + base-passing feature tests
    └── feature/         # feature + fault-injection tests (fault tests are named test_fault_<id>)
```

The agent sees only the environment and `instruction.md`. Tests are copied in after the agent finishes, so
they cannot be read or edited during the attempt.

### Reward

```
reward = 0.0                                       if any pass_to_pass test fails
reward = passing fail_to_pass tests / fail_to_pass   otherwise (1.0 when all of them pass)
```

So the untouched repo (`nop`) scores 0.0 and the reference patch (`oracle`) scores 1.0; a partial solution
scores the share of `fail_to_pass` tests it gets right. `test.sh` writes `/logs/verifier/reward.json`:

```json
{"reward": 0.6667, "feature_tests": 0.6667, "repo_suite": 1}
```

`feature_tests` is the passing share of `fail_to_pass` (0..1) and `repo_suite` is 1 only when the repo suite
and every guard pass. It also writes a CTRF report
(`ctrf.json`) with one aggregate entry each for `feature_tests` and `repo_suite` plus one entry per feature
test, and the logs `feature_tests.log` and `repo_suite.log`. Per-test status comes from pytest's `-rA` summary
lines, or from `go test -v -run '^(TestA|TestB)$'` `--- PASS` lines run once per feature package, so the
script needs nothing beyond bash and awk in the image.

### Test ids

Ids follow SWE-bench and are relative to the target's source root (where `test.sh` runs):

| language | `fail_to_pass.json` / `pass_to_pass.json` id |
|---|---|
| python | `tests/test_forge_x.py::test_fault_missing_host`, `tests/test_x.py::TestCls::test_y` |
| go | `internal/config::TestFaultEmptyBaseURL` (package dir, `.` for the module root) |

Feature test ids are read from the feature test sources (`test*` functions and `Test*` class methods, or
`func TestX(t *testing.T)`). Some feature tests check behaviour that already works on the base commit (for
example "the shipped defaults still validate"). Following SWE-bench, those are not `fail_to_pass`: the
`fail_on_base` gate reads the per-test result of the `nop` run, moves every feature test that passed there to
`pass_to_pass` as a *guard*, rewrites the task and runs `nop` again. Guards still run with the feature tests,
and a failing guard zeroes the reward like any other regression. `pass_to_pass` is collected once per target and commit inside the target image
(`run_tests --collect-only -q` or `go test -list . ./...`) and cached under `.cache/p2p/`.

`forge rerender tasks/` rewrites existing tasks in the current format (test.sh, both id lists, task.toml) and
keeps their instruction, patch, tests, extra metadata and guard split; `--nop-job <harbor job dir>` also
moves the feature tests that passed in that `nop` job to guards.

## Validation gates

A task is accepted only when all gates pass. Results are written to `reports/validation/<task_id>.json`.

| Gate | What it runs | What it proves |
|---|---|---|
| `fail_on_base` | feature tests on the untouched base commit (`nop` must score 0.0; base-passing tests become guards) | the feature really is missing; the task is not already solved |
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
harbor run -p <task_dir> -a nop -k 1 -o <out_dir> --no-delete -y      # must score 0.0
harbor run -p <task_dir> -a oracle -k 1 -o <out_dir> --no-delete -y   # must score 1.0
```

`-p tasks/<target>` runs the same check over every task of a target.

CI runs both on every committed task before `main` and nightly on `develop`.
