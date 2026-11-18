"""mutants of a reference patch: mutate only lines the patch adds, then re-diff against the base."""

from __future__ import annotations

import ast
import copy
import difflib
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from incidentforge.models import Target

MAX_MUTANTS = 6
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass
class FilePatch:
    path: str
    added: set[int] = field(default_factory=set)  # 1-based line numbers in the post-image
    new_file: bool = False


@dataclass
class Mutant:
    op: str
    file: str
    line: int
    patch: str


def parse_patch(patch: str) -> list[FilePatch]:
    files: list[FilePatch] = []
    cur: FilePatch | None = None
    new_line = 0
    old_is_null = False
    for line in patch.splitlines():
        if line.startswith("--- "):
            old_is_null = line[4:].strip() == "/dev/null"
        elif line.startswith("+++ "):
            path = line[4:].strip()
            cur = FilePatch(path[2:] if path.startswith("b/") else path, new_file=old_is_null)
            files.append(cur)
        elif (m := _HUNK.match(line)) and cur is not None:
            new_line = int(m.group(1))
        elif cur is not None and line.startswith("+"):
            cur.added.add(new_line)
            new_line += 1
        elif cur is not None and line.startswith(" "):
            new_line += 1
    return files


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def repo_checkout(target: Target) -> Path:
    """cached clone of the target repo; FORGE_REPO_CACHE overrides the location."""
    root = Path(os.environ.get("FORGE_REPO_CACHE", ".cache/repos"))
    d = root / f"{target.name}-{target.commit[:12]}"
    if not (d / ".git").exists():
        root.mkdir(parents=True, exist_ok=True)
        _git("clone", "--quiet", "--no-checkout", target.repo_url, str(d))
    return d


def base_files(target: Target, files: list[FilePatch]) -> dict[str, str]:
    repo = repo_checkout(target)
    return {f.path: "" if f.new_file else _git("show", f"{target.commit}:{f.path}", cwd=repo) for f in files}


