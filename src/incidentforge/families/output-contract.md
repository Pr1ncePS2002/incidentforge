## output contract

Reply with exactly one json object and nothing else (no prose, no code fences). Keys:

- `title` (string): short task title, lower case, no trailing period.
- `instruction` (string, markdown): what the engineer must build, written as a product/ops requirement.
  Name the behaviour, the settings or inputs involved and the expected error behaviour precisely enough
  that the hidden tests are fair. Never include code from the solution, never mention the hidden tests.
- `solution_patch` (string): a unified diff (`git diff` format, `--- a/<path>` / `+++ b/<path>` headers,
  paths relative to the repository root, correct `@@` hunk line counts) that applies with `git apply` on
  the pinned commit and implements the feature. Context lines must match the pinned code exactly.
  Change only application code; do not add or edit test files in the patch.
- `feature_tests` (object): file name → file content. One or two pytest files named `test_*.py`.
  They run from the source root with the repository installed, so import application modules by their
  package path (for example `from app.core import config`). They must fail on the pinned commit and pass
  with the patch applied. Each fault you list below needs at least one test that injects it, named
  `test_fault_<fault_id>` (fault id with `-` turned into `_`, an extra suffix is fine, e.g.
  `test_fault_placeholder_secret_key`). Tests of normal, unchanged behaviour must not contain the word
  `fault` in their names (e.g. `test_valid_config_still_loads`). Tests must be
  deterministic, use no network and no sleeps, and set environment through `monkeypatch`, never by
  mutating `os.environ` globally. A bare file name is placed in the repository's own tests directory
  (e.g. `tests/test_x.py` under the source root), so the repo's conftest fixtures and test helpers are
  available and the database is up. When a test builds a settings object, turn off dotenv loading
  (pydantic-settings: `Settings(_env_file=None)`) and pass every required field explicitly. Never write
  api keys, tokens or credential-shaped urls in tests or patches; a database url with a password may only
  point at `localhost`.
- `fault_cases` (array of strings): one line per injected fault, starting with its catalogue id, e.g.
  `"placeholder: SECRET_KEY left as changethis"`.
- `difficulty` (string): `easy`, `medium` or `hard`.

If the protection already exists at this surface, pick a different behaviour the code does not yet protect
against; the tests must fail on the pinned commit.
