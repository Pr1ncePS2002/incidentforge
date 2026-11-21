"""environment-scoped cache/queue names built from FASTAPI_ENV."""

import uuid
from unittest.mock import MagicMock

import pytest

from app import crud
from app.core import config
from app.core import naming
from app.models import UserCreate


def _set_env(monkeypatch: pytest.MonkeyPatch, value: object) -> None:
    monkeypatch.setattr(config.settings, "FASTAPI_ENV", value)


def _user_create() -> UserCreate:
    return UserCreate(email="forge-scoped@example.com", password="forge-pass-123")


def test_development_names_are_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, "development")
    uid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert naming.scoped_name("user", "42") == "development:user:42"
    assert naming.scoped_name("jobs", 7) == "development:jobs:7"
    assert naming.user_cache_key(uid) == f"development:user:{uid}"


def test_all_allowed_environments_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    for env in ("local", "development", "staging", "production"):
        _set_env(monkeypatch, env)
        assert naming.current_environment() == env


def test_create_user_still_works_with_valid_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch, "development")
    session = MagicMock()
    user = crud.create_user(session=session, user_create=_user_create())
    assert user.email == "forge-scoped@example.com"
    assert user.hashed_password != "forge-pass-123"
    session.add.assert_called_once()
    session.commit.assert_called_once()


def test_fault_unscoped_key_differs_per_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = uuid.uuid4()
    _set_env(monkeypatch, "staging")
    staging = naming.user_cache_key(uid)
    _set_env(monkeypatch, "production")
    production = naming.user_cache_key(uid)
    assert staging != production
    assert staging == f"staging:user:{uid}"
    assert production == f"production:user:{uid}"


def test_fault_wrong_env_source_reads_configured_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch, "production")
    assert naming.current_environment() == "production"
    assert naming.scoped_name("queue", "emails") == "production:queue:emails"
    _set_env(monkeypatch, "local")
    assert naming.scoped_name("queue", "emails") == "local:queue:emails"


@pytest.mark.parametrize("bad", ["", "   ", "qa", "Production", "prod", None])
def test_fault_unknown_env_global(monkeypatch: pytest.MonkeyPatch, bad: object) -> None:
    _set_env(monkeypatch, bad)
    with pytest.raises(ValueError) as exc:
        naming.current_environment()
    assert "FASTAPI_ENV" in str(exc.value)
    with pytest.raises(ValueError) as exc2:
        naming.scoped_name("user", "1")
    assert "FASTAPI_ENV" in str(exc2.value)


@pytest.mark.parametrize("bad", ["", "qa"])
def test_fault_unknown_env_blocks_create_user(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    _set_env(monkeypatch, bad)
    session = MagicMock()
    with pytest.raises(ValueError) as exc:
        crud.create_user(session=session, user_create=_user_create())
    assert "FASTAPI_ENV" in str(exc.value)
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_fault_separator_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, "staging")
    # ("a:b", "c") and ("a", "b:c") would both render as staging:a:b:c
    with pytest.raises(ValueError):
        naming.scoped_name("a:b", "c")
    with pytest.raises(ValueError):
        naming.scoped_name("a", "b:c")
    with pytest.raises(ValueError):
        naming.user_cache_key("x:y")
    with pytest.raises(ValueError):
        naming.scoped_name("user", "")
    assert naming.scoped_name("a", "b", "c") == "staging:a:b:c"
