"""tiny python and go repos the failure map tests build graphs from."""

import subprocess
from pathlib import Path

from incidentforge.models import Language, Target

PY_FILES = {
    "app/__init__.py": "",
    "app/core/__init__.py": "",
    "app/core/config.py": """import os

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings

DEBUG = os.getenv("DEBUG", "0")


class Settings(BaseSettings):
    SECRET_KEY: str = "changethis"
    DATABASE_URL: str
    DB_POOL_SIZE: int = 5
    PROJECT_NAME: str
    SMTP_HOST: str | None = None

    @field_validator("PROJECT_NAME")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def _smtp(self) -> "Settings":
        if self.SMTP_HOST == "":
            raise ValueError("smtp")
        return self


def worker_count() -> int:
    return int(os.environ["WORKERS"])


settings = Settings()
""",
    "app/core/db.py": """from sqlalchemy import create_engine

from app.core.config import worker_count

engine = create_engine("sqlite://", pool_size=worker_count())


def get_engine() -> object:
    return engine
""",
    "app/crud.py": """from app.core.config import worker_count


def create_user(email: str) -> dict[str, str]:
    worker_count()
    return {"email": email}


def upsert_item(item_id: str) -> dict[str, str]:
    return {"id": item_id, "on_conflict": "skip"}
""",
    "app/api/__init__.py": "",
    "app/api/routes.py": """from app.crud import create_user


def handle_signup(email: str) -> dict[str, str]:
    return create_user(email)


def register(email: str) -> dict[str, str]:
    return handle_signup(email)
""",
    "app/export.py": """import json
from pathlib import Path


def save_config(data: dict[str, str], path: Path) -> None:
    path.write_text(json.dumps(data))
""",
    "tests/__init__.py": "",
    "tests/test_crud.py": """from app.crud import create_user


def test_create_user() -> None:
    assert create_user("a@b.c")["email"] == "a@b.c"
""",
}

GO_FILES = {
    "go.mod": "module example.com/svc\n\ngo 1.22\n",
    "internal/config/options.go": """package config

import (
\t"os"
\t"strconv"
)

type Options struct {
\tPort     int    `env:"PORT" envDefault:"8080"`
\tDBURL    string `env:"DATABASE_URL,required"`
\tMaxConns int    `env:"DB_MAX_CONNS"`
}

type configValue struct {
\trawValue  string
\tvalueType string
\tvalidator func(string) error
}

func NewOptions() map[string]*configValue {
\treturn map[string]*configValue{
\t\t"BASE_URL":  {rawValue: "http://localhost", valueType: "stringType"},
\t\t"POOL_SIZE": {rawValue: "", valueType: "intType", validator: nil},
\t}
}

func Workers() int {
\tn, _ := strconv.Atoi(os.Getenv("WORKERS"))
\treturn n
}

func Home() string {
\tv, _ := os.LookupEnv("HOME")
\treturn v
}
""",
    "internal/config/viper.go": """package config

import "github.com/spf13/viper"

func Load() string {
\tviper.SetDefault("cache.prefix", "svc")
\treturn viper.GetString("cache.prefix") + viper.GetString("region")
}

func Timeout() int {
\treturn viper.GetInt("timeout")
}
""",
    "internal/worker/consumer.go": """package worker

import "example.com/svc/internal/config"

func HandleMessage(body string) int {
\treturn config.Workers() + len(body)
}
""",
    "internal/config/options_test.go": """package config

import "testing"

func TestWorkers(t *testing.T) {
\tif Workers() < 0 {
\t\tt.Fatal("negative")
\t}
}
""",
}


def write_repo(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    # crg lists files with git ls-files, so the fixture is a real repo
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    return root


def py_repo(root: Path) -> Path:
    return write_repo(root, PY_FILES)


def go_repo(root: Path) -> Path:
    return write_repo(root, GO_FILES)


def target(name: str, language: Language, env: Path | None = None) -> Target:
    return Target(
        name=name,
        repo_url="https://example.invalid/x.git",
        commit="0123456789abcdef0123456789abcdef01234567",
        licence="MIT",
        language=language,
        env_template=env or Path("."),
        test_command="run_tests -q tests/" if language is Language.python else "run_tests ./...",
    )
