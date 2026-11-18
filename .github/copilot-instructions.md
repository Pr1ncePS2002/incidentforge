# Review guidance for IncidentForge

Review for bugs and gaps, not style. ruff, ruff format and mypy strict already run in CI, so skip formatting,
naming and typing nits.

Flag, with a concrete failing input or scenario:

- **Correctness:** wrong logic, unhandled `None` or empty inputs, off-by-one errors, swallowed exceptions,
  subprocess calls whose exit code is ignored.
- **Validation gates (`src/incidentforge/validate/`):** any change that lets a bad task pass, such as a gate
  that returns success on error, a mutant that is never run, or flakiness reruns being skipped.
- **Task packages (`tasks/**`):**
  - `tests/test.sh` must write a reward of 0 on any failure;
  - `solution/solve.sh` must apply cleanly;
  - `instruction.md` must not leak the solution.
- **Spend safety (`budget.py`, `backends/gemini.py`):** any path that calls the paid key without a ledger
  reservation, raises `HARD_CAP_USD`, or records cost after the call can no longer be recorded.
- **Secrets:** keys or tokens printed, logged, committed or passed to processes that don't need them.
- **Concurrency:** shared files (ledger, `tasks/`, `reports/`) written by parallel workers without a lock.
- **Missing tests:** new behaviour or branches with no unit test, and bug fixes with no regression test.
- **CI (`.github/workflows/`):** a weakened or skipped gate, actions not pinned by SHA, floating dependency
  versions.

If the PR has no real issue, say so in one line instead of inventing one.
