"""API_V1_STR / FRONTEND_HOST must be usable at construction time."""

import pytest

from app.core.config import Settings

BASE = {
    "PROJECT_NAME": "forge",
    "SECRET_KEY": "forge-secret-key-for-tests",
    "DATABASE_URL": "postgresql://postgres:forge-pw@localhost:5432/app",
    "FIRST_SUPERUSER": "admin@example.com",
    "FIRST_SUPERUSER_PASSWORD": "forge-superuser-pw",
}


@pytest.fixture(autouse=True)
def _clean_routing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("API_V1_STR", "FRONTEND_HOST"):
        monkeypatch.delenv(name, raising=False)


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})  # type: ignore[arg-type]


def assert_rejected(names: list[str], **overrides: object) -> None:
    with pytest.raises(ValueError) as exc:
        make(**overrides)
    for name in names:
        assert name in str(exc.value), f"{name} missing from: {exc.value}"


def test_shipped_defaults_still_load() -> None:
    s = make()
    assert s.API_V1_STR == "/api/v1"
    assert s.FRONTEND_HOST == "http://localhost:5173"


def test_custom_valid_values_load() -> None:
    s = make(API_V1_STR="/api/v2", FRONTEND_HOST="https://dashboard.example.com")
    assert s.API_V1_STR == "/api/v2"
    assert s.FRONTEND_HOST == "https://dashboard.example.com"


@pytest.mark.parametrize("value", ["", "   "])
def test_fault_empty_frontend_host(value: str) -> None:
    assert_rejected(["FRONTEND_HOST"], FRONTEND_HOST=value)


@pytest.mark.parametrize("value", ["", "  "])
def test_fault_empty_api_prefix(value: str) -> None:
    assert_rejected(["API_V1_STR"], API_V1_STR=value)


@pytest.mark.parametrize("value", ["changethis", "TODO", "<fill-me>", " fixme "])
def test_fault_placeholder_frontend_host(value: str) -> None:
    assert_rejected(["FRONTEND_HOST"], FRONTEND_HOST=value)


@pytest.mark.parametrize("value", ["changethis", "<fill-me>"])
def test_fault_placeholder_api_prefix(value: str) -> None:
    assert_rejected(["API_V1_STR"], API_V1_STR=value)


@pytest.mark.parametrize("value", ["api/v1", "/api/v1/", "/"])
def test_malformed_api_prefix_rejected(value: str) -> None:
    assert_rejected(["API_V1_STR"], API_V1_STR=value)


@pytest.mark.parametrize("value", ["localhost:5173", "ftp://example.com", "http://"])
def test_malformed_frontend_host_rejected(value: str) -> None:
    assert_rejected(["FRONTEND_HOST"], FRONTEND_HOST=value)


def test_fault_several_bad() -> None:
    assert_rejected(
        ["API_V1_STR", "FRONTEND_HOST"],
        API_V1_STR="api/v1/",
        FRONTEND_HOST="changethis",
    )
