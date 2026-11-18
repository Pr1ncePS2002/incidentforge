"""fault cases for redelivered / retried user updates."""

import uuid
from typing import Any

import pytest
from sqlmodel import Session

from app import crud
from app.models import User, UserCreate, UserUpdate
from tests.utils.utils import random_email, random_lower_string


def _new_user(db: Session) -> User:
    return crud.create_user(
        session=db,
        user_create=UserCreate(email=random_email(), password=random_lower_string()),
    )


def _key() -> str:
    return f"req-{uuid.uuid4()}"


def test_update_without_key_still_applies_every_time(db: Session) -> None:
    user = _new_user(db)
    crud.update_user(session=db, db_user=user, user_in=UserUpdate(full_name="One"))
    crud.update_user(session=db, db_user=user, user_in=UserUpdate(full_name="Two"))
    db.refresh(user)
    assert user.full_name == "Two"
    first_hash = user.hashed_password
    pw = random_lower_string()
    crud.update_user(session=db, db_user=user, user_in=UserUpdate(password=pw))
    db.refresh(user)
    assert user.hashed_password != first_hash


def test_first_keyed_update_applies(db: Session) -> None:
    user = _new_user(db)
    out = crud.update_user(
        session=db,
        db_user=user,
        user_in=UserUpdate(full_name="Keyed"),
        idempotency_key=_key(),
    )
    assert out.id == user.id
    db.refresh(user)
    assert user.full_name == "Keyed"


def test_fault_duplicate_delivery_password_not_rehashed(db: Session) -> None:
    user = _new_user(db)
    key = _key()
    pw = random_lower_string()
    payload = UserUpdate(full_name="First", password=pw)
    first = crud.update_user(
        session=db, db_user=user, user_in=payload, idempotency_key=key
    )
    assert first.id == user.id
    db.refresh(user)
    applied_hash = user.hashed_password

    second = crud.update_user(
        session=db,
        db_user=user,
        user_in=UserUpdate(full_name="First", password=pw),
        idempotency_key=key,
    )
    assert second is not None
    assert second.id == user.id
    assert second.full_name == "First"
    db.refresh(user)
    assert user.hashed_password == applied_hash
    assert user.full_name == "First"
    assert crud.authenticate(session=db, email=user.email, password=pw) is not None


def test_fault_duplicate_delivery_does_not_revert_later_update(db: Session) -> None:
    user = _new_user(db)
    key_a = _key()
    key_b = _key()
    crud.update_user(
        session=db, db_user=user, user_in=UserUpdate(full_name="A"), idempotency_key=key_a
    )
    crud.update_user(
        session=db, db_user=user, user_in=UserUpdate(full_name="B"), idempotency_key=key_b
    )
    replay = crud.update_user(
        session=db, db_user=user, user_in=UserUpdate(full_name="A"), idempotency_key=key_a
    )
    assert replay.id == user.id
    assert replay.full_name == "B"
    db.refresh(user)
    assert user.full_name == "B"


def test_fault_retry_after_partial_write(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _new_user(db)
    original_name = user.full_name
    original_hash = user.hashed_password
    key = _key()
    pw = random_lower_string()

    real_commit = db.commit
    calls = {"n": 0}

    def flaky_commit(*args: Any, **kwargs: Any) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            db.flush()  # the write reached the database transaction
            raise RuntimeError("connection lost during commit")
        real_commit(*args, **kwargs)

    monkeypatch.setattr(db, "commit", flaky_commit)

    with pytest.raises(RuntimeError):
        crud.update_user(
            session=db,
            db_user=user,
            user_in=UserUpdate(full_name="Retried", password=pw),
            idempotency_key=key,
        )
    db.refresh(user)
    assert user.full_name == original_name
    assert user.hashed_password == original_hash

    out = crud.update_user(
        session=db,
        db_user=user,
        user_in=UserUpdate(full_name="Retried", password=pw),
        idempotency_key=key,
    )
    assert out.id == user.id
    db.refresh(user)
    assert user.full_name == "Retried"
    applied_hash = user.hashed_password
    assert applied_hash != original_hash

    crud.update_user(
        session=db,
        db_user=user,
        user_in=UserUpdate(full_name="Retried", password=pw),
        idempotency_key=key,
    )
    db.refresh(user)
    assert user.hashed_password == applied_hash
    monkeypatch.undo()
    assert crud.authenticate(session=db, email=user.email, password=pw) is not None


def test_fault_distinct_events_same_user_both_apply(db: Session) -> None:
    user = _new_user(db)
    pw = random_lower_string()
    crud.update_user(
        session=db, db_user=user, user_in=UserUpdate(full_name="One"), idempotency_key=_key()
    )
    crud.update_user(
        session=db, db_user=user, user_in=UserUpdate(password=pw), idempotency_key=_key()
    )
    db.refresh(user)
    assert user.full_name == "One"
    assert crud.authenticate(session=db, email=user.email, password=pw) is not None


def test_fault_distinct_events_same_key_different_users(db: Session) -> None:
    key = _key()
    alice = _new_user(db)
    bob = _new_user(db)
    crud.update_user(
        session=db, db_user=alice, user_in=UserUpdate(full_name="Alice"), idempotency_key=key
    )
    crud.update_user(
        session=db, db_user=bob, user_in=UserUpdate(full_name="Bob"), idempotency_key=key
    )
    db.refresh(alice)
    db.refresh(bob)
    assert alice.full_name == "Alice"
    assert bob.full_name == "Bob"
