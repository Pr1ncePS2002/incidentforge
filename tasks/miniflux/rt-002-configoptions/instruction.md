# Export environment settings into the configuration file without losing anything

Operators who move a Miniflux deployment from environment variables to a configuration file (or keep both in sync) need to write the current environment settings into an existing config file. Doing this by hand or with ad-hoc scripts loses data. Comments and keys the script doesn't know about disappear. Values that equal the default, or are explicitly empty, are dropped and later read back as something else. Values get normalised (`yes` becomes `true`). An interrupted write leaves a truncated file.

Add a lossless merge-writer to package `internal/config` (`miniflux.app/v2/internal/config`):

```go
func ExportEnvironmentToFile(filename string, environ []string) error
```

`environ` uses the `KEY=VALUE` form that `os.Environ()` returns. A value is everything after the first `=`.

Requirements:

1. **Only Miniflux settings are exported.** An entry is used only if its key is an option the configuration parser knows about (for example `LOG_LEVEL`, `POLLING_FREQUENCY`, `RUN_MIGRATIONS`, `OAUTH2_CLIENT_ID`). All other entries (`PATH`, `HOME`, …) are ignored. If the same key appears more than once, the last one wins.
2. **Nothing in the existing file is dropped.** Comment lines (`#`), blank lines, keys Miniflux doesn't know and settings not present in `environ` stay byte for byte, in their original order.
3. **Changing one field changes only that field.** An assignment line counts as a setting when, after trimming, it isn't empty, doesn't start with `#` and has a non-empty key before the first `=`. Keys and values are compared after trimming surrounding whitespace.
   - If a key from `environ` is already in the file with the same value, its line is left untouched (original spacing included).
   - If the value differs, the line is rewritten as `KEY=VALUE`. A trailing `\r` on that line is kept.
   - Keys from `environ` that aren't in the file are appended at the end as `KEY=VALUE` lines, in alphabetical order by key.
4. **Explicit values are kept verbatim.** A value equal to Miniflux's default is still written. An explicitly empty value is written as `KEY=` and must not be skipped or replaced. Values are never normalised or converted: `RUN_MIGRATIONS=yes` stays `yes`, and `POLLING_FREQUENCY=15` stays `15`.
5. **Load then save with no change is a no-op.** If nothing changes, the function returns `nil` and does not rewrite the file. A file that doesn't end in a newline, or uses `\r\n` line endings, stays byte-identical.
6. **When the file is written**, lines are joined with `\n` and the content ends with exactly one trailing `\n`. If the original file had no trailing newline, appended keys go on new lines after the last existing line.
7. **A failed save keeps the previous record.**
   - If any exported value contains a line break (`\n` or `\r`), return an error that names the key, and don't touch the file.
   - If the parser rejects the merged settings, return an error and don't touch the file.
   - The new content is written to a temporary file in the same directory and then renamed over the target. On failure, the original file stays intact and no temporary file is left in the directory.
8. **Permissions:** an existing file keeps its permission bits. A file that doesn't exist yet is created with mode `0600`. If the file exists but can't be read, return an error.
9. The result must be loadable with the existing configuration file parser (`NewConfigParser().ParseFile(filename)`).
10. Existing configuration parsing behaviour and the repository's existing test suite are unchanged.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
