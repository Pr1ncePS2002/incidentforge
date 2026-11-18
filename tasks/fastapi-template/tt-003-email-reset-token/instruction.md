# Let operators write the BCC recipient list the way they actually write lists

The backend reads its email settings (`SMTP_*`, `EMAILS_FROM_*`, `EMAIL_RESET_TOKEN_EXPIRE_HOURS`) in `app.core.config.Settings`. Ops wants a list of extra addresses (for example an audit mailbox) that are blind-copied on outgoing email such as password-reset mail. Add a new setting for this: **`EMAILS_BCC`**, a list of email addresses that defaults to an empty list.

Operators set this from env files and deployment manifests, and they write lists in different ways. With pydantic-settings' default list handling, `EMAILS_BCC=audit@example.com,ops@example.com` makes the service crash at startup with a JSON parser trace that names neither the problem nor the value. The setting must accept the spellings people use and turn each one into the same typed value.

Requirements (whether the value comes from the environment variable `EMAILS_BCC` or is passed straight to `Settings(...)`):

1. **Comma-separated string**: `"audit@example.com, ops@example.com"` must give `["audit@example.com", "ops@example.com"]`. Whitespace around each item is ignored. Empty items, such as a trailing comma, are dropped. A single address with no comma gives a one-element list.
2. **JSON array string**: `'["audit@example.com", "ops@example.com"]'` must give the same list.
3. **Empty value**: an empty or whitespace-only string must give `[]`. Leaving the setting unset also gives `[]`.
4. **Canonical form**: passing a real Python list of addresses must keep working and give the same list.
5. **Bad input fails clearly**: constructing `Settings` must raise a `ValueError` (pydantic's `ValidationError` counts) whose message contains the key name `EMAILS_BCC` and the offending value, in these cases:
   - an item is not a valid email address (e.g. `"audit@example.com, not-an-email"` must mention `not-an-email`)
   - the value looks like a JSON array but is malformed (e.g. `'["audit@example.com", '`)
   - a JSON array contains a non-string item (e.g. `'["audit@example.com", 42]'` must mention `42`)
6. Every accepted spelling must produce exactly the same list as the canonical form.
7. Existing settings and the existing test suite must keep working unchanged.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
