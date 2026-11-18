"""python surface finder on a tiny fixture package and, when present, the fastapi-template clone."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from incidentforge.models import Language
from incidentforge.surfaces import find_surfaces
from incidentforge.surfaces.python import find_python_surfaces, iter_py_files, scan_file

CONFIG = """
import os
from pydantic import field_validator
from pydantic_settings import BaseSettings

DEBUG = os.getenv("DEBUG", "0")


class Settings(BaseSettings):
    DB_POOL_SIZE: int = 5
    REQUEST_TIMEOUT: float = 3.0
    NAME: str = "x"

    @field_validator("NAME")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()
"""

MODELS = """
from pydantic import BaseModel, model_validator
from sqlmodel import SQLModel


class WindowCreate(BaseModel):
    start: int
    end: int

    @model_validator(mode="after")
    def _order(self):
        return self


class WindowPublic(BaseModel):
    start: int
    end: int


class Row(SQLModel, table=True):
    id: int
    name: str
"""

HANDLERS = """
import json
import os

import yaml
from fastapi import APIRouter

from app.db import create_engine

router = APIRouter()
engine = create_engine("sqlite://", pool_size=3)


@router.post("/items")
def create_item(body: dict) -> dict:
    return body


@router.get("/items")
def list_items() -> list:
    return []


def handle_order_event(event: dict) -> None:
    secret = os.environ["SECRET"]
    print(secret)


def build_cache_key(user: str) -> str:
    return f"user:{user}"


def save_config(path, data) -> None:
    with open(path, "w") as fh:
        yaml.safe_dump(data, fh)
    json.dumps(data)


class Worker:
    def on_message(self, msg: dict) -> None:
        pass
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    app = tmp_path / "backend" / "app"
    app.mkdir(parents=True)
    (app / "config.py").write_text(CONFIG)
    (app / "models.py").write_text(MODELS)
    (app / "handlers.py").write_text(HANDLERS)
    (app / "crud.py").write_text("def create_user(x):\n    return x\n\ndef get_user(x):\n    return x\n")
    (app / "broken.py").write_text("def (:\n")
    tests = tmp_path / "backend" / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text("import os\nos.getenv('X')\n")
    (app / "test_inline.py").write_text("import os\nos.getenv('X')\n")
    return tmp_path


def _index(repo: Path) -> set[tuple[str, str, str]]:
    return {(s.kind, s.file, s.symbol) for s in find_python_surfaces(repo, source_root="backend")}


def test_finds_every_kind(repo: Path) -> None:
    got = _index(repo)
    cfg, mod, h = "backend/app/config.py", "backend/app/models.py", "backend/app/handlers.py"
    expected = {
        ("settings-class", cfg, "Settings"),
        ("pool-config", cfg, "Settings.DB_POOL_SIZE"),
        ("pool-config", cfg, "Settings.REQUEST_TIMEOUT"),
        ("validator", mod, "WindowCreate"),
        ("validator", mod, "WindowCreate._order"),
        ("consumer", h, "create_item"),
        ("consumer", h, "handle_order_event"),
        ("consumer", h, "Worker.on_message"),
        ("consumer", "backend/app/crud.py", "create_user"),
        ("env-read", h, "handle_order_event"),
        ("cache-key", h, "build_cache_key"),
        ("config-writer", h, "save_config"),
    }
    assert expected <= got
    # module-level surfaces carry their line so several in one file stay distinct
    assert {s for k, f, s in got if k == "env-read" and f == cfg} == {"<module>:6"}
    assert any(k == "pool-config" and s.startswith("create_engine:") for k, _, s in got)


def test_skips_noise(repo: Path) -> None:
    got = _index(repo)
    symbols = {s for _, _, s in got}
    # output models, table models, read routes, settings validators, tests and broken files are not surfaces
    assert not symbols & {"WindowPublic", "Row", "list_items", "Settings._strip", "get_user"}
    assert not any("tests/" in f or "test_inline" in f for _, f, _ in got)


def test_kind_filter_and_dispatch(repo: Path) -> None:
    only = find_surfaces(repo, Language.python, {"settings-class"})
    assert [s.symbol for s in only] == ["Settings"]
    assert "class Settings" in only[0].excerpt


def test_excerpt_capped(tmp_path: Path) -> None:
    fields = "\n".join(f"    F{i}: int = {i}" for i in range(80))
    src = f"from pydantic_settings import BaseSettings\nclass Big(BaseSettings):\n{fields}\n"
    f = tmp_path / "big.py"
    f.write_text(src)
    (s,) = [s for s in scan_file(f, "big.py") if s.kind == "settings-class"]
    assert len(s.excerpt.splitlines()) == 40


def test_unreadable_file(tmp_path: Path) -> None:
    f = tmp_path / "bin.py"
    f.write_bytes(b"\xff\xfe\x00bad")
    assert scan_file(f, "bin.py") == []


TEMPLATE = Path.home() / "Hackathon/incidentforge/work/fastapi-template"


@pytest.mark.skipif(not (TEMPLATE / "backend").exists(), reason="fastapi-template clone not present")
def test_fastapi_template() -> None:
    got = find_python_surfaces(TEMPLATE, source_root="backend")
    kinds = {s.kind for s in got}
    assert {"settings-class", "validator", "consumer", "pool-config"} <= kinds
    assert all(len(s.excerpt.splitlines()) <= 40 for s in got)
    assert any(s.file == "backend/app/core/config.py" and s.kind == "settings-class" for s in got)


def test_inherited_input_models(tmp_path: Path) -> None:
    src = (
        "from sqlmodel import SQLModel\n"
        "class WindowBase(SQLModel):\n    start: int\n    end: int\n"
        "class WindowCreate(WindowBase):\n    pass\n"
        "class WindowUpdate(WindowBase):\n    note: str\n"
        "class Window(WindowBase, table=True):\n    id: int\n"
        "class WindowPublic(WindowBase):\n    id: int\n"
    )
    f = tmp_path / "m.py"
    f.write_text(src)
    got = {s.symbol for s in scan_file(f, "m.py") if s.kind == "validator"}
    assert got == {"WindowBase", "WindowCreate", "WindowUpdate"}


def test_late_pool_field_stays_in_excerpt(tmp_path: Path) -> None:
    fields = "\n".join(f"    F{i}: int = {i}" for i in range(80))
    src = f"from pydantic_settings import BaseSettings\nclass Big(BaseSettings):\n{fields}\n    LATE_TIMEOUT: int = 9\n"
    f = tmp_path / "big.py"
    f.write_text(src)
    (s,) = [s for s in scan_file(f, "big.py") if s.symbol == "Big.LATE_TIMEOUT"]
    lines = s.excerpt.splitlines()
    assert len(lines) == 40 and lines[0].startswith("class Big") and "LATE_TIMEOUT: int = 9" in s.excerpt


def test_skipped_dirs_not_walked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "x.py").write_text("import os\nos.getenv('A')\n")
    (tmp_path / "app.py").write_text("import os\nos.getenv('A')\n")
    walked: list[str] = []
    real = os.walk

    def spy(top: Path) -> Iterator[tuple[str, list[str], list[str]]]:
        for d, dirs, files in real(top):
            walked.append(d)
            yield d, dirs, files

    monkeypatch.setattr("incidentforge.surfaces.python.os.walk", spy)
    assert [p.name for p in iter_py_files(tmp_path)] == ["app.py"]
    assert not any(".venv" in w for w in walked)
