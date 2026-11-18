"""impossible user account states must be rejected when the data is validated."""

import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import settings
from app.models import UserBase, UserCreate

PW = "forge-password-123"


def _email() -> str:
    return f"forge-{uuid.uuid4().hex[:12]}@example.com"


def assert_rejected(names: list[str], factory, **kwargs) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationError) as exc:
        factory(**kwargs)
    msg = str(exc.value)
    for name in names:
        assert name in msg, f"{name} missing from: {msg}"


def test_defaults_still_validate() -> None:
    u = UserCreate(email=_email(), password=PW)
    assert u.is_active is True
    assert u.is_superuser is False
    assert u.full_name is None


def test_active_superuser_is_valid() -> None:
    u = UserCreate(email=_email(), password=PW, is_superuser=True, is_active=True)
    assert u.is_superuser is True


def test_inactive_regular_user_is_valid() -> None:
    u = UserBase(email=_email(), is_active=False, is_superuser=False)
    assert u.is_active is False


def test_one_char_and_max_length_full_name_are_valid() -> None:
    assert UserBase(email=_email(), full_name="A").full_name == "A"
    long_name = "x" * 255
    assert UserCreate(email=_email(), password=PW, full_name=long_name).full_name == long_name


def test_fault_mutually_exclusive_disabled_superuser_on_base() -> None:
    assert_rejected(
        ["is_superuser", "is_active"],
        UserBase,
        email=_email(),
        is_superuser=True,
        is_active=False,
    )


def test_fault_mutually_exclusive_disabled_superuser_on_create() -> None:
    assert_rejected(
        ["is_superuser", "is_active"],
        UserCreate,
        email=_email(),
        password=PW,
        is_superuser=True,
        is_active=False,
    )


def test_fault_negative_or_zero_empty_full_name() -> None:
    assert_rejected(["full_name"], UserCreate, email=_email(), password=PW, full_name="")


@pytest.mark.parametrize("blank", [" ", "   ", "\t\n"])
def test_fault_boundary_equal_whitespace_only_full_name(blank: str) -> None:
    assert_rejected(["full_name"], UserBase, email=_email(), full_name=blank)


def test_fault_mutually_exclusive_and_blank_name_reported_together() -> None:
    assert_rejected(
        ["is_superuser", "is_active", "full_name"],
        UserCreate,
        email=_email(),
        password=PW,
        is_superuser=True,
        is_active=False,
        full_name="  ",
    )


def test_fault_mutually_exclusive_api_rejects_disabled_superuser(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    email = _email()
    r = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=superuser_token_headers,
        json={
            "email": email,
            "password": PW,
            "is_superuser": True,
            "is_active": False,
        },
    )
    assert r.status_code == 422, r.text


def test_api_still_creates_inactive_regular_user(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    email = _email()
    r = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=superuser_token_headers,
        json={"email": email, "password": PW, "is_active": False},
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False
