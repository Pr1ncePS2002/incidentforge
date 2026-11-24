"""ast scan of a python repo for code surfaces a family can attach a task to. owner: phase 2."""

from __future__ import annotations

import ast
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import TypeGuard

from incidentforge.models import Surface

MAX_EXCERPT = 40
# converter and constructor checks need the whole method in view, so library surfaces get a wider cap
WIDE_EXCERPT = 90
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "tests",
    "test",
    "migrations",
    "versions",
    "docs",
    "examples",
}
SETTINGS_BASES = {"BaseSettings"}
MODEL_BASES = {"BaseModel", "SQLModel"}
VALIDATOR_DECOS = {"field_validator", "model_validator", "validator", "root_validator"}
WRITE_METHODS = {"post", "put", "patch", "delete"}
TASK_DECOS = {"task", "shared_task", "actor", "consumer", "subscriber", "handler"}
CONSUMER_NAME = re.compile(r"^(handle|on|process|consume|apply)_|_(handler|consumer|webhook)$|webhook")
CRUD_NAME = re.compile(r"^(create|update|upsert|register|apply)_")
CACHE_KEY_NAME = re.compile(r"(cache|redis).*key|key.*(cache|redis)", re.IGNORECASE)
POOL_FIELD = re.compile(r"POOL|TIMEOUT|WORKERS|CONCURRENCY|RETRIES|RETRY|EXPIRE|TTL|_MAX|MAX_|_MIN|MIN_|_SIZE|_LIMIT")
POOL_KWARGS = {"pool_size", "max_overflow", "pool_timeout", "pool_recycle", "timeout", "workers", "max_connections"}
OUTPUT_MODEL = re.compile(r"(Public|Response|Out|Message|Token)$")
POOL_FACTORIES = {"create_engine", "create_async_engine", "ConnectionPool", "ThreadPoolExecutor", "create_pool"}
DUMP_CALLS = {"dump", "safe_dump", "dumps", "write_text"}
# a name-matched handler must take something that looks like a delivered message, not ctx/value/opts
MESSAGE_PARAM = re.compile(r"(?i)event|msg|message|payload|body|record|job|task|delivery|envelope|webhook|notification")
CONVERT_METHODS = {"convert", "coerce", "to_python", "parse_value", "clean"}
CHECK_METHOD = re.compile(r"^_*(validate|check)")
CHECK_ERRORS = {"ValueError", "TypeError", "BadParameter", "UsageError", "ValidationError"}
RESOURCE_PROBES = {"get_terminal_size", "cpu_count", "sched_getaffinity", "process_cpu_count", "sysconf", "getrlimit"}


def _name(node: ast.expr) -> str:
    """last dotted component of a name, attribute or call target."""
    if isinstance(node, ast.Call):
        return _name(node.func)
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _excerpt(lines: list[str], start: int, end: int) -> str:
    """1-based inclusive line range, capped so the prompt stays small."""
    return "\n".join(lines[start - 1 : min(end, start + MAX_EXCERPT - 1)])


