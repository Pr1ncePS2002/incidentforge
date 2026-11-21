"""exact outputs of the patch parser, mutant operators, leak gate and ci reward check; kills mutmut survivors."""

import json
import subprocess
from pathlib import Path

import pytest

from incidentforge import ci_checks
from incidentforge.models import Language, Target
from incidentforge.validate import go_mutants as go
from incidentforge.validate import leak, mutation

# parse_patch


def test_parse_patch_counts_only_post_image_lines() -> None:
    patch = mutation._diff("f.txt", "a\nb\nc\n", "a\nB\nc\n", False)
    [f] = mutation.parse_patch(patch)
    assert (f.path, f.added, f.new_file) == ("f.txt", {2}, False)


def test_parse_patch_on_loose_input() -> None:
    # junk before any file header is ignored, a bare path keeps its name, a missing --- means not new
    assert mutation.parse_patch("+stray\n@@ -1 +1 @@\n") == []
    [f] = mutation.parse_patch("+++ pkg/a.py\n@@ -0,0 +3 @@\n+x\n")
    assert (f.path, f.added, f.new_file) == ("pkg/a.py", {3}, False)
    [g] = mutation.parse_patch("--- a/x\n+++ b/x\n+a\n+b\n")
    assert g.added == {0, 1} and g.new_file is False


# git helpers


def test_git_raises_on_failure(tmp_path: Path) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        mutation._git("definitely-not-a-git-command", cwd=tmp_path)


def _target(name: str, commit: str = "0123456789abcdef0123") -> Target:
    return Target(
        name=name,
        repo_url="https://x/r",
        commit=commit,
        language=Language.python,
        env_template=Path(),
        test_command="t",
    )


def test_repo_checkout_default_location_and_clone_args(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(mutation, "_git", lambda *a, cwd=None: calls.append(a) or "")
    monkeypatch.delenv("FORGE_REPO_CACHE", raising=False)
    monkeypatch.chdir(tmp_path)
    d = mutation.repo_checkout(_target("demo"))
    assert d == Path(".cache/repos/demo-0123456789ab")
    assert calls == [("clone", "--quiet", "--no-checkout", "https://x/r", str(d))]


def test_repo_checkout_makes_nested_root_and_reuses_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mutation, "_git", lambda *a, cwd=None: "")
    monkeypatch.setenv("FORGE_REPO_CACHE", str(tmp_path / "a" / "b"))
    assert mutation.repo_checkout(_target("one")) == tmp_path / "a" / "b" / "one-0123456789ab"
    assert mutation.repo_checkout(_target("two")) == tmp_path / "a" / "b" / "two-0123456789ab"


def test_post_image_creates_nested_dirs() -> None:
    patch = mutation._diff("a/b/c.py", "x = 1\n", "x = 2\n", False)
    assert mutation.post_image({"a/b/c.py": "x = 1\n"}, patch) == {"a/b/c.py": "x = 2\n"}


def test_diff_of_identical_text_is_empty() -> None:
    assert mutation._diff("a", "x\n", "x\n", False) == ""


# python operators

RAISE_SRC = "def f(a):\n    if a:\n        raise ValueError(\n            'bad'\n        )\n    return a\n\nz = 0\n"


def test_multi_line_raise_is_replaced_whole() -> None:
    muts = {op: src for op, _, src in mutation.python_mutants(RAISE_SRC, set(range(1, 9)))}
    assert muts["drop_raise"] == "def f(a):\n    if a:\n        pass\n    return a\n\nz = 0\n"
    assert muts["negate_if"] == RAISE_SRC.replace("if a:", "if not (a):")
    assert muts["return_early"] == "def f(a):\n    return a\n" + RAISE_SRC[len("def f(a):\n") :]


def test_partly_added_node_is_not_mutated() -> None:
    ops = [op for op, _, _ in mutation.python_mutants(RAISE_SRC, {3})]
    assert "drop_raise" not in ops
    # a node whose last line is the last added line still counts
    assert "drop_raise" in [op for op, _, _ in mutation.python_mutants(RAISE_SRC, {3, 4, 5})]


def test_return_early_inserts_before_the_first_statement() -> None:
    src = "def f(a):\n    x = 1\n    return a\n\nz = 0\n"
    [(op, line, out)] = [m for m in mutation.python_mutants(src, {1, 2, 3}) if m[0] == "return_early"]
    assert (op, line, out) == ("return_early", 1, "def f(a):\n    return a\n    x = 1\n    return a\n\nz = 0\n")


