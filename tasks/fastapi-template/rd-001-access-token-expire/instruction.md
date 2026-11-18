# Keep access token lifetime within its configured bounds

`app.core.config.Settings.ACCESS_TOKEN_EXPIRE_MINUTES` sets how long issued access tokens stay valid. The default is a fixed 8 days (`60 * 24 * 8` = 11520 minutes). Nothing checks this value or limits it. A value of `0` or below makes every token expire as soon as it is issued, so every login fails afterwards. Security teams also have no way to set an upper limit on token lifetime, so a typo like `ACCESS_TOKEN_EXPIRE_MINUTES=1000000` goes unnoticed.

Add an optional hard ceiling. Work out the effective lifetime from it, and reject impossible combinations when `Settings` is constructed.

Requirements:

1. Add a new setting, `ACCESS_TOKEN_MAX_EXPIRE_MINUTES` (integer, optional, default unset/`None`). It is the hard upper limit for access token lifetime, in minutes.
2. `ACCESS_TOKEN_EXPIRE_MINUTES` must be at least 1. Zero or negative values must be rejected, and the error must name `ACCESS_TOKEN_EXPIRE_MINUTES`.
3. If `ACCESS_TOKEN_MAX_EXPIRE_MINUTES` is set, it must be at least 1. Zero or negative values must be rejected, and the error must name `ACCESS_TOKEN_MAX_EXPIRE_MINUTES`.
4. If the ceiling is set and `ACCESS_TOKEN_EXPIRE_MINUTES` is given explicitly (as a constructor argument or an environment variable) with a value above the ceiling, reject it with one error that names **both** `ACCESS_TOKEN_EXPIRE_MINUTES` and `ACCESS_TOKEN_MAX_EXPIRE_MINUTES`. A value equal to the ceiling is allowed.
5. If the ceiling is set and `ACCESS_TOKEN_EXPIRE_MINUTES` is **not** given explicitly, use the formula `min(11520, ACCESS_TOKEN_MAX_EXPIRE_MINUTES)`, and store the result in `ACCESS_TOKEN_EXPIRE_MINUTES` so that everything reading the setting uses the derived value. Do not keep the fixed 11520.
6. If the ceiling is unset, behaviour does not change. The default stays 11520, and any explicit positive value is accepted as-is.
7. Rejection means constructing `Settings` raises a `ValueError` (pydantic's `ValidationError` counts).
8. The shipped defaults must still load, and the existing test suite must still pass.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
