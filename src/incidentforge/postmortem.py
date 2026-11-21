"""`forge from-postmortem`: public incident report -> family + trigger -> map surface -> generated, gated task."""

from __future__ import annotations

import json
import re
import tomllib
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from incidentforge.backends.base import Backend
from incidentforge.families import Family, list_families, load_family
from incidentforge.generate import (
    PREFIX,
    Generator,
    Pair,
    Validator,
    Writer,
    checkout,
    family_titles,
    find_target_surfaces,
    gold_example,
    next_number,
    slugify,
    surface_key,
)
from incidentforge.models import Surface, Target, TaskSpec, ValidationReport

# keeps the classifier prompt well inside one claude call; reports put the trigger near the top
MAX_TEXT_CHARS = 40_000
MAX_FETCH_BYTES = 5_000_000
FETCH_TIMEOUT = 30.0
TRIGGER_MAX_CHARS = 400
# a run this long copied from the report counts as quoting it, not summarising
QUOTE_WORDS = 12
NONE = "none"
USER_AGENT = "incidentforge/0.2 (postmortem snapshot)"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html,text/plain"}

Fetcher = Callable[[str], tuple[str, str]]


class PostmortemError(ValueError):
    """the postmortem cannot be loaded or turned into a task; the message says why."""


class NoFamilyFits(PostmortemError):
    """the classifier found no family whose protection matches the incident trigger."""


@dataclass
class Postmortem:
    text: str
    source_url: str
    snapshot: Path


class Classification(BaseModel):
    """classifier answer; strict so a sloppy reply is refused instead of guessed at."""

    model_config = ConfigDict(extra="forbid", strict=True)

    family: str
    trigger: str = Field(min_length=20, max_length=TRIGGER_MAX_CHARS)
    keywords: list[str] = Field(default_factory=list, max_length=8)
    reason: str = Field(min_length=1, max_length=600)

    @field_validator("family")
    @classmethod
    def _known(cls, v: str) -> str:
        if v != NONE and v not in list_families():
            raise ValueError(f"family {v!r} is not one of {list_families()} or {NONE!r}")
        return v

    @field_validator("trigger")
    @classmethod
    def _short(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(sentences(v)) > 2:
            raise ValueError("trigger must be one or two sentences")
        return v

    @field_validator("keywords")
    @classmethod
    def _words(cls, v: list[str]) -> list[str]:
        bad = [k for k in v if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,30}", k)]
        if bad:
            raise ValueError(f"keywords must be single lower-case words: {bad}")
        return v


def classification_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "family": {"type": "string", "enum": [*list_families(), NONE]},
            "trigger": {"type": "string"},
            "keywords": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string"},
        },
        "required": ["family", "trigger", "keywords", "reason"],
        "additionalProperties": False,
    }


def sentences(text: str) -> list[str]:
    # split on a terminator followed by a capital or digit, so "e.g. the" and "v1.2" stay whole
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", text.strip()) if s]


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def copied_run(summary: str, source: str, n: int = QUOTE_WORDS) -> str | None:
    """first n-word run of summary that appears verbatim in source, or none."""
    words = _words(summary)
    src = _words(source)
    grams = {tuple(src[i : i + n]) for i in range(len(src) - n + 1)}
    for i in range(len(words) - n + 1):
        if tuple(words[i : i + n]) in grams:
            return " ".join(words[i : i + n])
    return None