@pytest.mark.parametrize(
    "src",
    [
        "def f(a):\n    x = 1\n    pass\n",
        "def f(a):\n    x = 1\n    return g(a)\n",
        "def f(a):\n    x = 1\n    return x\n",
        "def f(a):\n    x = 1\n    return\n",
    ],
)
def test_return_early_only_for_constant_or_argument_returns(src: str) -> None:
    assert "return_early" not in [op for op, _, _ in mutation.python_mutants(src, {1, 2, 3})]


def test_drop_call_and_flip_compare_text() -> None:
    src = "def f(a):\n    log(a)\n    return a < 1\n"
    muts = {op: s for op, _, s in mutation.python_mutants(src, {2, 3})}
    assert muts["drop_call"] == "def f(a):\n    pass\n    return a < 1\n"
    assert muts["flip_compare"] == "def f(a):\n    log(a)\n    return a <= 1\n"
    # the source tree is untouched by the flip
    assert mutation.python_mutants(src, {3}) == mutation.python_mutants(src, {3})


# line operators

GO_SRC = "if a == b {\n\tx := 1\n\tif n < 3 {\n\treturn f(a)\n}"


def test_line_mutants_exact() -> None:
    assert mutation.line_mutants(GO_SRC, {1, 3, 5, 99}) == [
        ("negate_if", 1, "if !(a == b) {\n" + GO_SRC.split("\n", 1)[1]),
        ("flip_compare", 1, "if a != b {\n" + GO_SRC.split("\n", 1)[1]),
        ("negate_if", 3, "if a == b {\n\tx := 1\n\tif !(n < 3) {\n\treturn f(a)\n}"),
        ("flip_compare", 3, "if a == b {\n\tx := 1\n\tif n <= 3 {\n\treturn f(a)\n}"),
    ]


def test_line_mutants_on_the_last_line_without_newline() -> None:
    assert mutation.line_mutants("x\ny >= 1", {2}) == [("flip_compare", 2, "x\ny > 1")]


def test_line_mutants_need_the_brace_at_line_end() -> None:
    assert mutation.line_mutants("if a {X\n", {1}) == []


# make_mutants


def test_unparsable_python_yields_no_mutants() -> None:
    before = "x = 1\n"
    after = "x = 1\nif a <= b {\n"
    assert mutation.make_mutants(mutation._diff("m.py", before, after, False), {"m.py": before}) == []


def test_multi_file_mutant_patch_is_exact() -> None:
    a0, a1 = "x = 1\n", "x = 1\nif x > 0:\n    y = 2\n"
    b1 = "def g(v):\n    return v\n"
    patch = mutation._diff("a.py", a0, a1, False) + mutation._diff("b.py", "", b1, True)
    ms = mutation.make_mutants(patch, {"a.py": a0, "b.py": ""}, max_n=10)
    first = next(m for m in ms if m.file == "a.py" and m.op == "negate_if")
    assert first.line == 2
    expected = mutation._diff("a.py", a0, a1.replace("if x > 0:", "if not (x > 0):"), False) + mutation._diff(
        "b.py", "", b1, True
    )
    assert first.patch == expected
    assert "new file mode 100644" in first.patch


def test_make_mutants_respects_max_n() -> None:
    before = "class S:\n    port: int = 1\n"
    after = before + (
        "\n    def check(self, value):\n        problems = []\n        if self.port < 1:\n"
        "            problems.append('P')\n        if problems:\n            raise ValueError(problems)\n"
        "        return value\n"
    )
    assert len(mutation.make_mutants(mutation._diff("c.py", before, after, False), {"c.py": before}, max_n=2)) == 2


def test_other_mutants_dispatch() -> None:
    src = "if a == b {\n"
    assert mutation._other_mutants("x.go", src, {1})[0][0] == "flip-comparison"
    assert mutation._other_mutants("x.js", src, {1}) == mutation.line_mutants(src, {1}) != []


# go operators


def test_code_spans_skip_literals_and_comments() -> None:
    assert list(go._code_spans('"a" == b')) == [(0, 0), (3, 8)]
    assert list(go._code_spans("x == 1 // y")) == [(0, 7)]


@pytest.mark.parametrize(
    ("line", "flipped"),
    [
        ('"<" < x', '"<" >= x'),
        ("a / b == c", "a / b != c"),
        ("x == 1 // y == 2", "x != 1 // y == 2"),
        ("X == 1", "X != 1"),
        ('"" == a', '"" != a'),
        ('"abc" == d', '"abc" != d'),
        ('"a\\"b" == c', '"a\\"b" != c'),
        ("`a\\` == b", "`a\\` != b"),
        ('a == 1 "abc', 'a != 1 "abc'),
        ('"a" + "<" == b', '"a" + "<" != b'),
    ],
)
def test_flip_comparison_respects_literals(line: str, flipped: str) -> None:
    assert go.flip_comparison(line) == flipped


