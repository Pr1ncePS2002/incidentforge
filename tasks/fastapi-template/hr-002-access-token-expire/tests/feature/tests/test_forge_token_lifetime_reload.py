"""runtime reload of token lifetimes: next read sees new values, bad reloads keep the last good pair."""

import base64
import json
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, settings
from app.core.runtime_config import get_token_lifetimes, reload_token_lifetimes

ACCESS = "ACCESS_TOKEN_EXPIRE_MINUTES"
RESET = "EMAIL_RESET_TOKEN_EXPIRE_HOURS"
DEFAULT_ACCESS = 60 * 24 * 8
DEFAULT_RESET = 48

BASE = {
    "PROJECT_NAME": "forge",
    "SECRET_KEY": "forge-secret-key-for-tests",
    "DATABASE_URL": "postgresql://postgres:forge-pw@localhost:5432/app",
    "FIRST_SUPERUSER": "admin@example.com",
    "FIRST_SUPERUSER_PASSWORD": "forge-superuser-pw",
}


@pytest.fixture(autouse=True)
def _restore_lifetimes() -> Iterator[None]:
    access = settings.ACCESS_TOKEN_EXPIRE_MINUTES
    reset = settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS
    yield
    settings.ACCESS_TOKEN_EXPIRE_MINUTES = access
    settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS = reset


def _claims(token: str) -> dict:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def _current() -> tuple[int, int]:
    lt = get_token_lifetimes()
    return (lt.access_token_expire_minutes, lt.email_reset_token_expire_hours)


def test_defaults_unchanged_without_reload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ACCESS, raising=False)
    monkeypatch.delenv(RESET, raising=False)
    s = Settings(_env_file=None, **BASE)  # type: ignore[arg-type]
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == DEFAULT_ACCESS
    assert s.EMAIL_RESET_TOKEN_EXPIRE_HOURS == DEFAULT_RESET


def test_accessor_matches_settings_without_reload() -> None:
    assert _current() == (
        settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS,
    )


def test_reload_takes_effect_on_next_read() -> None:
    result = reload_token_lifetimes({ACCESS: "30", RESET: 2})
    assert tuple(result) == (30, 2)
    assert _current() == (30, 2)
    assert settings.ACCESS_TOKEN_EXPIRE_MINUTES == 30
    assert settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS == 2


def test_reload_ignores_unrelated_keys() -> None:
    reload_token_lifetimes({ACCESS: 15, RESET: "3", "PROJECT_NAME": "other"})
    assert _current() == (15, 3)


def test_fault_stale_capture_login_issues_token_with_reloaded_lifetime(
    client: TestClient,
) -> None:
    reload_token_lifetimes({ACCESS: "5", RESET: "48"})
    before = int(time.time())
    r = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={
            "username": settings.FIRST_SUPERUSER,
            "password": settings.FIRST_SUPERUSER_PASSWORD,
        },
    )
    after = int(time.time()) + 1
    assert r.status_code == 200, r.text
    exp = _claims(r.json()["access_token"])["exp"]
    assert before + 5 * 60 - 1 <= exp <= after + 5 * 60 + 1


@pytest.mark.parametrize("bad", ["abc", "0", "-5", "1.5", 0, -1, True, 2.5])
def test_fault_invalid_reload_keeps_last_good(bad: object) -> None:
    reload_token_lifetimes({ACCESS: 30, RESET: 2})
    with pytest.raises(ValueError) as exc:
        reload_token_lifetimes({ACCESS: bad, RESET: 2})
    assert ACCESS in str(exc.value)
    assert _current() == (30, 2)
    assert settings.ACCESS_TOKEN_EXPIRE_MINUTES == 30


def test_fault_invalid_reload_names_every_key() -> None:
    reload_token_lifetimes({ACCESS: 30, RESET: 2})
    with pytest.raises(ValueError) as exc:
        reload_token_lifetimes({ACCESS: "zero", RESET: "-1"})
    assert ACCESS in str(exc.value)
    assert RESET in str(exc.value)
    assert _current() == (30, 2)


def test_fault_partial_reload_never_mixes_new_and_old() -> None:
    reload_token_lifetimes({ACCESS: 30, RESET: 2})
    with pytest.raises(ValueError) as exc:
        reload_token_lifetimes({ACCESS: "45", RESET: "nope"})
    assert RESET in str(exc.value)
    assert _current() == (30, 2)
    assert settings.ACCESS_TOKEN_EXPIRE_MINUTES == 30
    assert settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS == 2


def test_fault_partial_reload_other_direction() -> None:
    reload_token_lifetimes({ACCESS: 30, RESET: 2})
    with pytest.raises(ValueError):
        reload_token_lifetimes({ACCESS: "-3", RESET: "7"})
    assert _current() == (30, 2)


def test_fault_reload_unset_missing_keys_fall_back_to_defaults() -> None:
    reload_token_lifetimes({ACCESS: 30, RESET: 2})
    result = reload_token_lifetimes({})
    assert tuple(result) == (DEFAULT_ACCESS, DEFAULT_RESET)
    assert _current() == (DEFAULT_ACCESS, DEFAULT_RESET)


def test_fault_reload_unset_blank_or_none_falls_back() -> None:
    reload_token_lifetimes({ACCESS: 30, RESET: 2})
    reload_token_lifetimes({ACCESS: "  ", RESET: None})
    assert _current() == (DEFAULT_ACCESS, DEFAULT_RESET)


def test_fault_reload_unset_one_key_only() -> None:
    reload_token_lifetimes({ACCESS: 30, RESET: 2})
    reload_token_lifetimes({ACCESS: "10"})
    assert _current() == (10, DEFAULT_RESET)
