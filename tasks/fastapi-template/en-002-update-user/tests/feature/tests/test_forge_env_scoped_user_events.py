"""user change events must use names scoped by the configured FASTAPI_ENV."""

from typing import Any

import pytest

from app import crud
from app.core import config
from app.models import User, UserUpdate


def _naming() -> Any:
    from app.core import naming

    return naming


def _broker() -> Any:
    from app.core import broker

    return broker


class FakeSession:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.commits = 0
        self.refreshed: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, obj: Any) -> None:
        self.refreshed.append(obj)


def _set_env(monkeypatch: pytest.MonkeyPatch, value: Any) -> None:
    monkeypatch.setattr(config.settings, "FASTAPI_ENV", value)


@pytest.fixture(autouse=True)
def _clear_published() -> Any:
    try:
        from app.core import broker
    except ImportError:
        yield
        return
    broker.published.clear()
    yield
    broker.published.clear()


def _user() -> User:
    return User(email="forge-scoped@example.com", hashed_password="not-a-real-hash", full_name="Old Name")


def _update(name: str = "New Name") -> tuple[User, FakeSession, Any]:
    user = _user()
    session = FakeSession()
    result = crud.update_user(session=session, db_user=user, user_in=UserUpdate(full_name=name))  # type: ignore[arg-type]
    return user, session, result


def test_development_names_are_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, "development")
    naming = _naming()
    assert naming.scoped_name("users", "updated") == "development:users:updated"
    assert naming.scoped_name("user", "42") == "development:user:42"


def test_shipped_default_environment_is_accepted() -> None:
    naming = _naming()
    env = config.settings.FASTAPI_ENV
    assert naming.scoped_name("user", "1") == f"{env}:user:1"


def test_update_user_publishes_development_names(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, "development")
    user, session, result = _update()
    assert result is user
    assert user.full_name == "New Name"
    assert session.commits == 1
    assert list(_broker().published) == [
        ("development:users:updated", f"development:user:{user.id}")
    ]


def test_fault_unscoped_key_differs_per_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    naming = _naming()
    names = {}
    for env in ("development", "staging", "production"):
        _set_env(monkeypatch, env)
        names[env] = naming.scoped_name("user", "42")
        assert names[env] == f"{env}:user:42"
    assert len(set(names.values())) == 3


def test_fault_unscoped_key_update_user(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, "staging")
    user, _, _ = _update()
    assert list(_broker().published) == [
        ("staging:users:updated", f"staging:user:{user.id}")
    ]


def test_fault_wrong_env_source(monkeypatch: pytest.MonkeyPatch) -> None:
    naming = _naming()
    _set_env(monkeypatch, "production")
    assert naming.scoped_name("users", "updated") == "production:users:updated"
    _set_env(monkeypatch, "staging")
    assert naming.scoped_name("users", "updated") == "staging:users:updated"


def test_fault_wrong_env_source_update_user(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, "production")
    user, _, _ = _update()
    topic, key = list(_broker().published)[0]
    assert topic == "production:users:updated"
    assert key == f"production:user:{user.id}"


@pytest.mark.parametrize(
    "env", ["", "qa", "dev", "Production", " production", "staging:x", None]
)
def test_fault_unknown_env(monkeypatch: pytest.MonkeyPatch, env: Any) -> None:
    naming = _naming()
    _set_env(monkeypatch, env)
    with pytest.raises(ValueError) as exc:
        naming.scoped_name("user", "42")
    assert "FASTAPI_ENV" in str(exc.value)


def test_fault_unknown_env_update_user_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, "qa")
    user = _user()
    session = FakeSession()
    with pytest.raises(ValueError) as exc:
        crud.update_user(session=session, db_user=user, user_in=UserUpdate(full_name="Changed"))  # type: ignore[arg-type]
    assert "FASTAPI_ENV" in str(exc.value)
    assert user.full_name == "Old Name"
    assert session.added == []
    assert session.commits == 0
    assert list(_broker().published) == []


@pytest.mark.parametrize(
    "parts",
    [("a:b", "c"), ("a", "b:c"), ("user", "1:2"), (":",), ("user", "")],
)
def test_fault_separator_injection(monkeypatch: pytest.MonkeyPatch, parts: tuple[str, ...]) -> None:
    naming = _naming()
    _set_env(monkeypatch, "development")
    with pytest.raises(ValueError):
        naming.scoped_name(*parts)


def test_fault_separator_injection_no_collision(monkeypatch: pytest.MonkeyPatch) -> None:
    naming = _naming()
    _set_env(monkeypatch, "development")
    produced = []
    for parts in (("a:b", "c"), ("a", "b:c")):
        try:
            produced.append(naming.scoped_name(*parts))
        except ValueError:
            pass
    assert len(produced) == len(set(produced))
    assert produced == []
