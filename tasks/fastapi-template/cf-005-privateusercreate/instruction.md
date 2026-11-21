# Reject impossible seed-user options on the private user endpoint

The local-only endpoint `POST {API_V1_STR}/private/users/` uses the request model `PrivateUserCreate` in `app.api.routes.private`. It creates seed and test accounts. QA wants to give these accounts an access window and to control whether a verification email is sent. Right now the endpoint accepts any combination of options. An account whose window ends before it starts, or an account marked as already verified that also asks for a verification email, would be accepted. The problem would only show up much later, when the account cannot be used.

Extend `PrivateUserCreate` and make it reject impossible combinations when the request is validated.

Requirements:

1. Add three optional fields to `PrivateUserCreate`. The existing fields and their defaults stay as they are.
   - `valid_from`: a datetime or `None`. Default `None`.
   - `valid_until`: a datetime or `None`. Default `None`.
   - `send_verification_email`: a bool. Default `False`.
2. **Access window.** When `valid_from` and `valid_until` are both set, `valid_from` must be strictly earlier than `valid_until`.
   - **Boundary rule:** if the two values are equal, the window has zero length and must be **rejected**.
   - If only one of the two fields is set, or neither is, there is nothing to check.
3. **Timezones.** A datetime without timezone information counts as UTC, so naive and timezone-aware values can be compared. Mixing the two must never cause a crash or a server error. The result must be either a normal successful validation or a normal validation error.
4. **Mutually exclusive flags.** `is_verified=True` together with `send_verification_email=True` must be rejected. Either flag on its own is valid.
5. **How rejection works.** Building the model raises pydantic's `ValidationError`, and the HTTP endpoint answers `422`.
   - The error message must name **both** fields involved: `valid_from` and `valid_until` for the window rule, `is_verified` and `send_verification_email` for the flag rule.
   - If both problems happen in one request, a single error must name all four fields.
6. Valid input keeps working exactly as before. This covers the shipped defaults (no new fields given), a correctly ordered window, and either flag on its own. The endpoint still creates the user and returns `200`.
7. The new fields are only validated. Storing them on the `User` table is out of scope. The repository's existing test suite must still pass.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
