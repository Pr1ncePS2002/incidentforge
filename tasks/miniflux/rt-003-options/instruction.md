# Lossless read/update of HTTP client options files

The HTTP client package (`internal/http/client`) describes its behaviour with `client.Options` (`Timeout time.Duration`, `BlockPrivateNetworks bool`). Operators want to keep these settings in a small JSON file that other tools also write to, and change one setting at a time. Naive "unmarshal into a struct, change it, marshal it back" writers lose data: unknown keys disappear, explicit `false` / `"0s"` values get dropped or replaced, durations turn into integer nanoseconds, and a failed save can leave a truncated file. Add a reader and a lossless updater for this record.

## File format

A JSON object. Known keys:

- `"timeout"`: a Go duration **string** (anything `time.ParseDuration` accepts, e.g. `"30s"`, `"1m30s"`, `"0s"`). Negative durations are invalid.
- `"block_private_networks"`: a JSON boolean.

Any other key may be present and belongs to other tools. A known key that is absent leaves the field at its zero value.

## API (package `client`, `miniflux.app/v2/internal/http/client`)

1. `func ReadOptionsFile(path string) (Options, error)`
   - Returns the decoded options.
   - Returns an error if the file can't be read, isn't a JSON object (e.g. an array, `null` or invalid JSON), if `timeout` isn't a string, can't be parsed as a duration or is negative, or if `block_private_networks` isn't a boolean.

2. `func UpdateOptionsFile(path string, mutate func(*Options) error) error`
   - Loads the file (same rules and errors as `ReadOptionsFile`), calls `mutate` on a copy of the loaded options (`mutate` may be nil), then saves.
   - **No change means no write:** if no field's value differs from what was loaded, the file stays byte-for-byte as it was.
   - **Only changed fields are rewritten:** a known key whose field value didn't change keeps its original JSON value exactly (e.g. `"1m30s"` stays `"1m30s"`). A changed `Timeout` is written as a duration string (`Duration.String()`, e.g. `"45s"`), never as a number. A changed `BlockPrivateNetworks` is written as a JSON boolean.
   - **Unknown keys are kept** with their values and JSON types (objects, lists, numbers, strings, including empty strings).
   - **Explicit values and absence stay distinct:** a known key that is present with a zero value (`false`, `"0s"`) stays present. A known key that is absent stays absent unless the mutation changes that field. Changing a field to its zero value writes the explicit zero value and never removes the key.
   - **A failed save keeps the previous record:** if `mutate` returns an error, `UpdateOptionsFile` returns an error that wraps it (it must work with `errors.Is`) and the file is untouched. If the mutated `Timeout` is negative, it returns an error and the file is untouched. The new content is written to a temporary file in the same directory, then renamed over the original. No temporary files are left behind, whether the save succeeds or fails.
   - After a successful update, `ReadOptionsFile` returns the mutated options.

Existing behaviour of the client package is unchanged, and the existing test suite must still pass.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