def post_image(base: dict[str, str], patch: str) -> dict[str, str]:
    """apply the patch to the base files in a scratch dir and read the results back."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for path, text in base.items():
            if text:
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).write_text(text)
        (root / "ref.patch").write_text(patch)
        _git("apply", "--whitespace=nowarn", "ref.patch", cwd=root)
        return {p: (root / p).read_text() for p in base}


def _col(line: str, byte_off: int) -> int:
    # ast offsets are utf-8 byte offsets
    return len(line.encode()[:byte_off].decode(errors="ignore"))


def _replace(src: str, node: ast.expr | ast.stmt, text: str) -> str:
    lines = src.splitlines(keepends=True)
    sl, el = node.lineno - 1, (node.end_lineno or node.lineno) - 1
    sc, ec = _col(lines[sl], node.col_offset), _col(lines[el], node.end_col_offset or 0)
    return "".join([*lines[:sl], lines[sl][:sc] + text + lines[el][ec:], *lines[el + 1 :]])


def _in_added(node: ast.expr | ast.stmt, added: set[int]) -> bool:
    return all(n in added for n in range(node.lineno, (node.end_lineno or node.lineno) + 1))


_FLIP: dict[type[ast.cmpop], type[ast.cmpop]] = {
    ast.Lt: ast.LtE,
    ast.LtE: ast.Lt,
    ast.Gt: ast.GtE,
    ast.GtE: ast.Gt,
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.In: ast.NotIn,
    ast.NotIn: ast.In,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
}


def _return_early(src: str, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    last = fn.body[-1]
    if not isinstance(last, ast.Return) or last.value is None:
        return None
    args = {a.arg for a in fn.args.args}
    if not (isinstance(last.value, ast.Constant) or (isinstance(last.value, ast.Name) and last.value.id in args)):
        return None
    first = fn.body[0]
    lines = src.splitlines(keepends=True)
    indent = lines[first.lineno - 1][: _col(lines[first.lineno - 1], first.col_offset)]
    if indent.strip():
        return None
    ret = f"{indent}return {ast.unparse(last.value)}\n"
    return "".join([*lines[: first.lineno - 1], ret, *lines[first.lineno - 1 :]])


def python_mutants(src: str, added: set[int]) -> list[tuple[str, int, str]]:
    """(operator, line, mutated source) for every applicable ast operator on added code."""
    out: list[tuple[str, int, str]] = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.If) and _in_added(node.test, added):
            seg = ast.get_source_segment(src, node.test)
            out.append(("negate_if", node.lineno, _replace(src, node.test, f"not ({seg})")))
        elif isinstance(node, ast.Raise) and _in_added(node, added):
            out.append(("drop_raise", node.lineno, _replace(src, node, "pass")))
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and _in_added(node, added):
            out.append(("drop_call", node.lineno, _replace(src, node, "pass")))
        elif isinstance(node, ast.Compare) and type(node.ops[0]) in _FLIP and _in_added(node, added):
            flipped = copy.deepcopy(node)
            flipped.ops[0] = _FLIP[type(node.ops[0])]()
            out.append(("flip_compare", node.lineno, _replace(src, node, ast.unparse(flipped))))
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.lineno in added:
            mutated = _return_early(src, node)
            if mutated:
                out.append(("return_early", node.lineno, mutated))
    return out


_CMP = re.compile(r"(?<![<>=!:])(<=|>=|==|!=)(?![=>])|(?<=\s)(<|>)(?=\s)")
_IF = re.compile(r"^(\s*)if ([^;{]+) \{\s*$")
_CMP_SWAP = {"<=": "<", ">=": ">", "==": "!=", "!=": "==", "<": "<=", ">": ">="}


def line_mutants(src: str, added: set[int]) -> list[tuple[str, int, str]]:
    """text-level fallback for languages without a python ast: flip one comparison, negate an if."""
    lines = src.splitlines(keepends=True)
    out: list[tuple[str, int, str]] = []
    for n in sorted(added):
        line = lines[n - 1] if n <= len(lines) else ""
        if (m := _IF.match(line.rstrip("\n"))) is not None:
            new = f"{m.group(1)}if !({m.group(2)}) {{\n"
            out.append(("negate_if", n, "".join([*lines[: n - 1], new, *lines[n:]])))
        cmps = list(_CMP.finditer(line))
        if len(cmps) == 1:
            op = cmps[0].group(0)
            new = line[: cmps[0].start()] + _CMP_SWAP[op] + line[cmps[0].end() :]
            out.append(("flip_compare", n, "".join([*lines[: n - 1], new, *lines[n:]])))
    return out


def _diff(path: str, before: str, after: str, new_file: bool) -> str:
    if before == after:
        return ""
    old = "/dev/null" if new_file else f"a/{path}"
    head = f"diff --git a/{path} b/{path}\n" + ("new file mode 100644\n" if new_file else "")
    body = ""
    for line in difflib.unified_diff(before.splitlines(True), after.splitlines(True), old, f"b/{path}"):
        body += line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
    return head + body


def make_mutants(patch: str, base: dict[str, str], max_n: int = MAX_MUTANTS) -> list[Mutant]:
    """mutants that still parse, picked round-robin across operators so each kind is tried."""
    files = parse_patch(patch)
    post = post_image(base, patch)
    by_op: dict[str, list[Mutant]] = {}
    for f in files:
        src = post[f.path]
        if f.path.endswith(".py"):
            try:
                cands = python_mutants(src, f.added)
            except SyntaxError:
                cands = line_mutants(src, f.added)
        else:
            cands = _other_mutants(f.path, src, f.added)
        for op, line, mutated in cands:
            if mutated == src or (f.path.endswith(".py") and not _parses(mutated)):
                continue
            text = "".join(
                _diff(g.path, base[g.path], mutated if g.path == f.path else post[g.path], g.new_file) for g in files
            )
            by_op.setdefault(op, []).append(Mutant(op, f.path, line, text))
    picked: list[Mutant] = []
    queues = [list(v) for v in by_op.values()]
    while len(picked) < max_n and any(queues):
        for q in queues:
            if q and len(picked) < max_n:
                picked.append(q.pop(0))
    return picked


def _other_mutants(path: str, src: str, added: set[int]) -> list[tuple[str, int, str]]:
    # go operators live in go_mutants (owned by phase 3) once it lands
    if path.endswith(".go"):
        try:
            from incidentforge.validate import go_mutants  # type: ignore[attr-defined, unused-ignore]
        except ImportError:
            pass
        else:
            result: list[tuple[str, int, str]] = go_mutants.go_mutants(src, added)
            return result
    return line_mutants(src, added)


def _parses(src: str) -> bool:
    try:
        ast.parse(src)
    except SyntaxError:
        return False
    return True
