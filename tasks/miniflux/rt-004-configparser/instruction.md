# Rename configuration keys without losing anything

Operators run Miniflux from a `KEY=VALUE` configuration file (the one read by the config parser's `ParseFile`). When an option is renamed or deprecated, they move the old key to the new name with ad-hoc `sed` scripts or small tools that read the file, rebuild it and write it back. Those tools often lose data. They drop comments and keys they don't know about. They drop explicitly empty values such as `ADMIN_PASSWORD=`, or rewrite values (`1h30m`, `007` and quoted strings come back in a different form). If they fail partway through, they leave a truncated file, and Miniflux then starts with a different configuration.

Add a key-rename writer to package `internal/config` (`miniflux.app/v2/internal/config`) that makes this round trip lossless.

## API

```
func RenameConfigKeys(filename string, renames map[string]string) error
```

`renames` maps an old key name to a new key name.

## Behaviour

1. **Only the key text changes.** For every non-comment line whose key (the text before the first `=`, ignoring surrounding spaces and tabs) matches an old name, replace only the key text with the new name. These stay byte-for-byte identical: whitespace before the key, whitespace between the key and `=`, and everything from `=` onwards (the raw value, including empty or whitespace-only values, quotes, inner spaces, leading zeros, duration strings and the line ending, `\n` or `\r\n`).
2. **Nothing else is touched.** Comment lines (first non-blank character `#`, indented or not), blank lines, keys that are not renamed (including keys Miniflux does not know about), line order and the presence or absence of a final newline must be kept exactly.
3. **No-op means no write.** If no line matches (including a `nil` or empty map), return `nil` and leave the file alone: same content, same modification time.
4. **Invalid input is rejected before anything is written.** Return an error and leave the file byte-for-byte unchanged when:
   - a non-blank, non-comment line has no `=`, or has an empty key;
   - after the rename, a key produced by a rename would be defined more than once (for example, the new name already exists in the file);
   - a rename entry is invalid: an empty old or new name, a name containing `=` or whitespace, a name starting with `#`, an old name equal to its new name, or a new name that is also an old name in the same map (chained renames);
   - the file does not exist or is not a regular file. A missing file must not be created.
5. **Atomic save.** When the file changes, write the new content to a temporary file in the same directory and rename it over the original. Keep the original file's permission bits (for example, a `0640` file stays `0640`). On success, and on any failure, no temporary files may be left in the directory. A failed save must always leave the previous file in place.
6. A renamed file must still load through the existing parser (`NewConfigParser()` followed by `ParseFile`) with the renamed values in effect.
7. Existing parsing behaviour and the existing test suite are unchanged.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
