"""Idempotent user deletion: redelivery, retry after partial write, distinct keys."""

import uuid

import pytest
import sqlmodel
from fastapi.testclient import TestClient
from sqlmodel import Session, func, select

from app import crud
from app.core.config import settings
from app.core.db import engine
from app.models import Item, User, UserCreate
from tests.utils.utils import random_email, random_lower_string

OK_BODY = {"message": "User deleted successfully"}


def _url(user_id: uuid.UUID | str) -> str:
    return f"{settings.API_V1_STR}/users/{user_id}"


def _key() -> str:
    return f"forge-{uuid.uuid4()}"


def _user_with_items(db: Session, n_items: int = 2) -> uuid.UUID:
    user = crud.create_user(
        session=db,
        user_create=UserCreate(email=random_email(), password=random_lower_string()),
    )
    for i in range(n_items):
        db.add(Item(title=f"forge-item-{i}", owner_id=user.id))
    db.commit()
    return user.id


def _state(user_id: uuid.UUID) -> tuple[bool, int]:
    with Session(engine) as s:
        exists = s.get(User, user_id) is not None
        n_items = s.exec(
            select(func.count()).select_from(Item).where(Item.owner_id == user_id)
        ).one()
    return exists, n_items


def _delete(
    client: TestClient, headers: dict[str, str], user_id: uuid.UUID, key: str | None
):
    h = dict(headers)
    if key is not None:
        h["Idempotency-Key"] = key
    return client.delete(_url(user_id), headers=h)


def test_delete_without_key_is_unchanged(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    user_id = _user_with_items(db)
    r1 = _delete(client, superuser_token_headers, user_id, None)
    assert r1.status_code == 200
    assert r1.json() == OK_BODY
    assert _state(user_id) == (False, 0)
    r2 = _delete(client, superuser_token_headers, user_id, None)
    assert r2.status_code == 404


def test_blank_key_behaves_like_no_key(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    user_id = _user_with_items(db)
    assert _delete(client, superuser_token_headers, user_id, "   ").status_code == 200
    assert _delete(client, superuser_token_headers, user_id, "   ").status_code == 404


def test_fault_duplicate_delivery(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    bystander = _user_with_items(db, 2)
    user_id = _user_with_items(db, 3)
    key = _key()

    first = _delete(client, superuser_token_headers, user_id, key)
    assert first.status_code == 200
    assert first.json() == OK_BODY
    assert _state(user_id) == (False, 0)

    second = _delete(client, superuser_token_headers, user_id, key)
    assert second.status_code == 200
    assert second.json() == first.json()
    assert _state(user_id) == (False, 0)
    assert _state(bystander) == (True, 2)


def test_fault_duplicate_delivery_many_repeats(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    user_id = _user_with_items(db, 1)
    key = _key()
    bodies = []
    for _ in range(4):
        r = _delete(client, superuser_token_headers, user_id, key)
        assert r.status_code == 200
        bodies.append(r.json())
    assert all(b == OK_BODY for b in bodies)
    assert _state(user_id) == (False, 0)


def test_fault_retry_after_partial_write(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = _user_with_items(db, 3)
    key = _key()

    original_delete = sqlmodel.Session.delete
    calls = {"n": 0}

    def flaky_delete(self, instance):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            # items were already deleted in this transaction; crash before the user goes
            raise RuntimeError("simulated crash after partial write")
        return original_delete(self, instance)

    monkeypatch.setattr(sqlmodel.Session, "delete", flaky_delete)

    with pytest.raises(RuntimeError):
        _delete(client, superuser_token_headers, user_id, key)
    # partial work rolled back
    assert _state(user_id) == (True, 3)

    retry = _delete(client, superuser_token_headers, user_id, key)
    assert retry.status_code == 200
    assert retry.json() == OK_BODY
    assert _state(user_id) == (False, 0)

    again = _delete(client, superuser_token_headers, user_id, key)
    assert again.status_code == 200
    assert again.json() == OK_BODY
    assert _state(user_id) == (False, 0)


def test_fault_distinct_events(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    a = _user_with_items(db, 2)
    b = _user_with_items(db, 2)
    key_a, key_b = _key(), _key()

    assert _delete(client, superuser_token_headers, a, key_a).status_code == 200
    assert _state(b) == (True, 2)
    assert _delete(client, superuser_token_headers, b, key_b).status_code == 200
    assert _state(a) == (False, 0)
    assert _state(b) == (False, 0)

    ra = _delete(client, superuser_token_headers, a, key_a)
    rb = _delete(client, superuser_token_headers, b, key_b)
    assert (ra.status_code, rb.status_code) == (200, 200)
    assert ra.json() == OK_BODY and rb.json() == OK_BODY


def test_key_reused_for_other_user_is_rejected(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    a = _user_with_items(db, 1)
    b = _user_with_items(db, 2)
    key = _key()
    assert _delete(client, superuser_token_headers, a, key).status_code == 200
    r = _delete(client, superuser_token_headers, b, key)
    assert r.status_code == 409
    assert _state(b) == (True, 2)


def test_failed_attempt_is_not_recorded(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    key = _key()
    missing = uuid.uuid4()
    assert _delete(client, superuser_token_headers, missing, key).status_code == 404
    assert _delete(client, superuser_token_headers, missing, key).status_code == 404

    user_id = _user_with_items(db, 1)
    r = _delete(client, superuser_token_headers, user_id, key)
    assert r.status_code == 200
    assert _state(user_id) == (False, 0)


def test_self_delete_with_key_still_forbidden(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    me = client.get(
        f"{settings.API_V1_STR}/users/me", headers=superuser_token_headers
    ).json()
    key = _key()
    for _ in range(2):
        r = _delete(client, superuser_token_headers, me["id"], key)
        assert r.status_code == 403
