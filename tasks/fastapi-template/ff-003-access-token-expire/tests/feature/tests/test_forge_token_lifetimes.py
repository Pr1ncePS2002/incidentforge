"""token lifetime settings must be usable or the service must refuse to start."""

import pytest

from app.core.config import Settings

BASE = {
    "PROJECT_NAME": "forge",
    "SECRET_KEY": "forge-secret-key-for-tests",
    "DATABASE_URL": "postgresql://postgres:forge-pw@localhost:5432/app",
    "FIRST_SUPERUSER": "admin@example.com",
    "FIRST_SUPERUSER_PASSWORD": "forge-superuser-pw",
}
LIFETIME_VARS = ("ACCESS_TOKEN_EXPIRE_MINUTES", "EMAIL_RESET_TOKEN_EXPIRE_HOURS")


@pytest.fixture(autouse=True)
def _clean_lifetime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in LIFETIME_VARS:
        monkeypatch.delenv(name, raising=False)


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})  # type: ignore[arg-type]


def rejected(**overrides: object) -> str:
    with pytest.raises(ValueError) as exc:
        make(**overrides)
    return str(exc.value)


# --- unchanged behaviour ---


def test_shipped_defaults_still_load() -> None:
    s = make()
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 60 * 24 * 8
    assert s.EMAIL_RESET_TOKEN_EXPIRE_HOURS == 48


@pytest.mark.parametrize("minutes", [1, 15, 60 * 24 * 365])
def test_valid_access_lifetime_loads(minutes: int) -> None:
    assert make(ACCESS_TOKEN_EXPIRE_MINUTES=minutes).ACCESS_TOKEN_EXPIRE_MINUTES == minutes


@pytest.mark.parametrize("hours", [1, 24, 24 * 365])
def test_valid_reset_lifetime_loads(hours: int) -> None:
    assert make(EMAIL_RESET_TOKEN_EXPIRE_HOURS=hours).EMAIL_RESET_TOKEN_EXPIRE_HOURS == hours


def test_numeric_strings_from_env_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "120")
    monkeypatch.setenv("EMAIL_RESET_TOKEN_EXPIRE_HOURS", "12")
    s = make()
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 120
    assert s.EMAIL_RESET_TOKEN_EXPIRE_HOURS == 12


def test_empty_env_var_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "")
    assert make().ACCESS_TOKEN_EXPIRE_MINUTES == 60 * 24 * 8


# --- out of range ---


@pytest.mark.parametrize("minutes", [0, -1, 60 * 24 * 365 + 1, 99999999999])
def test_out_of_range_access_lifetime_rejected(minutes: int) -> None:
    assert "ACCESS_TOKEN_EXPIRE_MINUTES" in rejected(ACCESS_TOKEN_EXPIRE_MINUTES=minutes)


@pytest.mark.parametrize("hours", [0, -3, 24 * 365 + 1])
def test_out_of_range_reset_lifetime_rejected(hours: int) -> None:
    assert "EMAIL_RESET_TOKEN_EXPIRE_HOURS" in rejected(EMAIL_RESET_TOKEN_EXPIRE_HOURS=hours)


# --- injected faults ---


@pytest.mark.parametrize("value", ["   ", "\t", " \n "])
def test_fault_empty_access_lifetime(value: str) -> None:
    msg = rejected(ACCESS_TOKEN_EXPIRE_MINUTES=value)
    assert "ACCESS_TOKEN_EXPIRE_MINUTES" in msg
    assert "blank" in msg.lower()


def test_fault_empty_reset_lifetime_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAIL_RESET_TOKEN_EXPIRE_HOURS", "   ")
    with pytest.raises(ValueError) as exc:
        make()
    msg = str(exc.value)
    assert "EMAIL_RESET_TOKEN_EXPIRE_HOURS" in msg
    assert "blank" in msg.lower()


@pytest.mark.parametrize("value", ["changethis", "TODO", "<fill-me>", " changeme ", "<minutes>"])
def test_fault_placeholder_access_lifetime(value: str) -> None:
    msg = rejected(ACCESS_TOKEN_EXPIRE_MINUTES=value)
    assert "ACCESS_TOKEN_EXPIRE_MINUTES" in msg
    assert "placeholder" in msg.lower()


def test_fault_placeholder_reset_lifetime_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAIL_RESET_TOKEN_EXPIRE_HOURS", "fixme")
    with pytest.raises(ValueError) as exc:
        make()
    msg = str(exc.value)
    assert "EMAIL_RESET_TOKEN_EXPIRE_HOURS" in msg
    assert "placeholder" in msg.lower()


def test_fault_several_bad_out_of_range() -> None:
    msg = rejected(ACCESS_TOKEN_EXPIRE_MINUTES=0, EMAIL_RESET_TOKEN_EXPIRE_HOURS=-5)
    assert "ACCESS_TOKEN_EXPIRE_MINUTES" in msg
    assert "EMAIL_RESET_TOKEN_EXPIRE_HOURS" in msg


def test_fault_several_bad_mixed() -> None:
    msg = rejected(ACCESS_TOKEN_EXPIRE_MINUTES="changethis", EMAIL_RESET_TOKEN_EXPIRE_HOURS=0)
    assert "ACCESS_TOKEN_EXPIRE_MINUTES" in msg
    assert "EMAIL_RESET_TOKEN_EXPIRE_HOURS" in msg
    assert "placeholder" in msg.lower()
