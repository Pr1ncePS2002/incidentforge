"""UserCreate must reject passwords derived from the account's own email or name."""

import pytest
from pydantic import ValidationError

from app.models import UserCreate, UserRegister


def _messages(exc: pytest.ExceptionInfo[ValidationError]) -> str:
    return " ".join(str(e["msg"]) for e in exc.value.errors())


def _assert_rejected(names: list[str], **fields: object) -> None:
    with pytest.raises(ValidationError) as exc:
        UserCreate(**fields)  # type: ignore[arg-type]
    msg = _messages(exc)
    for name in names:
        assert name in msg, f"{name} missing from: {msg}"


def test_valid_user_still_validates() -> None:
    user = UserCreate(
        email="alice.smith@example.com",
        password="correct-horse-battery",
        full_name="Alice Smith",
    )
    assert user.is_active is True
    assert user.is_superuser is False


def test_valid_user_without_full_name() -> None:
    user = UserCreate(email="nightowl@example.com", password="correct-horse-battery")
    assert user.full_name is None


def test_superuser_payload_still_valid() -> None:
    user = UserCreate(
        email="admin@example.com", password="changethis", is_superuser=True
    )
    assert user.is_superuser is True


def test_two_char_local_part_is_not_checked() -> None:
    user = UserCreate(email="jo@example.com", password="jo-rocks-123")
    assert user.password == "jo-rocks-123"


def test_two_char_full_name_is_not_checked() -> None:
    user = UserCreate(
        email="zed.q@example.com", password="Alpine-pass-9", full_name=" Al "
    )
    assert user.full_name == " Al "


def test_password_length_limit_unchanged() -> None:
    with pytest.raises(ValidationError):
        UserCreate(email="nightowl@example.com", password="short")


def test_fault_dependent_bound_email_local_part() -> None:
    _assert_rejected(
        ["password", "email"],
        email="marigold@example.com",
        password="xxMARIGOLD2024",
    )


def test_fault_dependent_bound_full_name() -> None:
    _assert_rejected(
        ["password", "full_name"],
        email="nightowl@example.com",
        password="i-am-GRACE hopper!",
        full_name="  Grace Hopper ",
    )


def test_fault_dependent_bound_both_reported_in_one_error() -> None:
    _assert_rejected(
        ["password", "email", "full_name"],
        email="orchid@example.com",
        password="orchid-ada byron",
        full_name="Ada Byron",
    )


def test_fault_dependent_bound_signup_payload_conversion() -> None:
    payload = UserRegister(email="marigold@example.com", password="my-marigold-pw")
    with pytest.raises(ValidationError) as exc:
        UserCreate.model_validate(payload)
    msg = _messages(exc)
    assert "password" in msg and "email" in msg


def test_fault_boundary_equal_password_equals_local_part() -> None:
    _assert_rejected(
        ["password", "email"],
        email="Sunflower99@example.com",
        password="sunflower99",
    )


def test_fault_boundary_equal_password_equals_full_name() -> None:
    _assert_rejected(
        ["password", "full_name"],
        email="nightowl@example.com",
        password="margaret",
        full_name="Margaret",
    )


def test_fault_boundary_equal_three_char_local_part_is_checked() -> None:
    _assert_rejected(
        ["password", "email"],
        email="bob@example.com",
        password="xx-BOB-secure",
    )
