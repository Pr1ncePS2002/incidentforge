"""property-based checks for the schema checker, the leak gate and the spend math."""

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from incidentforge.backends.base import GeminiJsonBackend, MalformedOutput, check_schema
from incidentforge.budget import CACHED_INPUT_FRACTION, PRICES, BudgetExhausted, Ledger, cost_usd
from incidentforge.validate.leak import NGRAM, _ngrams, check_leak

# bounded so the unit job stays fast; no deadline because ci runners are noisy
PROPS = settings(max_examples=200, deadline=None)

SCALAR_KINDS = ["string", "integer", "number", "boolean", "object", "array"]
json_scalars = st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(max_size=8)
json_values = st.recursive(
    json_scalars,
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=5), inner, max_size=3),
    max_leaves=10,
)


def value_of(kind: str) -> st.SearchStrategy[Any]:
    return {
        "string": st.text(max_size=10),
        "integer": st.integers(),
        "number": st.integers() | st.floats(allow_nan=False),
        "boolean": st.booleans(),
        # the checker is shallow: anything may sit inside a nested object or array
        "object": st.dictionaries(st.text(max_size=5), json_values, max_size=3),
        "array": st.lists(json_values, max_size=3),
    }[kind]


def fits(value: Any, kind: str) -> bool:
    """json-schema type semantics, written independently of the checker."""
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return type(value) is int
    if kind == "number":
        return type(value) in (int, float)
    if kind == "boolean":
        return type(value) is bool
    if kind == "object":
        return isinstance(value, dict)
    return isinstance(value, list)


keys = st.text(alphabet="abcdefgh", min_size=1, max_size=4)
schemas = st.dictionaries(keys, st.sampled_from(SCALAR_KINDS), min_size=1, max_size=5)


@st.composite
def schema_and_valid_obj(draw: st.DrawFn) -> tuple[dict[str, Any], dict[str, Any]]:
    kinds = draw(schemas)
    required = draw(st.lists(st.sampled_from(sorted(kinds)), unique=True))
    present = set(required) | draw(st.sets(st.sampled_from(sorted(kinds))))
    obj = {k: draw(value_of(kinds[k])) for k in present}
    obj.update(draw(st.dictionaries(st.text(alphabet="xyz", min_size=1), json_values, max_size=2)))
    schema = {"type": "object", "required": required, "properties": {k: {"type": t} for k, t in kinds.items()}}
    return schema, obj


@PROPS
@given(schema_and_valid_obj())
def test_valid_objects_pass_and_round_trip_through_generate_json(case: tuple[dict[str, Any], dict[str, Any]]) -> None:
    schema, obj = case
    check_schema(obj, schema)

    class Fake:
        def generate(self, model: str, prompt: str, **_: Any) -> SimpleNamespace:
            return SimpleNamespace(text=f"here you go:\n```json\n{json.dumps(obj)}\n```")

    assert GeminiJsonBackend(Fake(), model="m").generate_json("p", schema) == json.loads(json.dumps(obj))


@PROPS
@given(schema_and_valid_obj(), st.data())
def test_dropping_a_required_key_is_rejected(case: tuple[dict[str, Any], dict[str, Any]], data: st.DataObject) -> None:
    schema, obj = case
    assume(schema["required"])
    gone = data.draw(st.sampled_from(schema["required"]))
    with pytest.raises(MalformedOutput, match="missing keys"):
        check_schema({k: v for k, v in obj.items() if k != gone}, schema)


@PROPS
@given(st.sampled_from(SCALAR_KINDS), json_values)
def test_checker_agrees_with_json_schema_type_rules(kind: str, value: Any) -> None:
    schema = {"required": ["k"], "properties": {"k": {"type": kind}}}
    if fits(value, kind):
        check_schema({"k": value}, schema)
    else:
        with pytest.raises(MalformedOutput, match="should be"):
            check_schema({"k": value}, schema)


@PROPS
@given(st.booleans(), st.sampled_from(["integer", "number"]))
def test_bool_is_never_a_number(value: bool, kind: str) -> None:
    with pytest.raises(MalformedOutput):
        check_schema({"k": value}, {"properties": {"k": {"type": kind}}})


@PROPS
@given(st.lists(st.sampled_from([*SCALAR_KINDS, "null"]), min_size=1, unique=True), json_values)
def test_union_type_lists_never_raise(kinds: list[str], value: Any) -> None:
    # unions are left to the caller's pydantic model
    check_schema({"k": value}, {"properties": {"k": {"type": kinds}}})


@PROPS
@given(st.text(max_size=8) | st.none() | st.integers(), json_values)
def test_unknown_or_missing_type_is_ignored(kind: Any, value: Any) -> None:
    assume(kind not in SCALAR_KINDS)
    check_schema({"k": value}, {"properties": {"k": {"type": kind}, "n": "not-a-dict"}})


