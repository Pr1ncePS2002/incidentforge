"""tree-sitter pass for what crg does not model: config reads, env reads and message handlers."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import tree_sitter_language_pack as tslp

from incidentforge.failmap.store import MapEdge, MapNode
from incidentforge.models import Language, Surface
from incidentforge.surfaces import find_surfaces

PLACEHOLDER = re.compile(r"(?i)^(changethis|change[-_ ]?me|todo|fixme|xxx+|<[^>]*>|replace[-_ ]?me|secret)$")
PY_ENV_CALLS = {"os.getenv", "os.environ.get", "getenv", "environ.get"}
PY_ENV_MAPS = {"os.environ", "environ"}
PY_PARSERS = {"int", "float", "bool", "Decimal", "json.loads", "timedelta"}
PY_VALIDATORS = {"field_validator", "model_validator", "validator", "root_validator"}
GO_ENV_CALLS = {"os.Getenv", "os.LookupEnv"}
GO_PARSERS = re.compile(r"^(strconv\.\w+|time\.ParseDuration|url\.Parse)$")
GO_TAG_KEY = re.compile(r'\b(env|envconfig|mapstructure|koanf|yaml|toml)\s*:\s*"([^",]*)')
GO_TAG_DEFAULT = re.compile(r'\b(envDefault|default)\s*:\s*"')
GO_TAG_REQUIRED = re.compile(r'required|validate\s*:\s*"[^"]*required')
CONFIG_KEY = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
DEFAULT_FIELDS = {"rawValue", "defaultValue", "default", "Default", "DefaultValue"}
VALIDATOR_FIELDS = {"validator", "validate", "Validator", "Validate"}
TYPE_FIELDS = {"valueType", "type", "Type", "kind"}
DEDUPE = re.compile(r"(?i)idempot|dedup|already|exists|get_\w*by_|on_conflict|upsert|unique|processed|seen|ON CONFLICT")
# underscore-bounded so ADMIN_PASSWORD is not read as a MIN_ bound
POOL_KEY = re.compile(
    r"(^|_)(POOL|TIMEOUT|WORKERS?|CONCURRENCY|RETRIES|RETRY|TTL|EXPIRE\w*|MAX|MIN|SIZE|LIMIT|CONNS?|BATCH|BUFFER)(_|$)"
)
TEST_FILE = re.compile(r"(^|/)(tests?|testdata)/|(^|/)test_[^/]*\.py$|_test\.(py|go)$|(^|/)conftest\.py$")


@dataclass
class _File:
    rel: str
    src: bytes
    owners: list[MapNode] = field(default_factory=list)

    def owner_at(self, line: int) -> str:
        """innermost function/class covering a line, else the file node itself."""
        best: MapNode | None = None
        for n in self.owners:
            if n.line_start <= line <= n.line_end and (best is None or n.line_start >= best.line_start):
                best = n
        return best.id if best else self.rel


def _is_pool(name: str) -> bool:
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).upper()
    return bool(POOL_KEY.search(snake))


def _text(node: Any) -> str:
    return bytes(node.text).decode("utf-8", errors="replace")


def _walk(node: Any) -> Iterator[Any]:
    stack = [node]
    while stack:
        cur = stack.pop()
        yield cur
        stack.extend(reversed(cur.children))


def _string_value(node: Any | None) -> str | None:
    if node is None or node.type not in {"string", "interpreted_string_literal", "raw_string_literal"}:
        return None
    raw = _text(node)
    if node.type == "string":
        raw = re.sub(r"^[rbuRBUfF]*", "", raw)
    return raw[1:-1] if len(raw) >= 2 else ""


def _args(call: Any) -> list[Any]:
    args = call.child_by_field_name("arguments")
    return [] if args is None else list(args.named_children)


@dataclass
class _Out:
    nodes: dict[str, MapNode] = field(default_factory=dict)
    edges: set[MapEdge] = field(default_factory=set)

    def add(self, f: _File, kind: str, nid: str, name: str, line: int, attrs: dict[str, Any], owner: str) -> None:
        if nid in self.nodes:
            return
        lang = "go" if f.rel.endswith(".go") else "python"
        self.nodes[nid] = MapNode(nid, kind, name, f.rel, line, line, lang, False, attrs)
        edge_kind = {"config_read": "READS_CONFIG", "env_read": "READS_ENV", "handler": "HANDLES"}[kind]
        self.edges.add(MapEdge(edge_kind, owner, nid, line))


def _py_env(f: _File, root: Any, out: _Out) -> None:
    for n in _walk(root):
        key: str | None = None
        has_default = False
        if n.type == "call":
            fn = n.child_by_field_name("function")
            if fn is None or _text(fn) not in PY_ENV_CALLS:
                continue
            args = _args(n)
            key = _string_value(args[0]) if args else None
            has_default = len(args) >= 2
        elif n.type == "subscript":
            value = n.child_by_field_name("value")
            if value is None or _text(value) not in PY_ENV_MAPS:
                continue
            # os.environ[k] = v is a write, not a read
            if n.parent is not None and n.parent.type == "assignment" and n.parent.child_by_field_name("left") == n:
                continue
            key = _string_value(n.child_by_field_name("subscript"))
        else:
            continue
        parent = n.parent.parent if n.parent is not None and n.parent.type == "argument_list" else None
        parsed = (
            parent is not None and parent.type == "call" and _text(parent.child_by_field_name("function")) in PY_PARSERS
        )
        line = n.start_point[0] + 1
        owner = f.owner_at(line)
        k = key or "<dynamic>"
        attrs = {"key": k, "has_default": has_default, "parsed": parsed}
        out.add(f, "env_read", f"{owner}#env:{k}", k, line, attrs, owner)


def _py_settings(f: _File, root: Any, out: _Out) -> None:
    for cls in _walk(root):
        if cls.type != "class_definition":
            continue
        bases = cls.child_by_field_name("superclasses")
        if bases is None or "BaseSettings" not in {_text(b).split(".")[-1] for b in bases.named_children}:
            continue
        name = _text(cls.child_by_field_name("name"))
        body = cls.child_by_field_name("body")
        checked = _validated_names(body)
        for stmt in body.named_children:
            assign = stmt.named_children[0] if stmt.type == "expression_statement" and stmt.named_children else stmt
            if assign.type != "assignment" or assign.child_by_field_name("type") is None:
                continue
            fname = _text(assign.child_by_field_name("left"))
            right = assign.child_by_field_name("right")
            default = _string_value(right)
            ann = _text(assign.child_by_field_name("type"))
            attrs = {
                "key": fname,
                "type": ann,
                "has_default": right is not None,
                "placeholder_default": default is not None and bool(PLACEHOLDER.match(default.strip())),
                "validated": fname in checked,
                "typed": ann.split("|")[0].strip() not in {"str", "Optional[str]"},
                "pool": _is_pool(fname),
            }
            line = assign.start_point[0] + 1
            owner = f"{f.rel}::{name}"
            out.add(f, "config_read", f"{f.rel}::{name}.{fname}", fname, line, attrs, owner)


def _validated_names(body: Any) -> set[str]:
    """field names a validator method mentions, by string literal or attribute access."""
    names: set[str] = set()
    for dec in body.named_children:
        if dec.type != "decorated_definition":
            continue
        decos = {_text(d).lstrip("@").split("(")[0].split(".")[-1] for d in dec.named_children if d.type == "decorator"}
        if not decos & PY_VALIDATORS:
            continue
        for n in _walk(dec):
            if n.type == "string":
                names.add(_string_value(n) or "")
            elif n.type == "attribute":
                attr = n.child_by_field_name("attribute")
                if attr is not None:
                    names.add(_text(attr))
    return names


def _go_calls(f: _File, root: Any, out: _Out, viper_defaults: set[str]) -> None:
    for n in _walk(root):
        if n.type != "call_expression":
            continue
        fn = _text(n.child_by_field_name("function"))
        args = _args(n)
        key = _string_value(args[0]) if args else None
        line = n.start_point[0] + 1
        owner = f.owner_at(line)
        if fn in GO_ENV_CALLS:
            parent = n.parent.parent if n.parent is not None and n.parent.type == "argument_list" else None
            parsed = parent is not None and bool(GO_PARSERS.match(_text(parent.child_by_field_name("function"))))
            k = key or "<dynamic>"
            attrs = {"key": k, "has_default": fn == "os.LookupEnv", "parsed": parsed}
            out.add(f, "env_read", f"{owner}#env:{k}", k, line, attrs, owner)
        elif fn.startswith("viper.Get") and key:
            attrs = {
                "key": key,
                "has_default": key in viper_defaults,
                "validated": False,
                "typed": fn != "viper.GetString",
            }
            out.add(f, "config_read", f"{owner}#config:{key}", key, line, attrs, owner)


def _go_struct_fields(f: _File, root: Any, out: _Out) -> None:
    for spec in _walk(root):
        if spec.type != "type_spec":
            continue
        struct = spec.child_by_field_name("type")
        if struct is None or struct.type != "struct_type":
            continue
        tname = _text(spec.child_by_field_name("name"))
        for fd in _walk(struct):
            if fd.type != "field_declaration":
                continue
            tag = fd.child_by_field_name("tag")
            tag_text = _text(tag) if tag is not None else ""
            m = GO_TAG_KEY.search(tag_text)
            # untagged fields of config-ish structs are internal state, not settings
            if not m:
                continue
            names = [_text(c) for c in fd.children_by_field_name("name")]
            ftype = _text(fd.child_by_field_name("type")) if fd.child_by_field_name("type") is not None else ""
            for fname in names:
                attrs = {
                    "key": m.group(2) or fname,
                    "type": ftype,
                    "has_default": bool(GO_TAG_DEFAULT.search(tag_text)),
                    "validated": bool(GO_TAG_REQUIRED.search(tag_text)),
                    "typed": "string" not in ftype,
                    "pool": _is_pool(fname),
                }
                line = fd.start_point[0] + 1
                out.add(f, "config_read", f"{f.rel}::{tname}.{fname}", fname, line, attrs, f.owner_at(line))


def _go_config_table(f: _File, root: Any, out: _Out) -> None:
    """string-keyed composite literals like {"KEY": {rawValue: "", validator: v}}: a defaults table."""
    for el in _walk(root):
        if el.type != "keyed_element" or len(el.named_children) != 2:
            continue
        key_node, val_node = el.named_children
        key = _string_value(key_node.named_children[0] if key_node.named_children else key_node)
        lit = val_node.named_children[0] if val_node.named_children else None
        if key is None or not CONFIG_KEY.match(key) or lit is None or lit.type != "literal_value":
            continue
        fields: dict[str, str] = {}
        for sub in lit.named_children:
            if sub.type == "keyed_element" and len(sub.named_children) == 2:
                fields[_text(sub.named_children[0])] = _text(sub.named_children[1])
        if not fields:
            continue
        default = next((v for k, v in fields.items() if k in DEFAULT_FIELDS), None)
        vtype = next((v for k, v in fields.items() if k in TYPE_FIELDS), "")
        attrs = {
            "key": key,
            "type": vtype,
            "has_default": default is not None and default not in {'""', "``", "nil"},
            "validated": bool(VALIDATOR_FIELDS & fields.keys()),
            "typed": bool(vtype) and "string" not in vtype.lower(),
            "pool": _is_pool(key),
        }
        line = el.start_point[0] + 1
        out.add(f, "config_read", f"{f.rel}::config:{key}", key, line, attrs, f.owner_at(line))


def _viper_defaults(files: list[_File], parser: Any) -> set[str]:
    keys: set[str] = set()
    for f in files:
        if b"SetDefault" not in f.src:
            continue
        for n in _walk(parser.parse(f.src).root_node):
            if n.type == "call_expression" and _text(n.child_by_field_name("function")) == "viper.SetDefault":
                args = _args(n)
                key = _string_value(args[0]) if args else None
                if key:
                    keys.add(key)
    return keys


def surface_node_id(s: Surface, nodes: dict[str, MapNode]) -> str | None:
    """the map node a flat-scan surface lands on; module-level symbols fall back to their file."""
    direct = f"{s.file}::{s.symbol}"
    if direct in nodes:
        return direct
    tail = s.symbol.rpartition(":")[2]
    if tail.isdigit():
        line = int(tail)
        for n in nodes.values():
            if n.file == s.file and n.kind == "env_read" and n.line_start == line and s.kind == "env-read":
                return n.id
    if s.kind == "pool-config":
        for n in nodes.values():
            if n.file == s.file and n.kind == "config_read" and n.id.endswith(f".{s.symbol.split('.')[-1]}"):
                return n.id
    return s.file if s.file in nodes else None


def overlay(
    repo: Path, language: Language, nodes: list[MapNode], surfaces: list[Surface] | None = None
) -> tuple[list[MapNode], list[MapEdge]]:
    """overlay nodes/edges; also stamps surface_kinds onto the crg nodes the flat scan points at."""
    parser = tslp.get_parser(language.value)
    by_file: dict[str, _File] = {}
    for n in nodes:
        if n.kind == "File" and not TEST_FILE.search(n.file):
            by_file[n.file] = _File(n.file, (repo / n.file).read_bytes())
    for n in nodes:
        if n.kind in {"Function", "Class", "Test"} and n.file in by_file:
            by_file[n.file].owners.append(n)
    files = [by_file[k] for k in sorted(by_file)]
    out = _Out()
    viper = _viper_defaults(files, parser) if language is Language.go else set()
    for f in files:
        root = parser.parse(f.src).root_node
        if language is Language.python:
            _py_settings(f, root, out)
            _py_env(f, root, out)
        else:
            _go_calls(f, root, out, viper)
            _go_struct_fields(f, root, out)
            _go_config_table(f, root, out)
    index = {n.id: n for n in nodes} | out.nodes
    flat = find_surfaces(repo, language) if surfaces is None else surfaces
    kinds: dict[str, set[str]] = {}
    for s in flat:
        nid = surface_node_id(s, index)
        if nid is None:
            continue
        kinds.setdefault(nid, set()).add(s.kind)
        target = index[nid]
        if s.kind == "consumer" and not target.is_overlay and target.file in by_file:
            f = by_file[target.file]
            body = b"\n".join(f.src.splitlines()[target.line_start - 1 : target.line_end]).decode(errors="replace")
            attrs = {"dedupe": bool(DEDUPE.search(body))}
            out.add(f, "handler", f"{nid}#handler", target.name, target.line_start, attrs, nid)
    for nid, ks in kinds.items():
        index[nid].attrs["surface_kinds"] = sorted(ks)
    return sorted(out.nodes.values(), key=lambda n: n.id), sorted(out.edges)


def is_test_path(path: str) -> bool:
    return bool(TEST_FILE.search(PurePosixPath(path).as_posix()))
