"""access token lifetime must be derived from / bounded by its configured ceiling."""

import pytest

from app.core.config import Settings

BASE = {
    "PROJECT_NAME": "forge",
    "SECRET_KEY": "forge-secret-key-for-tests",
    "DATABASE_URL": "postgresql://postgres:forge-pw@localhost:5432/app",
    "FIRST_SUPERUSER": "admin@example.com",
    "FIRST_SUPERUSER_PASSWORD": "forge-superuser-pw",
}
DEFAULT_MINUTES = 60 * 24 * 8


@pytest.fixture(autouse=True)
def _clean_token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ACCESS_TOKEN_EXPIRE_MINUTES", "ACCESS_TOKEN_MAX_EXPIRE_MINUTES"):
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
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == DEFAULT_MINUTES
    assert s.ACCESS_TOKEN_MAX_EXPIRE_MINUTES is None


def test_explicit_lifetime_without_ceiling_is_kept() -> None:
    assert make(ACCESS_TOKEN_EXPIRE_MINUTES=30).ACCESS_TOKEN_EXPIRE_MINUTES == 30


def test_explicit_lifetime_within_ceiling_is_kept() -> None:
    s = make(ACCESS_TOKEN_EXPIRE_MINUTES=30, ACCESS_TOKEN_MAX_EXPIRE_MINUTES=60)
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 30


def test_explicit_lifetime_equal_to_ceiling_is_kept() -> None:
    s = make(ACCESS_TOKEN_EXPIRE_MINUTES=60, ACCESS_TOKEN_MAX_EXPIRE_MINUTES=60)
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 60


def test_large_ceiling_keeps_default_lifetime() -> None:
    s = make(ACCESS_TOKEN_MAX_EXPIRE_MINUTES=DEFAULT_MINUTES * 4)
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == DEFAULT_MINUTES


def test_fault_hardcoded_size_default_follows_ceiling() -> None:
    # lifetime not configured: must be derived min(default, ceiling), not fixed 11520
    s = make(ACCESS_TOKEN_MAX_EXPIRE_MINUTES=90)
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 90


def test_fault_hardcoded_size_default_follows_ceiling_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACCESS_TOKEN_MAX_EXPIRE_MINUTES", "45")
    assert make().ACCESS_TOKEN_EXPIRE_MINUTES == 45


def test_fault_unset_limit_uses_documented_default() -> None:
    s = make(ACCESS_TOKEN_EXPIRE_MINUTES=DEFAULT_MINUTES * 10)
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == DEFAULT_MINUTES * 10
    assert make().ACCESS_TOKEN_EXPIRE_MINUTES == DEFAULT_MINUTES


def test_fault_exceeds_limit_explicit_lifetime_over_ceiling() -> None:
    assert_rejected(
        ["ACCESS_TOKEN_EXPIRE_MINUTES", "ACCESS_TOKEN_MAX_EXPIRE_MINUTES"],
        ACCESS_TOKEN_EXPIRE_MINUTES=120,
        ACCESS_TOKEN_MAX_EXPIRE_MINUTES=60,
    )


def test_fault_exceeds_limit_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "120")
    monkeypatch.setenv("ACCESS_TOKEN_MAX_EXPIRE_MINUTES", "60")
    with pytest.raises(ValueError) as exc:
        make()
    assert "ACCESS_TOKEN_EXPIRE_MINUTES" in str(exc.value)
    assert "ACCESS_TOKEN_MAX_EXPIRE_MINUTES" in str(exc.value)


@pytest.mark.parametrize("minutes", [0, -1, -60])
def test_fault_zero_or_negative_lifetime(minutes: int) -> None:
    assert_rejected(["ACCESS_TOKEN_EXPIRE_MINUTES"], ACCESS_TOKEN_EXPIRE_MINUTES=minutes)


@pytest.mark.parametrize("maximum", [0, -5])
def test_fault_zero_or_negative_ceiling(maximum: int) -> None:
    assert_rejected(
        ["ACCESS_TOKEN_MAX_EXPIRE_MINUTES"], ACCESS_TOKEN_MAX_EXPIRE_MINUTES=maximum
    )
