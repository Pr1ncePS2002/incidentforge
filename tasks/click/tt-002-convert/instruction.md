## Accept comma digit grouping in number parameter types

People often type large numbers the way they read them, for example `--limit 1,000,000`, `--budget 1,234.50` or `MAX_ROWS=10,000` in an environment variable. Today click's number types (`click.INT`, `click.FLOAT`, `click.IntRange`, `click.FloatRange`) reject these values with `'1,000' is not a valid integer.` Add support for this spelling to the shared number conversion in `click.types` (`_NumberParamTypeBase.convert`). Every number type and range type that builds on it should accept it.

### Accepted spelling

A string value may use commas as thousands separators in its integer part:

- An optional leading `+` or `-` sign, then a first group of 1 to 3 ASCII digits, then one or more groups of exactly 3 ASCII digits, each group preceded by one comma. Surrounding whitespace is ignored, as it is today.
- For float types, a fractional part may follow (`.` and digits, plus an optional exponent as Python's `float` allows). The fractional part must not contain commas.
- The value is the same as the spelling with the commas removed: `1,000` -> `1000` (INT) or `1000.0` (FLOAT), `-12,345,678` -> `-12345678`, `1,234.5` -> `1234.5`.
- This works the same for command-line values and environment-variable values, including `multiple=True` options whose environment value is split on whitespace (`"1,000 2,000"` -> `(1000, 2000)`).
- Range types apply their bounds and clamping to the converted number. With `IntRange(0, 100)`, `1,000` is rejected as out of range. With `IntRange(0, 1000, clamp=True)`, `5,000` becomes `1000`.

### Unchanged behaviour

Canonical spellings must keep producing the same values as before: `42`, ` 7 `, `-3`, `1_000`, `2.5`, `1e3` for floats, and so on.

### Rejected input

Values with malformed grouping must still fail through the existing error path: a `click.BadParameter` that click reports as a usage error, exit code 2. The message must name the option (for example `'--count'`) and quote the offending value exactly as the user wrote it, in the existing form `Invalid value for '--count': '1,00' is not a valid integer.` Rejected examples:

- `1,00` and `1,0000`: a group after the first does not have exactly 3 digits
- `1234,567`: the first group has more than 3 digits
- `,100`, `100,` and `1,,000`: empty groups
- `1,0a0`: non-digit characters
- `1,000.5` for an integer type
- `1,000.0,5`: a comma in the fractional part

No new public names are added.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
