"""runtime reload of the password-reset link settings (token lifetime + frontend host)."""

import threading

import pytest

from app.core import config
from app.core.config import Settings

BASE = {
    "PROJECT_NAME": "forge",
    "SECRET_KEY": "forge-secret-key-for-tests",
    "DATABASE_URL": "postgresql://postgres:forge-pw@localhost:5432/app",
    "FIRST_SUPERUSER": "admin@example.com",
    "FIRST_SUPERUSER_PASSWORD": "forge-superuser-pw",
}
DEFAULT_HOURS = 48
DEFAULT_HOST = "http://localhost:5173"
HOURS = "EMAIL_RESET_TOKEN_EXPIRE_HOURS"
HOST = "FRONTEND_HOST"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(HOURS, raising=False)
    monkeypatch.delenv(HOST, raising=False)


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})  # type: ignore[arg-type]


def test_defaults_without_reload_are_unchanged() -> None:
    s = make()
    assert s.EMAIL_RESET_TOKEN_EXPIRE_HOURS == DEFAULT_HOURS
    assert s.FRONTEND_HOST == DEFAULT_HOST
    assert s.get_password_reset_settings() == (DEFAULT_HOURS, DEFAULT_HOST)


def test_startup_values_still_honoured() -> None:
    s = make(EMAIL_RESET_TOKEN_EXPIRE_HOURS=12, FRONTEND_HOST="https://app.example.com")
    assert s.get_password_reset_settings() == (12, "https://app.example.com")


def test_reload_next_read_returns_new_values() -> None:
    s = make()
    s.reload_password_reset_settings({HOURS: 6, HOST: "https://new.example.com"})
    assert s.get_password_reset_settings() == (6, "https://new.example.com")


def test_reload_parses_numeric_string_and_ignores_unknown_keys() -> None:
    s = make()
    s.reload_password_reset_settings(
        {HOURS: " 24 ", HOST: "http://reset.example.com:8080", "SMTP_HOST": "x"}
    )
    hours, host = s.get_password_reset_settings()
    assert hours == 24 and isinstance(hours, int)
    assert host == "http://reset.example.com:8080"


def test_fault_stale_capture_same_object_sees_reload() -> None:
    s = make()
    captured = s  # a reader that grabbed the settings object at import time
    s.reload_password_reset_settings({HOURS: "6", HOST: "https://new.example.com"})
    assert captured.EMAIL_RESET_TOKEN_EXPIRE_HOURS == 6
    assert captured.FRONTEND_HOST == "https://new.example.com"
    assert captured.get_password_reset_settings() == (6, "https://new.example.com")


def test_fault_stale_capture_global_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings as imported_settings

    # record current values so monkeypatch restores them afterwards
    monkeypatch.setattr(config.settings, HOURS, config.settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS)
    monkeypatch.setattr(config.settings, HOST, config.settings.FRONTEND_HOST)
    config.settings.reload_password_reset_settings(
        {HOURS: 3, HOST: "https://ops.example.com"}
    )
    assert imported_settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS == 3
    assert imported_settings.FRONTEND_HOST == "https://ops.example.com"
    assert imported_settings.get_password_reset_settings() == (3, "https://ops.example.com")


@pytest.mark.parametrize("bad", ["0", "-3", "721", "abc", "12.5", True, 3.0, 0, 1000])
def test_fault_invalid_reload_hours(bad: object) -> None:
    s = make()
    s.reload_password_reset_settings({HOURS: 6, HOST: "https://good.example.com"})
    with pytest.raises(ValueError) as exc:
        s.reload_password_reset_settings({HOURS: bad, HOST: "https://good.example.com"})
    assert HOURS in str(exc.value)
    assert s.get_password_reset_settings() == (6, "https://good.example.com")
    assert s.EMAIL_RESET_TOKEN_EXPIRE_HOURS == 6


