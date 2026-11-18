# Lossless read-modify-write for exported user records

Ops tooling keeps per-user snapshots as JSON files. Each file is one JSON object holding the `UserBase` fields (`email`, `is_active`, `is_superuser`, `full_name`) plus any other keys that other tools wrote, such as ids, timestamps, team names or nested preference objects. Scripts load a snapshot, change one field and save it back. Today nothing in the backend owns this round trip, and the ad-hoc scripts lose data in several ways:

- keys they don't know about disappear
- explicit `false`, `null` or `""` values get dropped or replaced by model defaults
- values change type (for example `"false"` gets stored for a boolean, a tuple turns into a list, a datetime turns into a string)
- a crash mid-save leaves a truncated file

Add a new module `app.user_record` (file `backend/app/user_record.py`) that makes this round trip lossless. It must expose:

- `UserRecordError`: an exception that subclasses `ValueError`.
- `load_user_record(path) -> dict`: reads the JSON file and returns the object with every key and value exactly as stored. It raises `UserRecordError` in these cases:
  - the file is not valid JSON
  - the top level is not a JSON object
  - the record fails validation (see rules below)
- `save_user_record(path, record) -> None`: validates the record and then writes it.
- `update_user_record(path, changes) -> dict`: loads the record, applies the `changes` mapping (keys not in `changes` stay untouched, new keys may be added), saves the result and returns the updated record.

Paths may be `str` or `pathlib.Path`.

## Rules

1. **No-change round trip.** If you load a record and save it with no change, re-reading the file gives a semantically identical object: same keys, same values, same value types. If the content already on disk is exactly what would be written, saving must not rewrite the file. In that case the save must not perform a file replace at all.
2. **Changing one field changes only that field.** Every other key keeps its value and its type, including keys that are not `UserBase` fields. Keys keep their original order.
3. **Unset and explicit values stay distinct.** A `UserBase` field that is absent from the record stays absent after an update; it is not filled in with its default. A field explicitly set to its default (`is_superuser: false`, `is_active: true`), to `null`, to `""` or to `0` is kept exactly as is.
4. **No type drift.** `UserBase` fields are checked strictly, with no coercion: `is_active`/`is_superuser` must be real booleans (not strings or numbers), `email` must be a valid email string and `full_name` must be a string or null, within the model's length limits. All values anywhere in the record, nested ones included, must be JSON-native: null, bool, int, finite float, str, list, or object with string keys. Anything that would come back as a different type or cannot be stored (tuples, sets, datetimes, NaN/inf) is rejected with `UserRecordError`, never silently converted. The email value is stored exactly as given (no case normalisation).
5. **Atomic save.** Validation happens before the file is touched. If validation fails, or if writing, flushing, fsyncing or replacing the file fails, the previous file stays byte-for-byte intact, the original exception (or `UserRecordError` for validation problems) propagates, and no temporary files are left in the directory. Saving to a path that does not exist yet creates the file.
6. Existing models, CRUD and API behaviour are unchanged, and the existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
