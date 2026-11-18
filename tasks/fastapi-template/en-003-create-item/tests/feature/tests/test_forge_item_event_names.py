"""environment-scoped item event names."""

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app import crud
from app.models import ItemCreate


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def add(self, obj: Any) -> None:
        self.calls.append("add")

    def commit(self) -> None:
        self.calls.append("commit")

    def refresh(self, obj: Any) -> None:
        self.calls.append("refresh")


@pytest.fixture()
def ns(monkeypatch: pytest.MonkeyPatch) -> Any:
    from app.core import events, namespacing

    monkeypatch.delenv("DEPLOYMENT_ENV", raising=False)
    monkeypatch.setattr(events, "OUTBOX", [])
    return namespacing


def _use_env(monkeypatch: pytest.MonkeyPatch, ns: Any, env: str) -> None:
    monkeypatch.setattr(
        ns, "namespace_settings", ns.NamespaceSettings(_env_file=None, DEPLOYMENT_ENV=env)
    )


def _create(session: FakeSession) -> Any:
    owner = uuid.uuid4()
    item = crud.create_item(
        session=session,  # type: ignore[arg-type]
        item_in=ItemCreate(title="forge item"),
        owner_id=owner,
    )
    return item, owner


def _outbox() -> list[tuple[str, dict[str, Any]]]:
    from app.core import events

    return events.OUTBOX


def test_default_environment_name_is_stable(ns: Any) -> None:
    s = ns.NamespaceSettings(_env_file=None)
    assert s.DEPLOYMENT_ENV == "local"
    assert ns.scoped_name("items", "created", "abc", settings=s) == "local:items:created:abc"


def test_create_item_publishes_local_event(monkeypatch: pytest.MonkeyPatch, ns: Any) -> None:
    _use_env(monkeypatch, ns, "local")
    session = FakeSession()
    item, owner = _create(session)
    assert item.title == "forge item"
    assert item.owner_id == owner
    assert session.calls == ["add", "commit", "refresh"]
    assert _outbox() == [
        (
            f"local:items:created:{item.id}",
            {"item_id": str(item.id), "owner_id": str(owner)},
        )
    ]


def test_fault_unscoped_key(monkeypatch: pytest.MonkeyPatch, ns: Any) -> None:
    staging = SimpleNamespace(DEPLOYMENT_ENV="staging")
    prod = SimpleNamespace(DEPLOYMENT_ENV="production")
    a = ns.scoped_name("items", "created", "42", settings=staging)
    b = ns.scoped_name("items", "created", "42", settings=prod)
    assert a != b
    assert a == "staging:items:created:42"
    assert b == "production:items:created:42"

    _use_env(monkeypatch, ns, "production")
    item, _ = _create(FakeSession())
    assert _outbox()[-1][0] == f"production:items:created:{item.id}"


def test_fault_wrong_env_source(monkeypatch: pytest.MonkeyPatch, ns: Any) -> None:
    monkeypatch.setenv("DEPLOYMENT_ENV", "staging")
    s = ns.NamespaceSettings(_env_file=None)
    assert s.DEPLOYMENT_ENV == "staging"
    monkeypatch.setattr(ns, "namespace_settings", s)
    assert ns.scoped_name("items", "x") == "staging:items:x"
    item, _ = _create(FakeSession())
    assert _outbox()[-1][0] == f"staging:items:created:{item.id}"


@pytest.mark.parametrize("bad", ["", "qa", "Production", " staging", "local:items"])
def test_fault_unknown_env_settings(ns: Any, bad: str) -> None:
    with pytest.raises(ValueError) as exc:
        ns.NamespaceSettings(_env_file=None, DEPLOYMENT_ENV=bad)
    assert "DEPLOYMENT_ENV" in str(exc.value)


@pytest.mark.parametrize("bad", ["", "qa", "dev", None])
def test_fault_unknown_env_helper(ns: Any, bad: Any) -> None:
    with pytest.raises(ValueError) as exc:
        ns.scoped_name("items", "created", "1", settings=SimpleNamespace(DEPLOYMENT_ENV=bad))
    assert "DEPLOYMENT_ENV" in str(exc.value)


def test_fault_unknown_env_create_item_fails_before_write(
    monkeypatch: pytest.MonkeyPatch, ns: Any
) -> None:
    monkeypatch.setattr(ns, "namespace_settings", SimpleNamespace(DEPLOYMENT_ENV="qa"))
    session = FakeSession()
    with pytest.raises(ValueError) as exc:
        _create(session)
    assert "DEPLOYMENT_ENV" in str(exc.value)
    assert session.calls == []
    assert _outbox() == []


def test_fault_separator_injection(ns: Any) -> None:
    s = SimpleNamespace(DEPLOYMENT_ENV="local")
    with pytest.raises(ValueError):
        ns.scoped_name("a:b", "c", settings=s)
    with pytest.raises(ValueError):
        ns.scoped_name("a", "b:c", settings=s)
    with pytest.raises(ValueError):
        ns.scoped_name("a", "", settings=s)
    assert ns.scoped_name("a", "b", "c", settings=s) == "local:a:b:c"
