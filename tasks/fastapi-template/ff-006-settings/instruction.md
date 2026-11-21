# Fail fast on unusable routing settings

The backend reads two routing settings in `app.core.config.Settings`:

- `API_V1_STR`: the prefix every versioned API router is mounted under (default `/api/v1`).
- `FRONTEND_HOST`: the base URL of the frontend. It is used to build the links in outgoing emails, such as the password-reset link (default `http://localhost:5173`).

Right now the settings accept any string for both. If a deployment leaves `FRONTEND_HOST` blank or as a template placeholder, the service starts normally. Then every password-reset email has a broken link, and nobody notices until users complain. A malformed `API_V1_STR` (empty, missing the leading `/`, or ending in `/`) also gets past settings validation and only fails later, when the routers are mounted.

Change `Settings` so that it refuses unusable values for these two settings when it is constructed.

Requirements:

1. `API_V1_STR` must be rejected if:
   - it is empty or only whitespace,
   - it still holds a template placeholder (see below),
   - it does not start with `/`,
   - it ends with `/` (this includes a bare `/`), or
   - it has leading or trailing whitespace.
2. `FRONTEND_HOST` must be rejected if:
   - it is empty or only whitespace,
   - it still holds a template placeholder, or
   - it is not an absolute URL with an `http` or `https` scheme and a host (for example, `localhost:5173` or `ftp://example.com` must be rejected).
3. Placeholder values are matched case-insensitively and ignore surrounding whitespace. They are: `changethis`, `changeme`, `change-me`, `todo`, `tbd`, `fixme`, `xxx`, and any value wrapped in angle brackets such as `<fill-me>`.
4. Rejection means that constructing `Settings` raises a `ValueError`. Pydantic's `ValidationError` counts. The error happens at construction time, not when the value is first used.
5. If several of these problems exist at once, a single error must name **every** offending setting (`API_V1_STR`, `FRONTEND_HOST`), not just the first one found.
6. The shipped defaults (`/api/v1` and `http://localhost:5173`) and other well-formed values (for example, `/api/v2` and `https://dashboard.example.com`) still load unchanged. The existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
