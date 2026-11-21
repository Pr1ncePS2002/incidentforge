# Lossless editing of the backend `.env` file

`app.core.config.Settings` loads its values from a dotenv file (the top-level `.env`). Nothing in the backend can safely *write* that file. Ops scripts that change one setting rewrite the whole file. When they do, unknown keys and comments get dropped. Explicit values equal to the default, and explicit empty values, are omitted. Booleans and numbers come back in a different form. A crash during the save leaves a truncated `.env`.

Add a writer for this record in a new module, `app.core.env_file`, that makes the load → modify → save round trip lossless.

## API

- `read_env_file(path) -> dict[str, str]`
  - Returns every assignment in the dotenv file at `path` (a `str` or `os.PathLike`), mapped to its raw string value.
  - A missing file returns `{}`.
  - Blank lines and lines starting with `#` are ignored.
  - An optional `export ` prefix is accepted.
  - Single-quoted and double-quoted values are unquoted. Double quotes support backslash escapes such as `\\`, `\"` and `\n`.
  - For unquoted values, an inline comment (whitespace followed by `#`) is stripped.
  - `KEY=` maps to `""`. A key that does not appear in the file is absent from the result, so unset and explicitly empty stay distinguishable.
  - If a key appears more than once, the last occurrence wins.
- `update_env_file(path, changes: Mapping[str, object]) -> None`
  - Applies `changes` to the file at `path`.
  - Creates the file if it does not exist.

## Requirements for `update_env_file`

1. **No-op saves are no-ops.** If, after applying `changes`, no value would differ, the file must not be rewritten at all; its bytes stay identical. This covers both `changes={}` and passing back exactly what `read_env_file` returned.
2. **Only changed fields change.** For each key whose value changes, rewrite only that assignment line. Keep everything else byte-for-byte:
   - comments and blank lines
   - line order
   - keys `Settings` does not know about
   - untouched assignments, including their quoting and line endings (`\r\n` included)
   - a missing final newline
3. **New keys** are appended at the end as `KEY=value` lines.
4. **Value conversion** (the value written must read back as exactly this string):
   - `bool` becomes `true` / `false`.
   - `int` / `float` becomes its decimal `str()`.
   - `str` is written as is.
   - `list` / `tuple` / `dict` becomes JSON.
   - `None` removes every assignment of that key (unset).
   - `""` writes an explicit empty assignment (`KEY=`) and must not be dropped.
   - Values equal to a `Settings` default, and zero or `false` values, must be written explicitly. Never omit them.
   - Any other type raises `TypeError`.
5. **Quoting.** Quote values as needed so they read back identically, both through `read_env_file` and through `Settings(_env_file=path)`. This includes values containing spaces, `#`, quotes, backslashes or newlines. Numbers and booleans must reload into `Settings` with their proper types.
6. **Key names** must match `[A-Za-z_][A-Za-z0-9_]*`. Any other key raises `ValueError`.
7. **Atomic save.** Validate and convert all values before touching the file. An invalid value or key leaves the file unchanged. Write the new content to a temporary file in the same directory, then move it into place with `os.replace`. If any step fails, including `os.replace` itself:
   - the error propagates,
   - the previous file is left intact,
   - no temporary file is left behind.

`Settings` and all existing behaviour are unchanged, and the existing test suite must still pass.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
