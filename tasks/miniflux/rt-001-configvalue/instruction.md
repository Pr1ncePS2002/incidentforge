# Lossless updates to the Miniflux configuration file

Miniflux reads its settings from a `KEY=value` configuration file (`miniflux -config-file ...`, loaded by the config parser's `ParseFile`). Operators and tooling often need to change one setting in that file, for example to flip `LOG_LEVEL` during an incident. Today there is no writer for this file. Ad-hoc scripts rewrite it from the parsed options, and that loses data. Comments and keys Miniflux does not know about disappear. An explicitly set value that equals the default is dropped, so it silently follows future default changes. An explicit empty value turns into "unset". A crash half-way through leaves a truncated file.

Add a writer to package `internal/config` (`miniflux.app/v2/internal/config`) that makes load, modify, save lossless:

```
func UpdateConfigFile(filename string, set map[string]string, unset []string) error
```

## Behaviour

1. **Everything you did not ask to change is preserved byte for byte.** This covers comment lines (first non-blank character `#`), blank lines, lines without a key, keys unknown to Miniflux, their order, their spacing and the presence or absence of a final newline. A line is a setting when, after trimming, it does not start with `#` and contains `=` at a position greater than 0. Its key and value are the trimmed text before and after the first `=`. These are the same rules the file parser uses.
2. **Set.** For every key in `set`, the first line holding that key is replaced by `KEY=value` (no spaces). Later duplicate lines for that key are removed, so the file ends up with exactly one effective value. If the existing (trimmed) value already equals the requested value, keep the original line exactly as it was. Keys from `set` that are not yet in the file are appended at the end as `KEY=value`, one per line, in ascending key order.
3. **Explicit values are written explicitly.** A value equal to Miniflux's default (for example `LOG_LEVEL=info`) is still written. An empty string writes an explicit empty value, `KEY=`. That is not the same as removing the key.
4. **Unset.** Every line for a key listed in `unset` is removed. Unsetting a key that is not present changes nothing.
5. **No-op.** If the resulting content is identical to the current content (for example `set` and `unset` are both empty, or every value already matches), the file is not rewritten. If the file does not exist in that case, it is not created.
6. **Missing file.** A missing file is treated as empty and is created when there is something to write, with permissions `0600`. Content written to a new or previously empty file ends with a newline. If the existing file ended with a newline, the result does too. If it did not, the result does not either.
7. **Permissions.** When an existing file is rewritten, its permission bits are kept.

## Rejection and failure safety

`UpdateConfigFile` must return a non-nil error and leave the file **exactly as it was**, with no leftover temporary files next to it, when:

- a key in `set` or `unset` is empty or contains a character other than ASCII letters, digits and `_` (for example `BAD KEY` or `A=B`);
- a value contains a line break (`\n` or `\r`), because that would inject extra settings into the file;
- a value starts or ends with whitespace, because the parser trims it and the value could not round-trip;
- the same key appears in both `set` and `unset`;
- the resulting configuration is rejected by the configuration parser;
- reading, writing, syncing or replacing the file fails. The new content must be written to a temporary file in the same directory and then atomically renamed over the original, so a failed save never leaves a truncated or mixed file.

A file produced by `UpdateConfigFile` must still load with the parser's `ParseFile`. The existing behaviour of the configuration parser is unchanged, and the existing test suite must still pass.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
