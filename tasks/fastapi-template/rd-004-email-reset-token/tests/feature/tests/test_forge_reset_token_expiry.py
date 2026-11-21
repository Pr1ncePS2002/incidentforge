"""fault cases for the password-reset token lifetime derived from configured bounds."""

import pytest

from app.core.config import Settings

BASE = {
    "PROJECT_NAME": "forge",
    "SECRET_KEY": "forge-secret-key-for-tests",
    "DATABASE_URL": "postgresql://postgres:forge-pw@localhost:5432/app",
    "FIRST_SUPERUSER": "admin@example.com",
    "FIRST_SUPERUSER_PASSWORD": "forge-superuser-pw",
}
RESET_VARS = (
    "EMAIL_RESET_TOKEN_EXPIRE_HOURS",
    "EMAIL_RESET_TOKEN_MIN_EXPIRE_HOURS",
    "EMAIL_RESET_TOKEN_MAX_EXPIRE_HOURS",
    "ACCESS_TOKEN_EXPIRE_MINUTES",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in RESET_VARS:
        monkeypatch.delenv(name, raising=False)


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})  # type: ignore[arg-type]


def assert_rejected(names: list[str], **overrides: object) -> None:
    with pytest.raises(ValueError) as exc:
        make(**overrides)
    for name in names:
        assert name in str(exc.value), f"{name} missing from: {exc.value}"


# --- unchanged behaviour ---------------------------------------------------


def test_shipped_defaults_still_give_48_hours() -> None:
    s = make()
    assert s.EMAIL_RESET_TOKEN_EXPIRE_HOURS == 48
    assert isinstance(s.EMAIL_RESET_TOKEN_EXPIRE_HOURS, int)


def test_explicit_value_is_used() -> None:
    assert make(EMAIL_RESET_TOKEN_EXPIRE_HOURS=24).EMAIL_RESET_TOKEN_EXPIRE_HOURS == 24


def test_explicit_value_from_env_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAIL_RESET_TOKEN_EXPIRE_HOURS", "72")
    assert make().EMAIL_RESET_TOKEN_EXPIRE_HOURS == 72


def test_explicit_value_on_the_bounds_is_valid() -> None:
    s = make(
        EMAIL_RESET_TOKEN_EXPIRE_HOURS=12,
        EMAIL_RESET_TOKEN_MIN_EXPIRE_HOURS=12,
        EMAIL_RESET_TOKEN_MAX_EXPIRE_HOURS=12,
    )
    assert s.EMAIL_RESET_TOKEN_EXPIRE_HOURS == 12


# --- unset-limit -------------------------------------------------------------


def test_fault_unset_limit_empty_value_is_derived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the key was blanked out by a config change; must derive, not use a constant
    monkeypatch.setenv("EMAIL_RESET_TOKEN_EXPIRE_HOURS", "")
    s = make(ACCESS_TOKEN_EXPIRE_MINUTES=60 * 24 * 2)
    assert s.EMAIL_RESET_TOKEN_EXPIRE_HOURS == 12


def test_fault_unset_limit_missing_value_is_derived() -> None:
    s = make(ACCESS_TOKEN_EXPIRE_MINUTES=60 * 24 * 20)
    assert s.EMAIL_RESET_TOKEN_EXPIRE_HOURS == 120


def test_fault_unset_limit_derived_value_respects_floor() -> None:
    s = make(ACCESS_TOKEN_EXPIRE_MINUTES=60, EMAIL_RESET_TOKEN_MIN_EXPIRE_HOURS=6)
    assert s.EMAIL_RESET_TOKEN_EXPIRE_HOURS == 6


# --- hardcoded-size ----------------------------------------------------------


def test_fault_hardcoded_size_follows_configured_ceiling() -> None:
    s = make(EMAIL_RESET_TOKEN_MAX_EXPIRE_HOURS=24)
    assert s.EMAIL_RESET_TOKEN_EXPIRE_HOURS == 24


def test_fault_hardcoded_size_follows_access_token_lifetime() -> None:
    s = make(ACCESS_TOKEN_EXPIRE_MINUTES=60 * 24 * 4)
    assert s.EMAIL_RESET_TOKEN_EXPIRE_HOURS == 24


# --- min-over-max ------------------------------------------------------------


def test_fault_min_over_max() -> None:
    assert_rejected(
        ["EMAIL_RESET_TOKEN_MIN_EXPIRE_HOURS", "EMAIL_RESET_TOKEN_MAX_EXPIRE_HOURS"],
        EMAIL_RESET_TOKEN_MIN_EXPIRE_HOURS=72,
        EMAIL_RESET_TOKEN_MAX_EXPIRE_HOURS=24,
    )


# --- exceeds-limit -----------------------------------------------------------


def test_fault_exceeds_limit_above_max() -> None:
    assert_rejected(
        ["EMAIL_RESET_TOKEN_EXPIRE_HOURS", "EMAIL_RESET_TOKEN_MAX_EXPIRE_HOURS"],
        EMAIL_RESET_TOKEN_EXPIRE_HOURS=200,
    )


def test_fault_exceeds_limit_below_min() -> None:
    assert_rejected(
        ["EMAIL_RESET_TOKEN_EXPIRE_HOURS", "EMAIL_RESET_TOKEN_MIN_EXPIRE_HOURS"],
        EMAIL_RESET_TOKEN_EXPIRE_HOURS=2,
        EMAIL_RESET_TOKEN_MIN_EXPIRE_HOURS=6,
    )


# --- zero-or-negative --------------------------------------------------------


@pytest.mark.parametrize("hours", [0, -5])
def test_fault_zero_or_negative_expiry(hours: int) -> None:
    assert_rejected(
        ["EMAIL_RESET_TOKEN_EXPIRE_HOURS"], EMAIL_RESET_TOKEN_EXPIRE_HOURS=hours
    )


def test_fault_zero_or_negative_min() -> None:
    assert_rejected(
        ["EMAIL_RESET_TOKEN_MIN_EXPIRE_HOURS"], EMAIL_RESET_TOKEN_MIN_EXPIRE_HOURS=0
    )


def test_fault_zero_or_negative_max() -> None:
    assert_rejected(
        ["EMAIL_RESET_TOKEN_MAX_EXPIRE_HOURS"], EMAIL_RESET_TOKEN_MAX_EXPIRE_HOURS=-1
    )
