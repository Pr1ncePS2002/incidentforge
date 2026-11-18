# Refuse to start with blank or placeholder core settings

The backend builds its configuration in `app.core.config.Settings`. Pydantic already rejects a required setting that is missing entirely. It does not reject one that is present but useless. If a deployment sets `SECRET_KEY`, `PROJECT_NAME` or `FIRST_SUPERUSER_PASSWORD` to an empty string, to whitespace only, or leaves template text such as `todo` or `<fill-me>` in it, the service starts normally. It then signs tokens with a trivial key, shows a blank project name in emails, or creates the first superuser with a guessable password. The only placeholder caught today is the literal `changethis`.

Make `Settings` reject these values when it is constructed, so a misconfigured deployment fails at startup.

Requirements:

1. Apply these checks to `SECRET_KEY`, `PROJECT_NAME` and `FIRST_SUPERUSER_PASSWORD`.
2. **Empty:** reject a value that is empty or contains only whitespace.
3. **Placeholder:** after removing surrounding whitespace, reject a value that is any of the following:
   - one of these words, ignoring case: `todo`, `tbd`, `fixme`, `changeme`, `replaceme`, `replace-me`, `xxx`
   - text wrapped in angle brackets, for example `<fill-me>` or `<your-secret-here>`
4. Only reject a value that is one of these placeholders as a whole. A value that merely contains one of the words (for example `todo-app` or `my-todo-secret-123`) is valid.
5. Leave the existing handling of the literal `changethis` exactly as it is: a warning in development, rejection otherwise.
6. **Several bad values:** if more than one of the three settings is bad, raise one error whose message names **every** offending setting, not just the first one found.
7. Rejection means constructing `Settings` raises a `ValueError`. Pydantic's `ValidationError` counts.
8. Valid configurations, including the repository's shipped defaults, must still load unchanged, and the existing test suite must still pass.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
