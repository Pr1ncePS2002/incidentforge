## Reject impossible numeric ranges when the range type is created

Right now `click.IntRange` and `click.FloatRange` (both built on `click.types._NumberRangeBase`) accept any combination of `min`, `max`, `min_open` and `max_open`. That includes ranges that no value can ever satisfy, such as `click.IntRange(10, 1)` or `click.FloatRange(1.0, 1.0, max_open=True)`. The mistake only shows up later, when a user passes a value on the command line and it is rejected, even though no value would ever have been accepted.

Add a check to the range constructor (shared by `IntRange` and `FloatRange`) so that impossible ranges are rejected when the type is created. Because `@click.option(..., type=click.IntRange(...))` builds the type when the command is declared, the error appears at decorator time.

### Rules (checked only when both `min` and `max` are given, not `None`)

1. **Inverted range:** if `min > max`, raise `ValueError`. The message must contain the words `min` and `max` and both values formatted with `str()`. For example, `click.IntRange(10, 1)` gives a message containing `min`, `max`, `10` and `1`. Mixing ints and floats follows normal Python comparison: `click.FloatRange(1, 0.5)` is rejected.
2. **Equal bounds (boundary rule):** `min == max` is **allowed** when both bounds are closed (`min_open=False` and `max_open=False`). This makes a one-value range: `click.IntRange(3, 3)` accepts only `3`, and with `clamp=True` it clamps every value to `3`.
3. **Equal bounds with an open side:** if `min == max` and either `min_open` or `max_open` is `True`, the range is empty. Raise `ValueError` with a message that contains `min` and `max`.

### Unchanged behaviour

- Ranges with only one bound, or with no bounds (`click.IntRange(min=5)`, `click.FloatRange(max=1.0)`, `click.IntRange()`), do not change.
- Valid ranges keep their current conversion, clamping, error and help-text behaviour. Examples: `click.IntRange(0, 5)`, `click.FloatRange(0, 1, min_open=True)`, `click.IntRange(0, 10, clamp=True)`.
- The existing `TypeError` that `FloatRange` raises for clamping with open bounds does not change.
- No new public names are added. The behaviour is used through `click.IntRange` / `click.FloatRange`, which are also importable from `click.types`.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
