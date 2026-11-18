"""go surface finder; a lexical scanner so forge needs no go toolchain or native parser on the host."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from incidentforge.models import Surface

KINDS = ("settings-class", "env-read", "validator", "consumer", "cache-key", "pool-config", "config-writer")
SKIP_DIRS = {"vendor", "testdata", ".git", "node_modules", "third_party"}
MAX_EXCERPT_LINES = 40
MAX_EXCERPT_CHARS = 2000

_DECL = re.compile(
    r"^(?:type\s+(?P<type>\w+)(?:\[[^\]]*\])?\s+struct\s*\{"
    r"|func\s+(?:\(\s*\w*\s*\*?\s*(?P<recv>\w+)(?:\[[^\]]*\])?\s*\)\s*)?(?P<func>\w+)(?:\[[^\]]*\])?\s*\()",
    re.MULTILINE,
)
_CONFIG_NAME = re.compile(r"(?i)(config|conf$|options|settings|^opts$|params$)")
_CONFIG_TAG = re.compile(r'`[^`]*\b(env|envconfig|mapstructure|koanf|yaml|toml)\s*:\s*"')
_ENV_READ = re.compile(
    r"\bos\.(Getenv|LookupEnv|Environ)\s*\(|\bviper\.(Get\w*|Unmarshal\w*)\s*\(|\benvconfig\.Process\s*\("
    r"|\benv\.Parse\w*\s*\(|\bcleanenv\.Read\w*\s*\(|\bgodotenv\.Load\s*\("
)
_VALIDATOR_NAME = re.compile(r"(?i)^(validate|verify|check)\w*$|\w*(validate|validator)$")
_CONSUMER_NAME = re.compile(
    r"^(?:[Cc]onsume|[Ss]ubscribe|[Oo]nMessage|(?:[Hh]andle|[Pp]rocess)(?:Message|Event|Delivery|Job|Task))"
    r"|(?:Consumer|Subscriber)$"
)
_CONSUMER_BODY = re.compile(r"\bamqp\.Delivery\b|\bkafka\.Message\b|\bnats\.Msg\b|\bsarama\.ConsumerMessage\b")
_CACHE_NAME = re.compile(r"(?i:cache\w*key|key\w*cache)|[Kk]eyFor(?:[A-Z_]|$)|^(?:[Bb]uild|[Mm]ake)\w*Key$")
# keys and topic names built from runtime parts are what env-aware-naming tasks attach to
_CACHE_BODY = re.compile(r'(?i)fmt\.Sprintf\(\s*"(?=[^"]*%)[^"]*(cache|prefix|namespace|topic|queue|key)')
_POOL = re.compile(
    r"(?i)(pool_?size|max_?conns|min_?conns|max_?idle\w*|max_?open\w*|workers?(_?count|_?pool\w*)?$"
    r"|batch_?size|concurrency|parallelism|queue_?size|buffer_?size)"
)
_WRITER_NAME = re.compile(r"(?i)^(save|write|dump|marshal|export|persist|store|serialize|encode)\w*$")


@dataclass
class _Decl:
    file: str
    symbol: str
    name: str
    receiver: str
    is_type: bool
    text: str


def find_go_surfaces(repo_dir: Path, kinds: set[str] | None = None, source_root: str = ".") -> list[Surface]:
    """scan non-test go files under source_root and classify top-level decls into surface kinds."""
    root = (repo_dir / source_root).resolve()
    wanted = set(KINDS) if kinds is None else kinds & set(KINDS)
    seen: set[tuple[str, str, str]] = set()
    out: list[Surface] = []
    for path in sorted(_go_files(root)):
        rel = path.relative_to(repo_dir.resolve()).as_posix()
        for decl in _decls(rel, path.read_text(errors="replace")):
            for kind in _classify(decl):
                key = (rel, decl.symbol, kind)
                if kind in wanted and key not in seen:
                    seen.add(key)
                    out.append(Surface(file=rel, symbol=decl.symbol, kind=kind, excerpt=_excerpt(decl.text)))
    return out


def _go_files(root: Path) -> Iterator[Path]:
    for path in root.rglob("*.go"):
        if path.name.endswith("_test.go") or SKIP_DIRS & set(path.relative_to(root).parts[:-1]):
            continue
        yield path


def _decls(rel: str, src: str) -> Iterator[_Decl]:
    for m in _DECL.finditer(src):
        open_at = src.find("{", m.end() - 1) if m.group("type") else _body_start(src, m.end())
        if open_at < 0:
            continue
        end = _match_brace(src, open_at)
        text = src[m.start() : end + 1]
        if m.group("type"):
            name = m.group("type")
            yield _Decl(rel, name, name, "", True, text)
        else:
            name, recv = m.group("func"), m.group("recv") or ""
            yield _Decl(rel, f"{recv}.{name}" if recv else name, name, recv, False, text)


def _body_start(src: str, pos: int) -> int:
    """first '{' after the signature at paren depth 0; -1 when the line ends first (an external func)."""
    depth = 1  # the regex consumed the opening paren of the params
    i = pos
    while i < len(src):
        c = src[i]
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == "{" and depth == 0:
            # an inline interface{} or struct{} in the result list is not the body
            if re.search(r"\b(interface|struct)\s*$", src[pos:i]):
                i = _match_brace(src, i) + 1
                continue
            return i
        elif c == "\n" and depth == 0 and src[i - 1] not in ",(":
            return -1
        i += 1
    return -1


def _match_brace(src: str, start: int) -> int:
    """index of the brace closing src[start], skipping strings, runes and comments."""
    depth, i, n = 0, start, len(src)
    while i < n:
        c = src[i]
        if c == "/" and src.startswith("//", i):
            i = src.find("\n", i)
            i = n if i < 0 else i
        elif c == "/" and src.startswith("/*", i):
            i = src.find("*/", i + 2)
            i = n if i < 0 else i + 1
        elif c in "\"'`":
            i = _skip_literal(src, i)
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n - 1


def _skip_literal(src: str, i: int) -> int:
    quote, i = src[i], i + 1
    while i < len(src) and src[i] != quote:
        if src[i] == "\\" and quote != "`":
            i += 1
        elif src[i] == "\n" and quote != "`":
            break
        i += 1
    return i


def _classify(d: _Decl) -> list[str]:
    kinds: list[str] = []
    if d.is_type:
        if _CONFIG_NAME.search(d.name) or _CONFIG_TAG.search(d.text):
            kinds.append("settings-class")
            if _POOL.search(d.text):
                kinds.append("pool-config")
        return kinds
    if _ENV_READ.search(d.text):
        kinds.append("env-read")
    if _VALIDATOR_NAME.search(d.name):
        kinds.append("validator")
    if _CONSUMER_NAME.search(d.name) or _CONSUMER_BODY.search(d.text):
        kinds.append("consumer")
    if _CACHE_NAME.search(d.name) or _CACHE_BODY.search(d.text):
        kinds.append("cache-key")
    if _POOL.search(d.name):
        kinds.append("pool-config")
    if _WRITER_NAME.search(d.name) and (_CONFIG_NAME.search(d.name) or _CONFIG_NAME.search(d.receiver)):
        kinds.append("config-writer")
    return kinds


def _excerpt(text: str) -> str:
    lines = text.splitlines()
    clipped = "\n".join(lines[:MAX_EXCERPT_LINES])
    if len(lines) > MAX_EXCERPT_LINES:
        clipped += "\n\t// ..."
    return clipped[:MAX_EXCERPT_CHARS]
