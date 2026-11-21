# Reject passwords built from the user's own identity

User accounts are created from the `app.models.UserCreate` schema. This happens when an admin creates a user, when someone signs up (the signup payload is converted into a `UserCreate`), and when the first superuser is bootstrapped. Each field is checked separately. That means `email="marigold@example.com"` and `password="Marigold2024"` both pass, even though together the password is just the address with a few characters added. These accounts get taken over by simple credential-stuffing, and nobody notices until much later.

`UserCreate` must reject this combination when the schema validates it, and the error must name both fields involved.

## Rules

All comparisons ignore case.

1. **Email local part.** The local part is everything before the last `@` of `email`. If it is **3 or more characters** long, `password` must not contain it as a substring. Local parts shorter than 3 characters are not checked.
2. **Full name.** Strip leading and trailing whitespace from `full_name`. If the result is **3 or more characters** long, `password` must not contain it as a substring. A `full_name` that is `None`, or shorter than 3 characters after stripping, is not checked.
3. **Equal-values boundary.** A password that is *equal* to the local part or to the stripped full name (ignoring case) counts as containing it and is **rejected**. A local part or full name of exactly 3 characters is checked; one of 2 characters is not.

## Error behaviour

- A rejected combination makes constructing or validating `UserCreate` raise a pydantic `ValidationError`. This includes `UserCreate.model_validate(...)` on a signup payload.
- The error message must name both fields involved: `password` and `email` for rule 1, `password` and `full_name` for rule 2.
- If both rules are broken at once, a single error must name `password`, `email` **and** `full_name`.

## Unchanged behaviour

- Valid combinations still validate exactly as before. This includes users with no `full_name` and the default `is_active` / `is_superuser` values.
- The existing field-level limits (such as password length 8–128) stay as they are.
- The repository's existing test suite must keep passing.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
