"""go text mutation operators."""

from incidentforge.validate.go_mutants import (
    OPERATORS,
    disable_if,
    drop_error_return,
    drop_statement,
    flip_comparison,
    flip_logical,
    go_mutants,
    negate_if,
)

SRC = """package config

func (c *opts) Validate() error {
\tif c.On() {
\t\tvar missing []string
\t\tif strings.TrimSpace(c.User()) == "" {
\t\t\tmissing = append(missing, "USER")
\t\t}
\t\tif len(missing) > 0 && c.Strict() {
\t\t\treturn fmt.Errorf("need %s", strings.Join(missing, " and "))
\t\t}
\t}
\t// a comment with == inside
\treturn nil
}"""


def test_flip_comparison_skips_strings_comments_and_channels() -> None:
    assert flip_comparison('\tif x == "a<b" {') == '\tif x != "a<b" {'
    assert flip_comparison("\tif n <= max {") == "\tif n > max {"
    assert flip_comparison("\tv := <-ch // x < y") is None
    assert flip_comparison('\ts := "a == b"') is None
    assert flip_comparison("\tx := y << 2") is None


def test_flip_logical() -> None:
    assert flip_logical("\tif a && b {") == "\tif a || b {"
    assert flip_logical("\tif a || b {") == "\tif a && b {"
    assert flip_logical('\ts := "&&"') is None


def test_if_operators() -> None:
    assert negate_if("\tif a > 1 {") == "\tif !(a > 1) {"
    assert negate_if("\t} else if ok {") == "\t} else if !(ok) {"
    assert negate_if("\tif err := f(); err != nil {") is None
    assert negate_if("\tx := 1") is None
    assert disable_if("\tif a > 1 {") == "\tif false {"
    assert disable_if("\t} else if ok {") is None
    assert disable_if("\tif err := f(); err != nil {") is None


def test_drop_error_return_keeps_arity() -> None:
    assert drop_error_return('\t\treturn fmt.Errorf("x %d", 1)') == "\t\treturn nil"
    assert drop_error_return("\treturn nil, err") == "\treturn nil, nil"
    assert drop_error_return('\treturn cfg, errors.New("a, b")') == "\treturn cfg, nil"
    assert drop_error_return("\treturn nil") is None
    assert drop_error_return("\treturn total") is None
    assert drop_error_return("\tx := 1") is None


def test_drop_statement() -> None:
    assert drop_statement('\t\tmissing = append(missing, "X")') == "\t\t// mutant: statement removed"
    assert drop_statement("\tcount++") == "\t// mutant: statement removed"
    assert drop_statement("\tx := f()") is None


def test_go_mutants_only_touch_added_lines() -> None:
    lines = SRC.split("\n")
    added = set(range(4, 13)) | {99}
    mutants = go_mutants(SRC, added)
    names = {m[0] for m in mutants}
    assert names == set(OPERATORS)
    for _name, lineno, text in mutants:
        assert lineno in added
        new_lines = text.split("\n")
        assert len(new_lines) == len(lines)
        assert [i for i, (a, b) in enumerate(zip(lines, new_lines, strict=True)) if a != b] == [lineno - 1]
    assert go_mutants(SRC, {13, 14}) == []
