"""BACKEND_CORS_ORIGINS must load from the spellings operators actually write."""

import pytest

from app.core.config import Settings

BASE = {
    "PROJECT_NAME": "forge",
    "SECRET_KEY": "forge-secret-key-for-tests",
    "DATABASE_URL": "postgresql://postgres:forge-pw@localhost:5432/app",
    "FIRST_SUPERUSER": "admin@example.com",
    "FIRST_SUPERUSER_PASSWORD": "forge-superuser-pw",
    "FRONTEND_HOST": "http://localhost:5173",
}
CANONICAL = [
    "http://localhost:3000",
    "https://app.example.com",
    "https://admin.example.com",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BACKEND_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("FRONTEND_HOST", raising=False)


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})  # type: ignore[arg-type]


def test_canonical_list_still_loads() -> None:
    assert make(BACKEND_CORS_ORIGINS=list(CANONICAL)).BACKEND_CORS_ORIGINS == CANONICAL


def test_default_is_empty_and_frontend_always_allowed() -> None:
    s = make()
    assert s.BACKEND_CORS_ORIGINS == []
    assert s.all_cors_origins == ["http://localhost:5173"]


def test_all_cors_origins_merges_without_duplicates() -> None:
    s = make(
        FRONTEND_HOST="http://localhost:5173/",
        BACKEND_CORS_ORIGINS=["http://localhost:5173/", "https://app.example.com"],
    )
    assert s.all_cors_origins == ["http://localhost:5173", "https://app.example.com"]


def test_fault_csv_list() -> None:
    s = make(
        BACKEND_CORS_ORIGINS="http://localhost:3000, https://app.example.com,https://admin.example.com"
    )
    assert s.BACKEND_CORS_ORIGINS == CANONICAL


def test_fault_csv_list_normalised() -> None:
    s = make(
        BACKEND_CORS_ORIGINS=" http://localhost:3000/ , ,https://app.example.com,https://admin.example.com/,"
    )
    assert s.BACKEND_CORS_ORIGINS == CANONICAL


def test_fault_csv_list_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "BACKEND_CORS_ORIGINS",
        "http://localhost:3000, https://app.example.com,https://admin.example.com",
    )
    s = make()
    assert s.BACKEND_CORS_ORIGINS == CANONICAL
    assert s.all_cors_origins == ["http://localhost:5173", *CANONICAL]


def test_fault_json_list() -> None:
    s = make(
        BACKEND_CORS_ORIGINS='["http://localhost:3000", "https://app.example.com", "https://admin.example.com/"]'
    )
    assert s.BACKEND_CORS_ORIGINS == CANONICAL


def test_fault_json_list_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "BACKEND_CORS_ORIGINS",
        '["http://localhost:3000","https://app.example.com","https://admin.example.com"]',
    )
    assert make().BACKEND_CORS_ORIGINS == CANONICAL


@pytest.mark.parametrize("value", ["", "   ", "[]", " , "])
def test_fault_empty_list(value: str) -> None:
    s = make(BACKEND_CORS_ORIGINS=value)
    assert s.BACKEND_CORS_ORIGINS == []
    assert s.all_cors_origins == ["http://localhost:5173"]


def test_fault_empty_list_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKEND_CORS_ORIGINS", "")
    assert make().BACKEND_CORS_ORIGINS == []


@pytest.mark.parametrize(
    ("value", "bad"),
    [
        ('["http://a.example.com",', '["http://a.example.com",'),
        ("localhost:3000, https://app.example.com", "localhost:3000"),
        ("https://app.example.com,ftp://files.example.com", "ftp://files.example.com"),
        ("[1, 2]", "[1, 2]"),
    ],
)
def test_fault_garbage(value: str, bad: str) -> None:
    with pytest.raises(ValueError) as exc:
        make(BACKEND_CORS_ORIGINS=value)
    msg = str(exc.value)
    assert "BACKEND_CORS_ORIGINS" in msg
    assert bad in msg


def test_fault_garbage_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "BACKEND_CORS_ORIGINS", "https://app.example.com,ftp://files.example.com"
    )
    with pytest.raises(ValueError) as exc:
        make()
    msg = str(exc.value)
    assert "BACKEND_CORS_ORIGINS" in msg
    assert "ftp://files.example.com" in msg
