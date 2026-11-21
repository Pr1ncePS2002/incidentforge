# Reject impossible credential length policies for the login form

The login form (package `internal/ui/form`, type `authForm`, fields `Username` and `Password`) only checks that both fields are non-empty. We want operators to be able to set length limits on login credentials. The risk is a policy that no credential can ever satisfy, such as a minimum above its maximum or a zero or negative limit. Today nothing would catch that: the policy would be accepted, and then every login would fail later with a confusing "wrong credentials"-style error. Catch impossible policies when they are validated.

## What to build (package `miniflux.app/v2/internal/ui/form`)

1. An exported struct `AuthPolicy` with four `int` fields: `MinUsernameLength`, `MaxUsernameLength`, `MinPasswordLength`, `MaxPasswordLength`. Lengths are counted in characters (Unicode code points / runes), not bytes.
2. `func DefaultAuthPolicy() AuthPolicy` returning the shipped defaults: username 1..255, password 1..1024. These defaults must validate.
3. `func (p AuthPolicy) Validate() error`:
   - Each of the four limits must be strictly positive. A zero or negative value returns an error that names the offending field by its Go field name (e.g. `MinPasswordLength`).
   - An inverted range (`MinUsernameLength > MaxUsernameLength`, or `MinPasswordLength > MaxPasswordLength`) returns an error that names **both** fields of that pair (for example both `MinUsernameLength` and `MaxUsernameLength`). It must not name the fields of the other, valid pair.
   - **Boundary rule:** equal values are allowed. `Min == Max` is a valid policy and means the length must be exactly that value.
   - A valid policy returns `nil`.
4. `func (a authForm) ValidateWithPolicy(p AuthPolicy) error`:
   - If `p.Validate()` fails, return a non-nil error that includes that policy error's message (so it still names the fields), whatever the form contains.
   - Otherwise, an empty username or password returns an error.
   - Otherwise, a username or password whose length (in characters) is outside `[Min, Max]` (inclusive) for its pair returns an error.
   - Otherwise it returns `nil`.
5. The existing `authForm.Validate()` keeps its current behaviour. The existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
