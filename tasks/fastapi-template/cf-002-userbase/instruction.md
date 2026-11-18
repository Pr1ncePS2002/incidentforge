# Reject impossible user account states at validation time

User account data is described by `UserBase` in `backend/app/models.py`. `UserCreate` and the other user schemas inherit from it. Each field is checked on its own, so some combinations that cannot work are still accepted:

- **A disabled superuser.** An admin can send `POST /api/v1/users/` with `"is_superuser": true` and `"is_active": false`. The account is stored, but the inactive flag stops it from logging in or using any admin power. Nobody notices until someone tries to use that admin account during an incident.
- **A blank display name.** `full_name` accepts `""` or a string of only spaces. Later, every screen that shows the user's name shows nothing at all instead of falling back to the email address, which it does only when the name is missing (`null`).

Make `UserBase` reject these states when the data is validated, so bad input fails right away with a clear error.

## Requirements

1. **Superuser must be active.** If `is_superuser` is `true` and `is_active` is `false`, reject the data. The error message must name **both** `is_superuser` and `is_active`.
   - Every other combination stays valid: an active superuser, an active regular user, and an inactive regular user.
2. **`full_name` must be missing or have real content.** `full_name` may be `null` or not given at all. If it is given, it must contain at least one character that is not whitespace. An empty string or a whitespace-only string must be rejected, and the error must name `full_name`.
3. **Boundary rule:** a `full_name` of exactly one non-whitespace character (for example `"A"`) is valid. A `full_name` of exactly 255 characters (the existing maximum length) is still valid. A string whose length is zero after removing whitespace is invalid.
4. If more than one problem is present, one error must name every field involved.
5. Rejection means building the model raises pydantic's `ValidationError`. This covers `UserBase` and `UserCreate`. Over the HTTP API, `POST /api/v1/users/` with an impossible combination must return `422` and must not create the user.
6. The shipped defaults (`is_active=True`, `is_superuser=False`, `full_name=None`) still validate, and the existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
