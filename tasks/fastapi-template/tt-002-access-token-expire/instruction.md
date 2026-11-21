# Load the extra CORS origins however operators write them

The backend settings (`app.core.config.Settings`) only know one browser origin, `FRONTEND_HOST`. Operators need to allow more origins, such as an admin console or a staging frontend. When list settings like this are rolled out, the same value turns up in several spellings: a JSON array (`["https://a.example.com","https://b.example.com"]`), a comma-separated string (`https://a.example.com, https://b.example.com`), or an empty string meaning "none". A typed list binding that only accepts JSON crashes the service at startup with an unreadable parser trace.

Add a new setting, `BACKEND_CORS_ORIGINS`, that holds the extra allowed origins. Also add a computed setting, `all_cors_origins`, that gives the full list of allowed origins.

Requirements:

1. `BACKEND_CORS_ORIGINS` defaults to an empty list. Once `Settings` is built, it is always a plain `list[str]`.
2. These inputs must all produce the same list. This holds whether the value comes from the environment variable `BACKEND_CORS_ORIGINS` or is passed to `Settings(...)` as a keyword argument:
   - a real Python list of strings (the canonical form)
   - a JSON array string, e.g. `'["http://localhost:3000","https://app.example.com"]'`
   - a comma-separated string, e.g. `"http://localhost:3000, https://app.example.com"`
3. Normalisation applies to every spelling:
   - strip whitespace around each entry
   - drop entries that are empty or blank (e.g. `"a,,b,"`)
   - remove trailing `/` from each origin, so `https://app.example.com/` becomes `https://app.example.com`
4. An empty or whitespace-only string, and the JSON array `[]`, give an empty list.
5. Each origin must start with `http://` or `https://`. Reject the value if:
   - an entry has no such scheme (e.g. `localhost:3000` or `ftp://files.example.com`)
   - a string that starts with `[` is not valid JSON
   - a JSON array holds anything other than strings
   - the value is not a list or a string at all

   Rejection means constructing `Settings` raises a `ValueError` (pydantic's `ValidationError` counts). The error message must contain the name `BACKEND_CORS_ORIGINS` and the offending input exactly as given (the raw value, or the bad entry).
6. `all_cors_origins` is `FRONTEND_HOST` with any trailing `/` removed, followed by the entries of `BACKEND_CORS_ORIGINS` in order, with duplicates removed.
7. Existing settings behave as before, and the repository's existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
