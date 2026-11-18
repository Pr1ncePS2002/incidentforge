# Edit user-creation drafts without losing data

Admins and onboarding tools prepare users ahead of time as **draft files**: a JSON object on disk with the fields of a `UserCreate` (`email`, `password`, `full_name`, `is_active`, `is_superuser`). Other tools can also add their own keys, such as a team name, a quota or a list of tags. Today the backend has no safe way to change a draft. Ad-hoc scripts load the draft into a `UserCreate`, change one field and dump it back. That drops every key the model doesn't know. It also fills in or rewrites values the draft never set, turns explicit `null`/empty values into something else, and can leave a half-written file if the process dies during the save.

Add a new module `app/user_drafts.py` (package path `app.user_drafts`) that exposes a function `edit_user_draft`. Its first argument is the draft path (a `str` or a path-like object). Its second, optional argument is a mapping of changes (field name to new value). It returns the validated `UserCreate`.

Required behaviour:

1. **Validation first.** Merge the stored record with the changes. Changes win, and keys in the changes that are not yet in the draft are added. Validate the `UserCreate` fields of the merged record with `UserCreate`. If validation fails (for example, a password that is too short or a malformed email), raise a `ValueError`; pydantic's `ValidationError` counts. Leave the file on disk byte-for-byte unchanged.
2. **No-op round trip.** If you call it with no changes, or with changes equal to the stored values, the file must not be rewritten. Its bytes stay identical.
3. **Only the changed field changes.** Every other key keeps exactly its previous value after a save. This covers keys `UserCreate` does not know about, and their position in the object is irrelevant.
4. **Unset vs explicit.** If a `UserCreate` field such as `is_active` is absent from the draft, it must stay absent after a save. Do not write defaults in. If a field is explicitly set to its default value (for example `"is_superuser": false`), or to an explicit `null` or empty string (for example `full_name`), it must keep that exact value.
5. **No type drift.** Untouched values keep their JSON type: integers stay integers, floats stay floats, lists stay lists, objects stay objects, booleans stay booleans. Changed `UserCreate` fields are stored with the field's own type after validation. For example, changing `is_active` to the string `"false"` stores the JSON boolean `false`, not a string.
6. **Atomic save.** Write the new content to a temporary file in the same directory, then move it over the draft with `os.replace` (called through the `os` module). If anything fails during the save, including `os.replace` raising, the error must propagate. The previous draft must stay intact, and no temporary file may be left in the directory.
7. If the file does not contain a JSON object (for example, it contains a list), raise `ValueError`.
8. Existing behaviour of `UserCreate` and the rest of the backend is unchanged, and the existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