class _TextParser(HTMLParser):
    SKIP = frozenset({"script", "style", "noscript", "svg", "head", "nav", "footer", "form", "template"})
    BLOCK = frozenset({"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "section", "article"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _TextParser()
    p.feed(html)
    p.close()
    lines = (" ".join(line.split()) for line in "".join(p.parts).splitlines())
    return "\n".join(line for line in lines if line)


def fetch_url(url: str) -> tuple[str, str]:
    """plain GET; returns (body, content type). only public http(s) pages, no auth or cookies."""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        raw = resp.read(MAX_FETCH_BYTES + 1)
        ctype = resp.headers.get("Content-Type", "")
        charset = resp.headers.get_content_charset() or "utf-8"
    if len(raw) > MAX_FETCH_BYTES:
        raise PostmortemError(f"{url} is larger than {MAX_FETCH_BYTES} bytes")
    return raw.decode(charset, errors="replace"), ctype


def snapshot_name(url: str) -> str:
    u = urlparse(url)
    return slugify(f"{u.netloc} {u.path}", 10)


def load_postmortem(
    source: str, work_root: Path, source_url: str | None = None, fetch: Fetcher = fetch_url
) -> Postmortem:
    """local file or public url -> plain text snapshot under work/postmortems/ (never committed)."""
    if re.match(r"https?://", source):
        if urlparse(source).scheme not in {"http", "https"} or not urlparse(source).netloc:
            raise PostmortemError(f"not a usable url: {source}")
        body, ctype = fetch(source)
        text = html_to_text(body) if "html" in ctype or body.lstrip()[:1] == "<" else body
        url = source_url or source
    else:
        path = Path(source)
        if not path.is_file():
            raise PostmortemError(f"no such file: {source}")
        if not source_url:
            # every task must link back to a public report, so a local copy needs its url
            raise PostmortemError("a local postmortem file needs --source-url pointing at the public report")
        body = path.read_text(errors="replace")
        text = html_to_text(body) if path.suffix in {".html", ".htm"} else body
        url = source_url
    if not re.match(r"https?://[^/\s]+", url):
        raise PostmortemError(f"source url must be a public http(s) url: {url}")
    text = text.strip()
    if len(_words(text)) < 50:
        raise PostmortemError(f"postmortem text from {source} is too short ({len(_words(text))} words)")
    snap = work_root / "postmortems" / f"{snapshot_name(url)}.txt"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(text + "\n")
    return Postmortem(text, url, snap)


def classifier_prompt(pm: Postmortem, families: list[Family]) -> str:
    catalogue = "\n".join(f"- `{f.slug}`: {f.title}. {' '.join(f.intent.split())}" for f in families)
    body = pm.text[:MAX_TEXT_CHARS]
    return (
        "You classify a public production incident report into a catalogue of failure classes. Each class "
        "names a protection that a service can add in its configuration or startup code.\n\n"
        f"## classes\n\n{catalogue}\n\n"
        "## what to return\n\n"
        "- `family`: the one class whose protection, had it been in place, would have prevented or contained "
        f"the trigger of this incident. Use `{NONE}` when no class fits the trigger itself; do not stretch a "
        "class to fit a loosely related symptom.\n"
        "- `trigger`: one or two sentences, in your own words, naming the concrete configuration or code "
        "condition that set the incident off (not the impact, not the timeline). Do not quote the report "
        "and do not name people.\n"
        "- `keywords`: up to five single lower-case words for the kind of setting or resource involved "
        "(for example: timeout, pool, env, secret, cache, url, token, retry).\n"
        "- `reason`: one sentence on why that class fits, or why none does.\n\n"
        f"## report ({pm.source_url})\n\n<report>\n{body}\n</report>\n"
    )


def _check(data: dict[str, Any], pm: Postmortem) -> Classification:
    try:
        cls = Classification.model_validate(data)
    except ValidationError as exc:
        raise PostmortemError(f"classifier answer rejected: {exc.errors()[0]['msg']}") from exc
    quoted = copied_run(cls.trigger, pm.text)
    if quoted:
        raise PostmortemError(f"trigger quotes the report verbatim ({quoted!r}); a summary is required")
    return cls


def classify(pm: Postmortem, backend: Backend, families: list[Family], expected: str | None = None) -> Classification:
    """structured call with one corrective retry; invalid twice, or naming no class without `expected`, is refused."""
    prompt = classifier_prompt(pm, families)
    try:
        cls = _check(backend.generate_json(prompt, classification_schema(), tag="postmortem-classify"), pm)
    except PostmortemError as exc:
        retry = f"{prompt}\nyour previous answer was rejected: {exc}. answer again and fix that.\n"
        cls = _check(backend.generate_json(retry, classification_schema(), tag="postmortem-classify"), pm)
    if expected is not None:
        if expected not in {f.slug for f in families}:
            raise PostmortemError(f"--family {expected} is not a family for this target's language")
        # the caller logs a disagreement; the trigger is still the classifier's own summary
        return cls
    if cls.family == NONE:
        raise NoFamilyFits(f"no family fits this incident: {cls.reason}")
    if cls.family not in {f.slug for f in families}:
        raise NoFamilyFits(f"family {cls.family} does not support this target's language: {cls.reason}")
    return cls


def used_surfaces(tasks_root: Path, target: str, family: str) -> set[str]:
    """symbol slugs and map nodes already taken by a kept task of this family, so a second task differs."""
    prefix = PREFIX.get(family, slugify(family, 1)[:2])
    taken: set[str] = set()
    base = tasks_root / target
    for d in sorted(base.iterdir()) if base.exists() else []:
        m = re.match(rf"{prefix}-\d+-(.+)$", d.name)
        if m:
            taken.add(m.group(1))
        toml = d / "task.toml"
        if toml.exists():
            meta = tomllib.loads(toml.read_text()).get("metadata", {})
            if meta.get("family") == family and meta.get("map_node"):
                taken.add(str(meta["map_node"]))
    return taken


def rank_for_incident(
    surfaces: list[Surface], family: Family, tags: dict[str, list[str]], keywords: list[str], taken: set[str]
) -> list[Surface]:
    """map tag for the family first, then keyword overlap, then the family's kind order, then risk order."""
    from incidentforge.families.sampling import rank_surfaces

    kind_rank = {k: i for i, k in enumerate(family.surface_kinds)}
    seen: set[str] = set()
    cands: list[Surface] = []
    for s in surfaces:
        key = surface_key(s)
        slug = slugify(s.symbol.split(".")[-1], 3)
        if s.kind not in kind_rank or key in seen or slug in taken or (s.node_id and s.node_id in taken):
            continue
        seen.add(key)
        cands.append(s)
    risk = {surface_key(s): i for i, s in enumerate(rank_surfaces(cands))}

    def score(s: Surface) -> tuple[int, int, int, int]:
        tagged = family.slug in tags.get(s.node_id or "", [])
        hay = f"{s.symbol} {s.file} {s.excerpt}".lower()
        hits = sum(1 for k in keywords if k in hay)
        return (-int(tagged), -hits, kind_rank[s.kind], risk[surface_key(s)])

    return sorted(cands, key=score)


def map_surfaces(
    target: Target, repo: Path, work_root: Path, log: Callable[[str], None]
) -> tuple[list[Surface], dict[str, list[str]]]:
    """flat-scan surfaces annotated from the failure map, building the map once if it is missing."""
    from incidentforge.failmap import MAP_FILE, map_dir
    from incidentforge.failmap.pipeline import annotate_surfaces, build_map
    from incidentforge.failmap.store import read_annotations

    map_path = map_dir(work_root, target.name) / MAP_FILE
    if not map_path.exists():
        log(f"no failure map for {target.name}; building it")
        build_map(target, repo, work_root)
    surfaces = annotate_surfaces(find_target_surfaces(repo, target), map_path)
    tags = {nid: a.tags for nid, a in read_annotations(map_path).items()}
    return surfaces, tags


def background(cls: Classification, url: str) -> str:
    return (
        "\n\n## background\n\n"
        f"This protection comes from a public incident report ({url}). What set that incident off: {cls.trigger}\n"
    )


@dataclass
class PostmortemGenerator(Generator):
    """the stock generator with the incident trigger in the prompt and the source on the task."""

    incident: Classification | None = None
    source_url: str = ""

    def prompt(self, pair: Pair, existing: list[str], previous_failure: str) -> str:
        base = super().prompt(pair, existing, previous_failure)
        if self.incident is None:
            return base
        section = (
            "## real incident this task re-creates\n\n"
            f"A public incident was set off by: {self.incident.trigger}\n\n"
            "Shape the task so its fault cases reproduce that trigger on the surface above, adapted to this "
            "repository. The instruction must describe the required behaviour without naming the company or "
            "quoting the report; a background note linking the report is added for you.\n\n"
        )
        marker = "## previous attempt"
        return base.replace(marker, section + marker, 1) if marker in base else f"{base}\n\n{section}"

    def build_spec(self, pair: Pair, data: dict[str, Any]) -> TaskSpec:
        spec = super().build_spec(pair, data)
        if self.incident is None:
            return spec
        instruction = spec.instruction.rstrip() + background(self.incident, self.source_url)
        return spec.model_copy(
            update={"source_url": self.source_url, "origin": "postmortem", "instruction": instruction}
        )


@dataclass
class PostmortemResult:
    classification: Classification
    postmortem: Postmortem
    candidates: list[Surface]
    reports: list[ValidationReport] = field(default_factory=list)
    classifier_family: str = ""

    @property
    def accepted(self) -> ValidationReport | None:
        return next((r for r in self.reports if r.accepted), None)


def from_postmortem(
    source: str,
    target: Target,
    backend: Backend,
    *,
    source_url: str | None = None,
    tasks_root: Path = Path("tasks"),
    work_root: Path = Path("work"),
    writer: Writer | None = None,
    validator: Validator | None = None,
    tries: int = 2,
    family: str | None = None,
    fetch: Fetcher = fetch_url,
    log: Callable[[str], None] = print,
) -> PostmortemResult:
    """classify, pick up to `tries` surfaces in rank order, and stop at the first accepted task."""
    from incidentforge.package import write_task
    from incidentforge.validate import validate_task

    pm = load_postmortem(source, work_root, source_url, fetch)
    families = [load_family(s) for s in list_families()]
    families = [f for f in families if target.language.value in f.languages]
    verdict = classify(pm, backend, families, expected=family)
    chosen = family or verdict.family
    if chosen != verdict.family:
        log(f"classifier picked {verdict.family}, using --family {chosen} as asked")
    cls = verdict.model_copy(update={"family": chosen})
    fam = next(f for f in families if f.slug == chosen)
    log(f"family {chosen}: {cls.trigger}")
    record = pm.snapshot.with_suffix(".json")
    row = {"source_url": pm.source_url, **cls.model_dump(), "classifier_family": verdict.family}
    record.write_text(json.dumps(row, indent=1) + "\n")

    repo = checkout(target, work_root)
    surfaces, tags = map_surfaces(target, repo, work_root, log)
    taken = used_surfaces(tasks_root, target.name, fam.slug)
    cands = rank_for_incident(surfaces, fam, tags, cls.keywords, taken)
    result = PostmortemResult(cls, pm, cands, classifier_family=verdict.family)
    if not cands:
        raise PostmortemError(f"no unused {fam.slug} surface in {target.name}")

    gen = PostmortemGenerator(
        target,
        backend,
        repo,
        tasks_root,
        work_root,
        writer or write_task,
        validator or validate_task,
        gold_example(tasks_root, target),
        log,
        incident=cls,
        source_url=pm.source_url,
    )
    prefix = PREFIX.get(fam.slug, slugify(fam.slug, 1)[:2])
    for s in cands[: max(1, tries)]:
        num = next_number(tasks_root, work_root, target.name, prefix, set())
        tid = f"{target.name}/{prefix}-{num:03d}-{slugify(s.symbol.split('.')[-1], 3)}"
        log(f"  surface {surface_key(s)} -> {tid}")
        outcome = gen.run_pair(Pair(fam, s, tid), family_titles(tasks_root, target.name, fam.slug))
        result.reports.append(outcome.report)
        state = "accepted" if outcome.report.accepted else "rejected"
        log(f"  {tid}: {state} after {outcome.attempts} attempt(s) {outcome.title}")
        if outcome.report.accepted:
            break
    return result
