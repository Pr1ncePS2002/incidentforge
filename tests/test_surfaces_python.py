"""python surface finder on a tiny fixture package and, when present, the fastapi-template clone."""

from pathlib import Path

import pytest

from incidentforge.models import Language
from incidentforge.surfaces import find_surfaces
from incidentforge.surfaces.python import find_python_surfaces, scan_file

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
        ("env-read", cfg, "<module>"),
        ("validator", mod, "WindowCreate"),
        ("validator", mod, "WindowCreate._order"),
        ("consumer", h, "create_item"),
        ("consumer", h, "handle_order_event"),
        ("consumer", h, "Worker.on_message"),
        ("consumer", "backend/app/crud.py", "create_user"),
        ("env-read", h, "handle_order_event"),
        ("cache-key", h, "build_cache_key"),
        ("config-writer", h, "save_config"),
        ("pool-config", h, "create_engine"),
    }
    assert expected <= got


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
