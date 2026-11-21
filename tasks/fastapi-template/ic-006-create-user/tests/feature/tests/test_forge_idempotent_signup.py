"""user creation keyed on the normalized email must apply once per key."""

import uuid
from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy import delete
from sqlmodel import Session, func, select

from app import crud
from app.core.db import engine
from app.models import User, UserCreate

PASSWORD = "forge-pw-1234"
OTHER_PASSWORD = "forge-other-pw-5678"


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    with Session(engine) as s:
        yield s
        s.rollback()
    with Session(engine) as cleanup:
        cleanup.execute(
            delete(User).where(func.lower(User.email).like("forge-idem-%"))
        )
        cleanup.commit()


def new_email() -> str:
    return f"forge-idem-{uuid.uuid4().hex[:12]}@example.com"


def rows(session: Session, email: str) -> int:
    stmt = (
        select(func.count())
        .select_from(User)
        .where(func.lower(User.email) == email.lower())
    )
    return int(session.exec(stmt).one())


def make(email: str, password: str = PASSWORD, full_name: str = "First") -> UserCreate:
    return UserCreate(email=email, password=password, full_name=full_name)


def test_fault_duplicate_delivery_returns_original(session: Session) -> None:
    email = new_email()
    first = crud.create_user(session=session, user_create=make(email))
    second = crud.create_user(session=session, user_create=make(email))
    assert second.id == first.id
    assert rows(session, email) == 1


def test_fault_duplicate_delivery_mixed_case_email(session: Session) -> None:
    email = new_email()
    first = crud.create_user(session=session, user_create=make(email))
    second = crud.create_user(session=session, user_create=make(email.upper()))
    assert second.id == first.id
    assert rows(session, email) == 1


def test_fault_duplicate_delivery_keeps_original_fields(session: Session) -> None:
    email = new_email()
    first = crud.create_user(session=session, user_create=make(email))
    second = crud.create_user(
        session=session, user_create=make(email, full_name="Changed")
    )
    assert second.id == first.id
    assert second.full_name == "First"
    session.expire_all()
    stored = session.exec(select(User).where(User.id == first.id)).one()
    assert stored.full_name == "First"
    assert rows(session, email) == 1


def test_fault_duplicate_delivery_conflicting_password_rejected(
    session: Session,
) -> None:
    email = new_email()
    crud.create_user(session=session, user_create=make(email))
    with pytest.raises(ValueError) as exc:
        crud.create_user(
            session=session, user_create=make(email, password=OTHER_PASSWORD)
        )
    assert email not in str(exc.value)
    assert rows(session, email) == 1
    assert crud.authenticate(session=session, email=email, password=PASSWORD)


def test_fault_retry_after_partial_write(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = new_email()
    real_refresh = session.refresh
    state = {"calls": 0}

    def crash_once(instance: Any, *args: Any, **kwargs: Any) -> None:
        if state["calls"] == 0:
            state["calls"] += 1
            raise RuntimeError("worker crashed after commit")
        real_refresh(instance, *args, **kwargs)

    monkeypatch.setattr(session, "refresh", crash_once)
    with pytest.raises(RuntimeError):
        crud.create_user(session=session, user_create=make(email))
    retried = crud.create_user(session=session, user_create=make(email))
    assert retried.email == email
    assert rows(session, email) == 1


def test_fault_distinct_events_both_apply(session: Session) -> None:
    a, b = new_email(), new_email()
    user_a = crud.create_user(session=session, user_create=make(a))
    user_b = crud.create_user(session=session, user_create=make(b))
    again_a = crud.create_user(session=session, user_create=make(a))
    assert user_a.id != user_b.id
    assert again_a.id == user_a.id
    assert rows(session, a) == 1
    assert rows(session, b) == 1


def test_new_user_email_is_stored_normalized(session: Session) -> None:
    email = new_email()
    user = crud.create_user(session=session, user_create=make(email.upper()))
    assert user.email == email


def test_lookup_by_email_ignores_case(session: Session) -> None:
    email = new_email()
    user = crud.create_user(session=session, user_create=make(email))
    found = crud.get_user_by_email(session=session, email=email.upper())
    assert found is not None and found.id == user.id
    assert crud.get_user_by_email(session=session, email=new_email()) is None