# leak gate: disjoint alphabets guarantee no shared token between instruction and patch
words_a = st.text(alphabet="abcdefghijklm", min_size=1, max_size=8)
words_b = st.text(alphabet="nopqrstuvwxyz", min_size=1, max_size=8)


def prose(words: st.SearchStrategy[str], lo: int = 1) -> st.SearchStrategy[str]:
    return st.lists(words, min_size=lo, max_size=40).map(" ".join)


def patch_of(lines: list[str]) -> str:
    return "--- a/x.py\n+++ b/x.py\n@@ -0,0 +1 @@\n" + "".join(f"+{line}\n" for line in lines)


@PROPS
@given(st.lists(prose(words_a, lo=NGRAM), min_size=1, max_size=4))
def test_instruction_that_repeats_the_patch_leaks(lines: list[str]) -> None:
    passed, _ = check_leak("\n".join(lines), patch_of(lines))
    assert not passed


@PROPS
@given(prose(words_a), st.lists(prose(words_b), min_size=1, max_size=4))
def test_disjoint_text_never_leaks(instruction: str, lines: list[str]) -> None:
    passed, _ = check_leak(instruction, patch_of(lines))
    assert passed


@PROPS
@given(prose(words_a | words_b), st.lists(prose(words_a | words_b), min_size=1, max_size=4), prose(words_a | words_b))
def test_more_shared_content_never_turns_a_leak_into_a_pass(instr: str, lines: list[str], extra: str) -> None:
    patch = patch_of(lines)
    before, _ = check_leak(instr, patch)
    after, _ = check_leak(f"{instr} {extra}", patch)
    copied, _ = check_leak(f"{instr}\n{lines[0]}", patch)
    assert before or not after
    assert copied <= before


@PROPS
@given(prose(words_a | words_b), st.lists(prose(words_a | words_b), min_size=1, max_size=4), st.data())
def test_verdict_ignores_instruction_line_wrapping(instr: str, lines: list[str], data: st.DataObject) -> None:
    rewrapped = "".join(c if c != " " else data.draw(st.sampled_from([" ", "\n", "  \t"])) for c in instr)
    assert check_leak(instr, patch_of(lines))[0] == check_leak(rewrapped, patch_of(lines))[0]


@PROPS
@given(prose(words_a | words_b), prose(words_a | words_b))
def test_ngram_overlap_is_symmetric(a: str, b: str) -> None:
    assert len(_ngrams(a) & _ngrams(b)) == len(_ngrams(b) & _ngrams(a))
    assert _ngrams(a) <= _ngrams(f"{a} {b}") and _ngrams(b) <= _ngrams(f"{a} {b}")


# spend math
models = st.sampled_from([*PRICES, "gemini-9-unknown", "models/gemini-3.8-flash"])
toks = st.integers(min_value=0, max_value=10**9)


@PROPS
@given(models, toks, toks, st.integers(min_value=-(10**9), max_value=2 * 10**9))
def test_cost_is_non_negative_and_cached_is_clamped(model: str, i: int, o: int, cached: int) -> None:
    c = cost_usd(model, i, o, cached)
    assert c >= 0
    assert c == pytest.approx(cost_usd(model, i, o, min(max(cached, 0), i)))
    assert c <= cost_usd(model, i, o) + 1e-12
    assert c >= cost_usd(model, i, o, i) - 1e-12


@PROPS
@given(models, toks, toks, toks, toks, toks)
def test_cost_is_monotonic_in_tokens(model: str, i: int, o: int, di: int, do: int, cached: int) -> None:
    base = cost_usd(model, i, o, min(cached, i))
    assert cost_usd(model, i + di, o, min(cached, i)) >= base - 1e-12
    assert cost_usd(model, i, o + do, min(cached, i)) >= base - 1e-12


@PROPS
@given(models, toks)
def test_fully_cached_input_costs_the_cached_fraction(model: str, i: int) -> None:
    assert cost_usd(model, i, 0, i) == pytest.approx(cost_usd(model, i, 0) * CACHED_INPUT_FRACTION)


ops = st.lists(
    st.tuples(st.sampled_from(["record", "release", "crash"]), st.integers(0, 20_000), st.integers(0, 20_000)),
    max_size=25,
)


@PROPS
@given(ops, st.floats(min_value=0.05, max_value=2.0))
def test_ledger_spend_plus_holds_never_pass_the_cap(steps: list[tuple[str, int, int]], cap: float) -> None:
    with tempfile.TemporaryDirectory() as d:
        led = Ledger(Path(d) / "l.jsonl", cap=cap)
        for how, worst_out, real_out in steps:
            try:
                rid = led.reserve("gemini-4-argon", 0, worst_out)
            except BudgetExhausted:
                continue
            if how == "record":
                # the real bill never exceeds the reserved worst case
                led.record("gemini-4-argon", 0, min(real_out, worst_out), reservation=rid)
            elif how == "release":
                led.release(rid)
            # "crash" leaves the hold open: this process is alive, so it keeps counting
            assert led.spent() + led.reserved() <= cap + 1e-9
