"""fault cases for create_item being applied more than once for the same request."""

import uuid

import pytest
from sqlmodel import Session, func, select

from app import crud
from app.core.db import engine
from app.models import Item, ItemCreate
from tests.utils.user import create_random_user


def count_items(owner_id: uuid.UUID) -> int:
    with Session(engine) as s:
        return int(
            s.exec(
                select(func.count()).select_from(Item).where(Item.owner_id == owner_id)
            ).one()
        )


def new_owner(db: Session) -> uuid.UUID:
    return create_random_user(db).id


def test_without_key_every_call_still_creates(db: Session) -> None:
    owner_id = new_owner(db)
    item_in = ItemCreate(title="plain", description="no key")
    with Session(engine) as s:
        a = crud.create_item(session=s, item_in=item_in, owner_id=owner_id)
        b = crud.create_item(session=s, item_in=item_in, owner_id=owner_id)
        assert a.id != b.id
    assert count_items(owner_id) == 2


def test_fault_duplicate_delivery_same_session(db: Session) -> None:
    owner_id = new_owner(db)
    item_in = ItemCreate(title="once", description="dup")
    with Session(engine) as s:
        first = crud.create_item(
            session=s, item_in=item_in, owner_id=owner_id, idempotency_key="evt-1"
        )
        second = crud.create_item(
            session=s, item_in=item_in, owner_id=owner_id, idempotency_key="evt-1"
        )
        assert second.id == first.id
        assert second.title == "once"
        assert second.description == "dup"
        assert second.owner_id == owner_id
    assert count_items(owner_id) == 1


def test_fault_duplicate_delivery_new_session_returns_original(db: Session) -> None:
    owner_id = new_owner(db)
    with Session(engine) as s1:
        first = crud.create_item(
            session=s1,
            item_in=ItemCreate(title="original", description="v1"),
            owner_id=owner_id,
            idempotency_key="evt-2",
        )
        first_id = first.id
    with Session(engine) as s2:
        again = crud.create_item(
            session=s2,
            item_in=ItemCreate(title="changed", description="v2"),
            owner_id=owner_id,
            idempotency_key="evt-2",
        )
        assert again.id == first_id
        assert again.title == "original"
        assert again.description == "v1"
    assert count_items(owner_id) == 1


def test_fault_retry_after_partial_commit_then_crash(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_id = new_owner(db)
    item_in = ItemCreate(title="partial", description="lost ack")
    with Session(engine) as s1:
        real_commit = s1.commit

        def commit_then_drop() -> None:
            real_commit()
            raise RuntimeError("connection dropped after commit")

        monkeypatch.setattr(s1, "commit", commit_then_drop)
        with pytest.raises(RuntimeError):
            crud.create_item(
                session=s1, item_in=item_in, owner_id=owner_id, idempotency_key="evt-3"
            )
    assert count_items(owner_id) == 1
    with Session(engine) as s2:
        retried = crud.create_item(
            session=s2, item_in=item_in, owner_id=owner_id, idempotency_key="evt-3"
        )
        assert retried.title == "partial"
        assert retried.owner_id == owner_id
    assert count_items(owner_id) == 1


def test_fault_retry_after_partial_failure_before_persist(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_id = new_owner(db)
    item_in = ItemCreate(title="retry", description="first failed")
    with Session(engine) as s1:

        def fail_commit() -> None:
            raise RuntimeError("database went away")

        monkeypatch.setattr(s1, "commit", fail_commit)
        with pytest.raises(RuntimeError):
            crud.create_item(
                session=s1, item_in=item_in, owner_id=owner_id, idempotency_key="evt-4"
            )
        s1.rollback()
    assert count_items(owner_id) == 0
    with Session(engine) as s2:
        a = crud.create_item(
            session=s2, item_in=item_in, owner_id=owner_id, idempotency_key="evt-4"
        )
        b = crud.create_item(
            session=s2, item_in=item_in, owner_id=owner_id, idempotency_key="evt-4"
        )
        assert a.id == b.id
    assert count_items(owner_id) == 1


def test_fault_back_to_back_duplicate(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_id = new_owner(db)
    item_in = ItemCreate(title="race", description="concurrent")
    with Session(engine) as first, Session(engine) as second:
        real_commit = first.commit
        racer: dict[str, Item] = {}

        def commit_after_racing_duplicate() -> None:
            # the duplicate delivery runs and commits after the first delivery has
            # already checked for an existing item but before it commits
            if "item" not in racer:
                racer["item"] = crud.create_item(
                    session=second,
                    item_in=item_in,
                    owner_id=owner_id,
                    idempotency_key="evt-5",
                )
            real_commit()

        monkeypatch.setattr(first, "commit", commit_after_racing_duplicate)
        result = crud.create_item(
            session=first, item_in=item_in, owner_id=owner_id, idempotency_key="evt-5"
        )
        assert "item" in racer
        assert result.id == racer["item"].id
        assert result.title == "race"
    assert count_items(owner_id) == 1


def test_fault_distinct_events_both_apply(db: Session) -> None:
    owner_id = new_owner(db)
    item_in = ItemCreate(title="same payload", description="x")
    with Session(engine) as s:
        a = crud.create_item(
            session=s, item_in=item_in, owner_id=owner_id, idempotency_key="evt-a"
        )
        b = crud.create_item(
            session=s, item_in=item_in, owner_id=owner_id, idempotency_key="evt-b"
        )
        assert a.id != b.id
    assert count_items(owner_id) == 2


def test_fault_distinct_events_same_key_different_owners(db: Session) -> None:
    owner_a = new_owner(db)
    owner_b = new_owner(db)
    item_in = ItemCreate(title="shared key", description="y")
    with Session(engine) as s:
        a = crud.create_item(
            session=s, item_in=item_in, owner_id=owner_a, idempotency_key="evt-shared"
        )
        b = crud.create_item(
            session=s, item_in=item_in, owner_id=owner_b, idempotency_key="evt-shared"
        )
        assert a.id != b.id
        assert a.owner_id == owner_a
        assert b.owner_id == owner_b
    assert count_items(owner_a) == 1
    assert count_items(owner_b) == 1


@pytest.mark.parametrize("key", ["", "   "])
def test_blank_key_is_rejected(db: Session, key: str) -> None:
    owner_id = new_owner(db)
    with Session(engine) as s:
        with pytest.raises(ValueError):
            crud.create_item(
                session=s,
                item_in=ItemCreate(title="blank"),
                owner_id=owner_id,
                idempotency_key=key,
            )
    assert count_items(owner_id) == 0
