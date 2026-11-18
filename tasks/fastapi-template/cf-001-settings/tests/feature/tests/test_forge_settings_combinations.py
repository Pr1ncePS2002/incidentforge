"""impossible token-lifetime / smtp transport combinations must fail at startup."""

import pytest

from app.core.config import Settings

BASE = {
    "PROJECT_NAME": "forge",
    "SECRET_KEY": "forge-secret-key-for-tests",
    "DATABASE_URL": "postgresql://postgres:forge-pw@localhost:5432/app",
    "FIRST_SUPERUSER": "admin@example.com",
    "FIRST_SUPERUSER_PASSWORD": "forge-superuser-pw",
}
VARS = (
    "ACCESS_TOKEN_EXPIRE_MINUTES",
    "EMAIL_RESET_TOKEN_EXPIRE_HOURS",
    "SMTP_TLS",
    "SMTP_SSL",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in VARS:
        monkeypatch.delenv(name, raising=False)


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})  # type: ignore[arg-type]


def assert_rejected(names: list[str], **overrides: object) -> None:
    with pytest.raises(ValueError) as exc:
        make(**overrides)
    for name in names:
        assert name in str(exc.value), f"{name} missing from: {exc.value}"


def test_shipped_defaults_still_validate() -> None:
    s = make()
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 60 * 24 * 8
    assert s.EMAIL_RESET_TOKEN_EXPIRE_HOURS == 48
    assert s.SMTP_TLS is True
    assert s.SMTP_SSL is False


def test_ssl_alone_is_valid() -> None:
    s = make(SMTP_TLS=False, SMTP_SSL=True)
    assert s.SMTP_SSL is True and s.SMTP_TLS is False


def test_neither_tls_nor_ssl_is_valid() -> None:
    assert make(SMTP_TLS=False, SMTP_SSL=False).SMTP_TLS is False


def test_reset_shorter_than_session_is_valid() -> None:
    s = make(ACCESS_TOKEN_EXPIRE_MINUTES=180, EMAIL_RESET_TOKEN_EXPIRE_HOURS=1)
    assert s.EMAIL_RESET_TOKEN_EXPIRE_HOURS == 1


@pytest.mark.parametrize("minutes", [0, -1, -60])
def test_fault_negative_or_zero_access_minutes(minutes: int) -> None:
    assert_rejected(["ACCESS_TOKEN_EXPIRE_MINUTES"], ACCESS_TOKEN_EXPIRE_MINUTES=minutes)


@pytest.mark.parametrize("hours", [0, -1, -48])
def test_fault_negative_or_zero_reset_hours(hours: int) -> None:
    assert_rejected(
        ["EMAIL_RESET_TOKEN_EXPIRE_HOURS"], EMAIL_RESET_TOKEN_EXPIRE_HOURS=hours
    )


def test_fault_dependent_bound_reset_outlives_session() -> None:
    assert_rejected(
        ["EMAIL_RESET_TOKEN_EXPIRE_HOURS", "ACCESS_TOKEN_EXPIRE_MINUTES"],
        ACCESS_TOKEN_EXPIRE_MINUTES=60,
        EMAIL_RESET_TOKEN_EXPIRE_HOURS=48,
    )


def test_fault_boundary_equal_allowed_one_minute_short_rejected() -> None:
    s = make(ACCESS_TOKEN_EXPIRE_MINUTES=120, EMAIL_RESET_TOKEN_EXPIRE_HOURS=2)
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 120
    assert_rejected(
        ["EMAIL_RESET_TOKEN_EXPIRE_HOURS", "ACCESS_TOKEN_EXPIRE_MINUTES"],
        ACCESS_TOKEN_EXPIRE_MINUTES=119,
        EMAIL_RESET_TOKEN_EXPIRE_HOURS=2,
    )


def test_fault_mutually_exclusive_tls_and_ssl() -> None:
    assert_rejected(["SMTP_TLS", "SMTP_SSL"], SMTP_TLS=True, SMTP_SSL=True)


def test_fault_negative_or_zero_combined_error_names_every_variable() -> None:
    assert_rejected(
        [
            "ACCESS_TOKEN_EXPIRE_MINUTES",
            "EMAIL_RESET_TOKEN_EXPIRE_HOURS",
            "SMTP_TLS",
            "SMTP_SSL",
        ],
        ACCESS_TOKEN_EXPIRE_MINUTES=0,
        EMAIL_RESET_TOKEN_EXPIRE_HOURS=-1,
        SMTP_TLS=True,
        SMTP_SSL=True,
    )