@pytest.mark.parametrize(
    "bad", ["localhost:5173", "ftp://files.example.com", "http://", "not a url", 42]
)
def test_fault_invalid_reload_frontend_host(bad: object) -> None:
    s = make()
    with pytest.raises(ValueError) as exc:
        s.reload_password_reset_settings({HOURS: 6, HOST: bad})
    assert HOST in str(exc.value)
    assert s.get_password_reset_settings() == (DEFAULT_HOURS, DEFAULT_HOST)


def test_fault_invalid_reload_names_every_key() -> None:
    s = make()
    with pytest.raises(ValueError) as exc:
        s.reload_password_reset_settings({HOURS: "-1", HOST: "localhost"})
    assert HOURS in str(exc.value)
    assert HOST in str(exc.value)


def test_fault_invalid_reload_then_good_reload_applies() -> None:
    s = make()
    with pytest.raises(ValueError):
        s.reload_password_reset_settings({HOURS: "zero"})
    s.reload_password_reset_settings({HOURS: "2", HOST: "https://later.example.com"})
    assert s.get_password_reset_settings() == (2, "https://later.example.com")


def test_fault_partial_reload_bad_host_keeps_old_hours() -> None:
    s = make()
    s.reload_password_reset_settings({HOURS: 6, HOST: "https://a.example.com"})
    with pytest.raises(ValueError):
        s.reload_password_reset_settings({HOURS: 10, HOST: "ftp://b.example.com"})
    assert s.get_password_reset_settings() == (6, "https://a.example.com")
    assert s.EMAIL_RESET_TOKEN_EXPIRE_HOURS == 6
    assert s.FRONTEND_HOST == "https://a.example.com"


def test_fault_partial_reload_bad_hours_keeps_old_host() -> None:
    s = make()
    s.reload_password_reset_settings({HOURS: 6, HOST: "https://a.example.com"})
    with pytest.raises(ValueError):
        s.reload_password_reset_settings({HOURS: 0, HOST: "https://b.example.com"})
    assert s.get_password_reset_settings() == (6, "https://a.example.com")
    assert s.FRONTEND_HOST == "https://a.example.com"


def test_fault_partial_reload_readers_never_see_mixed_pair() -> None:
    s = make()
    pair_a = (1, "https://a.example.com")
    pair_b = (2, "https://b.example.com")
    s.reload_password_reset_settings({HOURS: pair_a[0], HOST: pair_a[1]})
    done = threading.Event()
    seen: set[tuple[int, str]] = set()
    errors: list[BaseException] = []

    def reader() -> None:
        try:
            while not done.is_set():
                seen.add(s.get_password_reset_settings())
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    t = threading.Thread(target=reader)
    t.start()
    try:
        for i in range(3000):
            hours, host = pair_b if i % 2 == 0 else pair_a
            s.reload_password_reset_settings({HOURS: hours, HOST: host})
    finally:
        done.set()
        t.join()
    assert not errors
    assert seen <= {pair_a, pair_b}, f"mixed pair observed: {seen - {pair_a, pair_b}}"


@pytest.mark.parametrize("unset", [{}, {HOURS: None, HOST: None}, {HOURS: "", HOST: "  "}])
def test_fault_reload_unset_falls_back_to_defaults(unset: dict[str, object]) -> None:
    s = make(EMAIL_RESET_TOKEN_EXPIRE_HOURS=12, FRONTEND_HOST="https://start.example.com")
    s.reload_password_reset_settings({HOURS: 6, HOST: "https://a.example.com"})
    s.reload_password_reset_settings(unset)
    assert s.get_password_reset_settings() == (DEFAULT_HOURS, DEFAULT_HOST)
    assert s.EMAIL_RESET_TOKEN_EXPIRE_HOURS == DEFAULT_HOURS
    assert s.FRONTEND_HOST == DEFAULT_HOST


def test_fault_reload_unset_one_key_only() -> None:
    s = make()
    s.reload_password_reset_settings({HOURS: 6, HOST: "https://a.example.com"})
    s.reload_password_reset_settings({HOST: "https://keep.example.com"})
    assert s.get_password_reset_settings() == (DEFAULT_HOURS, "https://keep.example.com")