def test_unterminated_literal_hides_the_rest() -> None:
    assert go.flip_comparison('"abc == d') is None


def test_split_top_exact() -> None:
    exprs = "a, \"x,y\", f(g(b, c), d), [1,2], {k: v}, 'q', X, err"
    assert go._split_top(exprs) == ["a", '"x,y"', "f(g(b, c), d)", "[1,2]", "{k: v}", "'q'", "X", "err"]
    assert go._split_top('"a", b') == ['"a"', "b"]


def test_flip_logical_first_occurrence() -> None:
    assert go.flip_logical("a && b && c") == "a || b && c"
    assert go.flip_logical("&& b") == "|| b"


def test_go_mutants_line_bounds() -> None:
    src = "if a == b {\n\tx++\n}\nreturn x, err"
    lines = {line for _, line, _ in go.go_mutants(src, {0, 1, 4, 9})}
    assert lines == {1, 4}
    [m] = [m for m in go.go_mutants(src, {2}) if m[0] == "drop-statement"]
    assert m == ("drop-statement", 2, "if a == b {\n\t// mutant: statement removed\n}\nreturn x, err")


# leak


def test_added_lines_exact() -> None:
    patch = "--- a/x\n+++ b/x\n@@ -1,2 +1,2 @@\n ctx\n-old\n+new line\n++plus\n"
    assert leak.added_lines(patch) == ["new line", "+plus"]


def test_ngrams_and_squash_exact() -> None:
    assert leak._ngrams("a b c d e f g h i") == {
        ("a", "b", "c", "d", "e", "f", "g", "h"),
        ("b", "c", "d", "e", "f", "g", "h", "i"),
    }
    assert leak._ngrams("a b c d e f g") == set()
    assert leak._squash(" a \n\t b ") == "a b"


def _p(*lines: str) -> str:
    return "+++ b/x\n@@ -0,0 +1 @@\n" + "".join(f"+{x}\n" for x in lines)


def test_line_check_boundary_and_detail() -> None:
    line25 = "abcdefghijklmnopqrstuvwxy"
    assert leak.check_leak(f"use {line25} here", _p(line25)) == (
        False,
        f"instruction contains patch line: {line25!r}",
    )
    long = "z" * 100
    assert leak.check_leak(long, _p(long)) == (False, f"instruction contains patch line: {'z' * 80!r}")


def test_ngram_share_boundary_and_details() -> None:
    line = "a+b+c+d+e+f+g+h+i"  # 17 tokens, 10 grams, under 25 chars
    assert leak.check_leak("a+b+c+d+e+", _p(line)) == (False, "30% of patch 8-grams appear in the instruction")
    assert leak.check_leak("a+b+c+d+e", _p(line)) == (True, "20% 8-gram overlap")
    two = ["a+b+c+d+e+f+g+h+i", "j+k+l+m+n+o+p+q+r"]
    assert leak.check_leak("\n".join(two), _p(*two)) == (False, "100% of patch 8-grams appear in the instruction")


# ci reward check


def test_trial_name_comes_from_result_json(tmp_path: Path) -> None:
    d = tmp_path / "dir-name"
    d.mkdir()
    (d / "result.json").write_text(json.dumps({"trial_name": "real", "verifier_result": {"rewards": {"reward": 1.0}}}))
    assert ci_checks.trial_rewards(tmp_path) == {"real": 1.0}


def test_main_prints_errors_and_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for name, r in (("a", 1.0), ("b", 0.0)):
        (tmp_path / name).mkdir()
        (tmp_path / name / "result.json").write_text(
            json.dumps({"trial_name": name, "verifier_result": {"rewards": {"reward": r}}})
        )
    assert ci_checks.main([str(tmp_path), "1.0"]) == 1
    assert capsys.readouterr().out == "::error::b: reward 0.0, expected 1.0\n1 trial(s) ok, 1 problem(s)\n"


def test_escape_skips_exactly_one_char() -> None:
    assert go.flip_comparison('"\\n" == c') == '"\\n" != c'


def test_return_early_indent_uses_the_statement_line() -> None:
    src = "class C:\n    def f(self, a):\n    # \u00e9\u00e9\n        x = 1\n        return a\n"
    [out] = [s for op, _, s in mutation.python_mutants(src, {2, 3, 4, 5}) if op == "return_early"]
    assert (
        out == "class C:\n    def f(self, a):\n    # \u00e9\u00e9\n        return a\n        x = 1\n        return a\n"
    )
