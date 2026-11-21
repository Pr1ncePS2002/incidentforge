"""fault cases for unauthenticated or half-configured database settings."""

import pytest

from app.core.config import Settings

GOOD_URL = "postgresql+psycopg://postgres:forge-db-pw@localhost:5432/app"
BASE = {
    "PROJECT_NAME": "forge",
    "SECRET_KEY": "forge-secret-key-for-tests",
    "DATABASE_URL": GOOD_URL,
    "FIRST_SUPERUSER": "admin@example.com",
    "FIRST_SUPERUSER_PASSWORD": "forge-superuser-pw",
}
SSL_VARS = ("DATABASE_SSL_ENABLED", "DATABASE_SSL_ROOT_CERT")


@pytest.fixture(autouse=True)
def _clean_ssl_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in SSL_VARS:
        monkeypatch.delenv(name, raising=False)


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})  # type: ignore[arg-type]


def assert_rejected(names: list[str], **overrides: object) -> None:
    with pytest.raises(ValueError) as exc:
        make(**overrides)
    for name in names:
        assert name in str(exc.value), f"{name} missing from: {exc.value}"


def test_valid_config_still_loads() -> None:
    s = make()
    assert s.DATABASE_SSL_ENABLED is False
    assert s.DATABASE_SSL_ROOT_CERT is None


def test_ssl_with_root_cert_loads() -> None:
    s = make(DATABASE_SSL_ENABLED=True, DATABASE_SSL_ROOT_CERT="/etc/ssl/db-root.crt")
    assert s.DATABASE_SSL_ENABLED is True
    assert s.DATABASE_SSL_ROOT_CERT == "/etc/ssl/db-root.crt"


def test_root_cert_not_checked_when_ssl_off() -> None:
    s = make(DATABASE_SSL_ENABLED=False, DATABASE_SSL_ROOT_CERT="")
    assert s.DATABASE_SSL_ENABLED is False


def test_ssl_flag_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_SSL_ENABLED", "true")
    monkeypatch.setenv("DATABASE_SSL_ROOT_CERT", "/etc/ssl/db-root.crt")
    s = make()
    assert s.DATABASE_SSL_ENABLED is True


def test_fault_missing_database_password() -> None:
    assert_rejected(
        ["DATABASE_URL"],
        DATABASE_URL="postgresql+psycopg://postgres@localhost:5432/app",
    )


def test_fault_missing_database_user_and_password() -> None:
    assert_rejected(
        ["DATABASE_URL"],
        DATABASE_URL="postgresql+psycopg://localhost:5432/app",
    )


def test_fault_empty_database_password() -> None:
    assert_rejected(
        ["DATABASE_URL"],
        DATABASE_URL="postgresql+psycopg://postgres:@localhost:5432/app",
    )


def test_fault_empty_whitespace_database_password() -> None:
    assert_rejected(
        ["DATABASE_URL"],
        DATABASE_URL="postgresql+psycopg://postgres:%20%20@localhost:5432/app",
    )


def test_fault_conditional_missing_root_cert() -> None:
    assert_rejected(["DATABASE_SSL_ROOT_CERT"], DATABASE_SSL_ENABLED=True)


def test_fault_conditional_missing_root_cert_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_SSL_ENABLED", "true")
    assert_rejected(["DATABASE_SSL_ROOT_CERT"])


@pytest.mark.parametrize("value", ["", "   "])
def test_fault_empty_root_cert(value: str) -> None:
    assert_rejected(
        ["DATABASE_SSL_ROOT_CERT"],
        DATABASE_SSL_ENABLED=True,
        DATABASE_SSL_ROOT_CERT=value,
    )


@pytest.mark.parametrize("value", ["changethis", "TODO", "<fill-me>"])
def test_fault_placeholder_root_cert(value: str) -> None:
    assert_rejected(
        ["DATABASE_SSL_ROOT_CERT"],
        DATABASE_SSL_ENABLED=True,
        DATABASE_SSL_ROOT_CERT=value,
    )


def test_fault_several_bad() -> None:
    assert_rejected(
        ["DATABASE_URL", "DATABASE_SSL_ROOT_CERT"],
        DATABASE_URL="postgresql+psycopg://postgres@localhost:5432/app",
        DATABASE_SSL_ENABLED=True,
    )