def _class_outline(cls: ast.ClassDef, lines: list[str], focus: int | None = None) -> str:
    """header, field lines and method signatures; a focus line is kept in view when the outline is cut."""
    end = cls.end_lineno or cls.lineno
    if end - cls.lineno < MAX_EXCERPT:
        return _excerpt(lines, cls.lineno, end)
    keep = [cls.lineno]
    for node in cls.body:
        if isinstance(node, ast.AnnAssign | ast.Assign):
            keep += range(node.lineno, (node.end_lineno or node.lineno) + 1)
        elif isinstance(node, ast.FunctionDef):
            keep += [d.lineno for d in node.decorator_list] + [node.lineno]
    keep = sorted(set(keep))
    if len(keep) <= MAX_EXCERPT or focus is None or focus not in keep:
        chosen = keep[:MAX_EXCERPT]
    else:
        # header plus a window of field lines centred on the focus
        i = keep.index(focus)
        lo = max(1, min(i - (MAX_EXCERPT - 1) // 2, len(keep) - (MAX_EXCERPT - 1)))
        chosen = [keep[0], *keep[lo : lo + MAX_EXCERPT - 1]]
    return "\n".join(lines[i - 1] for i in chosen)


def _is_route_write(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for d in fn.decorator_list:
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in WRITE_METHODS:
            return True
    return False


def _is_env_read(node: ast.AST) -> bool:
    if isinstance(node, ast.Call):
        target = _dotted(node.func)
        return target in {"os.getenv", "os.environ.get", "getenv", "environ.get"}
    if isinstance(node, ast.Subscript):
        return _dotted(node.value) in {"os.environ", "environ"}
    return False


def _is_dump(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call) or _name(node.func) not in DUMP_CALLS:
        return False
    owner = _dotted(node.func.value) if isinstance(node.func, ast.Attribute) else ""
    last = owner.split(".")[-1]
    if _name(node.func) == "write_text":
        # formatter.write_text and friends write help output, not a file
        target = node.func.value if isinstance(node.func, ast.Attribute) else node.func
        return (isinstance(target, ast.Call) and _name(target) == "Path") or bool(re.search(r"(?i)path|file", last))
    return last in {"yaml", "json", "toml", "tomli_w"}


def _is_pool_call(node: ast.AST) -> TypeGuard[ast.Call]:
    if not isinstance(node, ast.Call):
        return False
    return _name(node.func) in POOL_FACTORIES or bool({k.arg for k in node.keywords} & POOL_KWARGS)


def _scan_function(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, symbol: str, rel: str, lines: list[str], module: str
) -> Iterator[Surface]:
    end = fn.end_lineno or fn.lineno
    start = min([d.lineno for d in fn.decorator_list] + [fn.lineno])
    excerpt = _excerpt(lines, start, end)
    decos = {_name(d) for d in fn.decorator_list}
    if decos & VALIDATOR_DECOS:
        yield Surface(file=rel, symbol=symbol, kind="validator", excerpt=excerpt)
    is_consumer = (
        _is_route_write(fn)
        or bool(decos & TASK_DECOS)
        or (bool(CONSUMER_NAME.search(fn.name)) and _takes_message(fn))
        or (module == "crud" and bool(CRUD_NAME.match(fn.name)))
    )
    if is_consumer:
        yield Surface(file=rel, symbol=symbol, kind="consumer", excerpt=excerpt)
    if CACHE_KEY_NAME.search(fn.name):
        yield Surface(file=rel, symbol=symbol, kind="cache-key", excerpt=excerpt)
    body = list(ast.walk(fn))
    if any(_is_env_read(n) for n in body):
        yield Surface(file=rel, symbol=symbol, kind="env-read", excerpt=excerpt)
    if any(_is_dump(n) for n in body):
        yield Surface(file=rel, symbol=symbol, kind="config-writer", excerpt=excerpt)
    if any(isinstance(n, ast.Call) and _name(n.func) in RESOURCE_PROBES for n in body):
        # a size resolved from the machine at call time is where resource-aware defaults attach
        yield Surface(file=rel, symbol=symbol, kind="pool-config", excerpt=_excerpt(lines, start, end))


def _takes_message(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    args = [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]
    return any(MESSAGE_PARAM.search(a.arg) for a in args if a.arg not in {"self", "cls"})


def _raises_check(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """raises a value/type/usage error or calls self.fail, i.e. the method rejects bad input."""
    for n in ast.walk(fn):
        if isinstance(n, ast.Raise) and n.exc is not None and _name(n.exc) in CHECK_ERRORS:
            return True
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "fail":
            return True
    return False


def _check_outline(fn: ast.FunctionDef | ast.AsyncFunctionDef, lines: list[str]) -> list[int]:
    """signature plus every if-branch that raises, so a long constructor shows its checks."""
    body_start = fn.body[0].lineno
    keep = list(range(fn.lineno, body_start))
    for n in ast.walk(fn):
        if isinstance(n, ast.If) and any(isinstance(b, ast.Raise) for b in n.body):
            keep += range(n.lineno, (n.end_lineno or n.lineno) + 1)
    return sorted(set(keep))


def _converter_excerpt(cls: ast.ClassDef, fn: ast.FunctionDef | ast.AsyncFunctionDef, lines: list[str]) -> str:
    """class header, fields, __init__ (or its signature and checks when long), then the method, capped."""
    keep = [cls.lineno]
    for node in cls.body:
        if isinstance(node, ast.AnnAssign | ast.Assign):
            keep += range(node.lineno, (node.end_lineno or node.lineno) + 1)
        elif isinstance(node, ast.FunctionDef) and node.name == "__init__" and node is not fn:
            end = node.end_lineno or node.lineno
            keep += range(node.lineno, end + 1) if end - node.lineno < 25 else _check_outline(node, lines)
    keep += range(fn.lineno, (fn.end_lineno or fn.lineno) + 1)
    return "\n".join(lines[i - 1] for i in sorted(set(keep))[:WIDE_EXCERPT])


def _library_validators(cls: ast.ClassDef, rel: str, lines: list[str]) -> Iterator[Surface]:
    """converter methods and constructor checks of plain classes: where a library validates its inputs."""
    for node in cls.body:
        if not isinstance(node, ast.FunctionDef) or not _raises_check(node):
            continue
        if node.name in CONVERT_METHODS or CHECK_METHOD.match(node.name):
            excerpt = _converter_excerpt(cls, node, lines)
        elif node.name == "__init__":
            excerpt = "\n".join(lines[i - 1] for i in [cls.lineno, *_check_outline(node, lines)][:WIDE_EXCERPT])
        else:
            continue
        yield Surface(file=rel, symbol=f"{cls.name}.{node.name}", kind="validator", excerpt=excerpt)


def _scan_class(
    cls: ast.ClassDef, rel: str, lines: list[str], module: str, models: dict[str, int]
) -> Iterator[Surface]:
    """models maps model class names seen earlier in the file to their field count, inherited ones included."""
    bases = {_name(b) for b in cls.bases}
    is_table = any(k.arg == "table" for k in cls.keywords)
    if bases & SETTINGS_BASES:
        yield Surface(file=rel, symbol=cls.name, kind="settings-class", excerpt=_class_outline(cls, lines))
        for node in cls.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if POOL_FIELD.search(node.target.id.upper()):
                    yield Surface(
                        file=rel,
                        symbol=f"{cls.name}.{node.target.id}",
                        kind="pool-config",
                        excerpt=_class_outline(cls, lines, focus=node.lineno),
                    )
    elif bases & (MODEL_BASES | set(models)):
        fields = sum(isinstance(n, ast.AnnAssign) for n in cls.body) + sum(models.get(b, 0) for b in bases)
        models[cls.name] = fields
        if fields >= 2 and not is_table and not OUTPUT_MODEL.search(cls.name):
            # request/input models are where cross-field rules belong
            yield Surface(file=rel, symbol=cls.name, kind="validator", excerpt=_class_outline(cls, lines))
    else:
        yield from _library_validators(cls, rel, lines)
    for node in cls.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for s in _scan_function(node, f"{cls.name}.{node.name}", rel, lines, module):
                # settings validators are already part of the settings-class surface
                if not (s.kind == "validator" and bases & SETTINGS_BASES):
                    yield s


def _module_level(tree: ast.Module, rel: str, lines: list[str]) -> Iterator[Surface]:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        for sub in ast.walk(node):
            if _is_pool_call(sub):
                yield Surface(
                    file=rel,
                    symbol=f"{_name(sub.func)}:{sub.lineno}",
                    kind="pool-config",
                    # module-level calls need their imports and neighbours to make sense
                    excerpt=_excerpt(lines, max(1, node.lineno - 10), (node.end_lineno or node.lineno) + 10),
                )
                break
            if _is_env_read(sub):
                yield Surface(
                    file=rel,
                    symbol=f"<module>:{node.lineno}",
                    kind="env-read",
                    excerpt=_excerpt(lines, node.lineno, node.end_lineno or node.lineno),
                )
                break


def scan_file(path: Path, rel: str) -> list[Surface]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return []
    lines = source.splitlines()
    module = path.stem
    out: list[Surface] = list(_module_level(tree, rel, lines))
    models: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            out += _scan_class(node, rel, lines, module, models)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            out += _scan_function(node, node.name, rel, lines, module)
    return out


def iter_py_files(root: Path) -> Iterator[Path]:
    # prune while walking so vendored trees like .venv are never traversed
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            if name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py":
                continue
            yield Path(dirpath) / name


def find_python_surfaces(repo_dir: Path, kinds: set[str] | None = None, source_root: str = ".") -> list[Surface]:
    """surfaces under repo_dir/source_root; Surface.file stays relative to the repo root for patches."""
    root = (repo_dir / source_root).resolve()
    seen: set[tuple[str, str, str]] = set()
    out: list[Surface] = []
    for path in iter_py_files(root):
        rel = path.resolve().relative_to(repo_dir.resolve()).as_posix()
        for s in scan_file(path, rel):
            key = (s.file, s.symbol, s.kind)
            if (kinds is None or s.kind in kinds) and key not in seen:
                seen.add(key)
                out.append(s)
    return out
