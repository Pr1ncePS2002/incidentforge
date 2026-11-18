"""fault cases for create_user being redelivered / retried."""

import uuid
from typing import Any

import pytest
from sqlmodel import Session, select

from app import crud
from app.core.db import engine
from app.core.security import get_password_hash
from app.models import User, UserCreate

PASSWORD = "forge-pw-12345"


def _email() -> str:
    return f"forge-{uuid.uuid4().hex}@example.com"


def _payload(email: str, **kw: Any) -> UserCreate:
    data: dict[str, Any] = {"email": email, "password": PASSWORD}
    data.update(kw)
    return UserCreate(**data)


def _rows(email: str) -> list[User]:
    with Session(engine) as s:
        return list(s.exec(select(User).where(User.email == email)).all())


def test_fault_duplicate_delivery_same_session() -> None:
    email = _email()
    with Session(engine) as session:
        first = crud.create_user(
            session=session, user_create=_payload(email, full_name="Forge")
        )
        first_id = first.id
        second = crud.create_user(
            session=session, user_create=_payload(email, full_name="Forge")
        )
        assert second.id == first_id
    rows = _rows(email)
    assert len(rows) == 1
    assert rows[0].id == first_id
    assert rows[0].full_name == "Forge"


def test_fault_duplicate_delivery_new_session() -> None:
    email = _email()
    with Session(engine) as session:
        first_id = crud.create_user(session=session, user_create=_payload(email)).id
    with Session(engine) as session:
        second_id = crud.create_user(session=session, user_create=_payload(email)).id
    assert second_id == first_id
    assert len(_rows(email)) == 1


def test_fault_retry_after_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    email = _email()
    with Session(engine) as session:
        real_refresh = session.refresh
        calls = {"n": 0}

        def flaky_refresh(obj: Any, *args: Any, **kwargs: Any) -> Any:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("connection lost after commit")
            return real_refresh(obj, *args, **kwargs)

        monkeypatch.setattr(session, "refresh", flaky_refresh)
        with pytest.raises(RuntimeError):
            crud.create_user(session=session, user_create=_payload(email))
    # the first attempt did commit before failing
    assert len(_rows(email)) == 1
    with Session(engine) as session:
        retried_id = crud.create_user(session=session, user_create=_payload(email)).id
    rows = _rows(email)
    assert len(rows) == 1
    assert rows[0].id == retried_id


def test_fault_back_to_back_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    email = _email()
    payload = _payload(email, full_name="Racer")
    real_get = crud.get_user_by_email
    state: dict[str, Any] = {"raced": False, "winner_id": None}

    def racing_get(*, session: Session, email: str) -> User | None:
        if not state["raced"]:
            state["raced"] = True
            # the other delivery commits right after our existence check
            with Session(engine) as other:
                winner = User.model_validate(
                    payload,
                    update={"hashed_password": get_password_hash(PASSWORD)},
                )
                other.add(winner)
                other.commit()
                state["winner_id"] = winner.id
            return None
        return real_get(session=session, email=email)

    monkeypatch.setattr(crud, "get_user_by_email", racing_get)
    with Session(engine) as session:
        result = crud.create_user(session=session, user_create=payload)
        result_id = result.id
    assert state["raced"], "create_user must look the user up via crud.get_user_by_email"
    assert result_id == state["winner_id"]
    rows = _rows(email)
    assert len(rows) == 1
    # and a further redelivery still replays
    monkeypatch.setattr(crud, "get_user_by_email", real_get)
    with Session(engine) as session:
        again_id = crud.create_user(session=session, user_create=payload).id
    assert again_id == state["winner_id"]
    assert len(_rows(email)) == 1


def test_fault_distinct_events() -> None:
    email_a, email_b = _email(), _email()
    with Session(engine) as session:
        a = crud.create_user(session=session, user_create=_payload(email_a, full_name="Same"))
        a_id = a.id
        b = crud.create_user(session=session, user_create=_payload(email_b, full_name="Same"))
        b_id = b.id
        # replays of both still map to their own rows
        assert crud.create_user(
            session=session, user_create=_payload(email_a, full_name="Same")
        ).id == a_id
        assert crud.create_user(
            session=session, user_create=_payload(email_b, full_name="Same")
        ).id == b_id
    assert a_id != b_id
    assert len(_rows(email_a)) == 1
    assert len(_rows(email_b)) == 1


def test_same_email_with_different_details_is_rejected() -> None:
    email = _email()
    with Session(engine) as session:
        original_id = crud.create_user(
            session=session, user_create=_payload(email, full_name="Original")
        ).id
    with Session(engine) as session:
        with pytest.raises(ValueError) as exc:
            crud.create_user(
                session=session, user_create=_payload(email, full_name="Changed")
            )
        assert email not in str(exc.value)
    with Session(engine) as session:
        with pytest.raises(ValueError):
            crud.create_user(
                session=session,
                user_create=UserCreate(
                    email=email, password="another-pw-999", full_name="Original"
                ),
            )
    with Session(engine) as session:
        with pytest.raises(ValueError):
            crud.create_user(
                session=session,
                user_create=_payload(email, full_name="Original", is_superuser=True),
            )
    rows = _rows(email)
    assert len(rows) == 1
    assert rows[0].id == original_id
    assert rows[0].full_name == "Original"
    assert rows[0].is_superuser is False


def test_single_create_still_works() -> None:
    email = _email()
    with Session(engine) as session:
        user = crud.create_user(session=session, user_create=_payload(email))
        assert user.email == email
        assert user.hashed_password != PASSWORD
    assert len(_rows(email)) == 1
