# Reject category title length limits that no title can satisfy

Category creation (`internal/validator/category.go`, `ValidateCategoryCreation`) only checks that a title is not empty and not already in use. We want to add a configurable length policy for category titles. A policy has a lower and an upper bound. Each bound can look fine by itself while the pair is impossible, for example a minimum of 50 with a maximum of 20. If nothing checks the pair, it is accepted and every later category creation fails without a clear reason. The policy must be checked as a whole, and the error must name the fields involved.

Add the following to package `internal/validator` (import path `miniflux.app/v2/internal/validator`):

1. An exported struct `CategoryTitleLimits` with two exported `int` fields, `MinLength` and `MaxLength`. Lengths count characters (Unicode code points), not bytes. Both bounds are inclusive.
2. An exported package-level variable `DefaultCategoryTitleLimits` of type `CategoryTitleLimits`, with `MinLength` 1 and `MaxLength` 255. This default must pass validation.
3. A method `func (l CategoryTitleLimits) Validate() error` that returns:
   - an error naming `MinLength` when `MinLength` is zero or negative. This error must not mention `MaxLength`.
   - an error naming `MaxLength` when `MaxLength` is zero or negative.
   - an error naming **both** `MinLength` and `MaxLength` when `MinLength` is greater than `MaxLength`.
   - `nil` otherwise.

   **Boundary rule:** `MinLength == MaxLength` is allowed. It means titles of exactly that length.
4. A method `func (l CategoryTitleLimits) CheckTitle(title string) error` that:
   - first validates the limits and returns the `Validate()` error unchanged if they are invalid.
   - returns an error naming `MinLength` if the title has fewer characters than `MinLength`.
   - returns an error naming `MaxLength` if the title has more characters than `MaxLength`.
   - returns `nil` otherwise. A title whose length equals either bound is accepted.

The field names `MinLength` and `MaxLength` must appear literally in the error messages. The existing behaviour of `ValidateCategoryCreation` / `ValidateCategoryModification` stays the same, and the existing test suite must still pass.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
