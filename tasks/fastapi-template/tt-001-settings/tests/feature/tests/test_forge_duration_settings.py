"""duration settings must accept unit suffixes and reject garbage clearly."""

import pytest

from app.core.config import Settings

BASE = {
    "PROJECT_NAME": "forge",
    "SECRET_KEY": "forge-secret-key-for-tests",
    "DATABASE_URL": "postgresql://postgres:forge-pw@localhost:5432/app",
    "FIRST_SUPERUSER": "admin@example.com",
    "FIRST_SUPERUSER_PASSWORD": "forge-superuser-pw",
}
DURATION_VARS = ("ACCESS_TOKEN_EXPIRE_MINUTES", "EMAIL_RESET_TOKEN_EXPIRE_HOURS")


@pytest.fixture(autouse=True)
def _clean_duration_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in DURATION_VARS:
        monkeypatch.delenv(name, raising=False)


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})  # type: ignore[arg-type]


def assert_rejected(name: str, bad: str, **overrides: object) -> None:
    with pytest.raises(ValueError) as exc:
        make(**overrides)
    msg = str(exc.value)
    assert name in msg, f"{name} missing from: {msg}"
    assert bad in msg, f"{bad!r} missing from: {msg}"


def test_defaults_unchanged() -> None:
    s = make()
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 60 * 24 * 8
    assert s.EMAIL_RESET_TOKEN_EXPIRE_HOURS == 48


@pytest.mark.parametrize("value", [90, "90", " 90 "])
def test_canonical_integer_still_works(value: object) -> None:
    s = make(ACCESS_TOKEN_EXPIRE_MINUTES=value, EMAIL_RESET_TOKEN_EXPIRE_HOURS=value)
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 90
    assert s.EMAIL_RESET_TOKEN_EXPIRE_HOURS == 90


def test_canonical_integer_from_env_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440")
    monkeypatch.setenv("EMAIL_RESET_TOKEN_EXPIRE_HOURS", "24")
    s = make()
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 1440
    assert s.EMAIL_RESET_TOKEN_EXPIRE_HOURS == 24


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("30m", 30),
        ("2h", 120),
        ("1d", 1440),
        ("120s", 2),
        ("8D", 11520),
        ("2H", 120),
        (" 45 M ", 45),
        ("0m", 0),
    ],
)
def test_fault_duration_suffix_minutes(raw: str, expected: int) -> None:
    s = make(ACCESS_TOKEN_EXPIRE_MINUTES=raw)
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == expected
    assert type(s.ACCESS_TOKEN_EXPIRE_MINUTES) is int
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == make(
        ACCESS_TOKEN_EXPIRE_MINUTES=expected
    ).ACCESS_TOKEN_EXPIRE_MINUTES


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("48h", 48), ("2d", 48), ("3600s", 1), ("120m", 2), ("1D", 24)],
)
def test_fault_duration_suffix_hours(raw: str, expected: int) -> None:
    s = make(EMAIL_RESET_TOKEN_EXPIRE_HOURS=raw)
    assert s.EMAIL_RESET_TOKEN_EXPIRE_HOURS == expected
    assert type(s.EMAIL_RESET_TOKEN_EXPIRE_HOURS) is int


def test_fault_duration_suffix_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "2h")
    monkeypatch.setenv("EMAIL_RESET_TOKEN_EXPIRE_HOURS", "3d")
    s = make()
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 120
    assert s.EMAIL_RESET_TOKEN_EXPIRE_HOURS == 72


@pytest.mark.parametrize("bad", ["abc", "5x", "1.5h", "30 minutes", "h"])
def test_fault_garbage_minutes(bad: str) -> None:
    assert_rejected("ACCESS_TOKEN_EXPIRE_MINUTES", bad, ACCESS_TOKEN_EXPIRE_MINUTES=bad)


@pytest.mark.parametrize("bad", ["soon", "2w", "1.5d"])
def test_fault_garbage_hours(bad: str) -> None:
    assert_rejected(
        "EMAIL_RESET_TOKEN_EXPIRE_HOURS", bad, EMAIL_RESET_TOKEN_EXPIRE_HOURS=bad
    )


def test_fault_garbage_not_whole_unit() -> None:
    assert_rejected("ACCESS_TOKEN_EXPIRE_MINUTES", "30s", ACCESS_TOKEN_EXPIRE_MINUTES="30s")
    assert_rejected(
        "EMAIL_RESET_TOKEN_EXPIRE_HOURS", "90m", EMAIL_RESET_TOKEN_EXPIRE_HOURS="90m"
    )


def test_fault_garbage_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "forever")
    with pytest.raises(ValueError) as exc:
        make()
    assert "ACCESS_TOKEN_EXPIRE_MINUTES" in str(exc.value)
    assert "forever" in str(exc.value)
