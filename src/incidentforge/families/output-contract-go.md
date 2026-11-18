## output contract

Reply with exactly one json object and nothing else (no prose, no code fences). Keys:

- `title` (string): short task title, lower case, no trailing period.
- `instruction` (string, markdown): what the engineer must build, written as a product/ops requirement.
  Name the behaviour, the exported functions or methods the tests call (package, name, signature), the
  settings or inputs involved and the expected error behaviour precisely enough that the hidden tests are
  fair. Never include code from the solution, never mention the hidden tests.
- `solution_patch` (string): a unified diff (`git diff` format, `--- a/<path>` / `+++ b/<path>` headers,
  paths relative to the repository root, correct `@@` hunk line counts) that applies with `git apply` on
  the pinned commit and implements the feature. Context lines must match the pinned code exactly (tabs, not
  spaces) and the result must be `gofmt`-clean and compile. Change only application code; do not add or
  edit `_test.go` files in the patch. Use only the standard library and modules already in `go.mod`.
  The package's existing tests run together with yours and must keep passing: do not change shipped
  defaults or reject combinations that existing tests build (check the package's `*_test.go` files for
  the values they set), and do not duplicate a check the code already performs.
- `feature_tests` (object): repository-relative path → file content. One or two Go test files named
  `*_test.go`, placed in the directory of the package under test (for example
  `internal/config/forge_feature_test.go`) and declaring that same package, so unexported identifiers are
  reachable. The path must contain at least one directory: a bare file name is packaged under `tests/`,
  so never attach a task to the package at the repository root (usually `package main`). Use only the standard `testing` package. They must fail on the pinned commit (a compile error
  because the new function does not exist yet counts as failing) and pass with the patch applied. Each
  fault you list below needs at least one test that injects it, named `TestFault<FaultId>` (fault id in
  CamelCase, an extra suffix is fine, e.g. `TestFaultPlaceholderSecretKey`). Tests of normal, unchanged
  behaviour must not contain the word `Fault` in their names (e.g. `TestValidConfigStillLoads`). Tests must
  be deterministic, use no network and no sleeps, set environment variables only with `t.Setenv`, write
  files only under `t.TempDir()`, and be free of data races. Do not redeclare identifiers that already
  exist in the package's other test files.
- `fault_cases` (array of strings): one line per injected fault, starting with its catalogue id, e.g.
  `"placeholder: SECRET_KEY left as changethis"`.
- `difficulty` (string): `easy`, `medium` or `hard`.

If the protection already exists at this surface, pick a different behaviour the code does not yet protect
against; the tests must fail on the pinned commit.
