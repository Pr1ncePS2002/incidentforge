"""impossible option combinations on PrivateUserCreate must be rejected at validation time."""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.routes.private import PrivateUserCreate
from app.core.config import settings
from tests.utils.utils import random_email, random_lower_string

START = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
END = START + timedelta(days=30)


def base(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "email": "seed@example.com",
        "password": "seed-password-123",
        "full_name": "Seed User",
    }
    data.update(overrides)
    return data


def assert_rejected(names: list[str], **overrides: Any) -> None:
    with pytest.raises(ValidationError) as exc:
        PrivateUserCreate(**base(**overrides))
    msg = str(exc.value)
    for name in names:
        assert name in msg, f"{name} missing from: {msg}"


def test_defaults_still_validate() -> None:
    m = PrivateUserCreate(**base())
    assert m.is_verified is False
    assert m.send_verification_email is False
    assert m.valid_from is None and m.valid_until is None


def test_ordered_window_is_valid() -> None:
    m = PrivateUserCreate(**base(valid_from=START, valid_until=END))
    assert m.valid_from == START and m.valid_until == END


def test_one_sided_window_is_valid() -> None:
    assert PrivateUserCreate(**base(valid_from=END)).valid_until is None
    assert PrivateUserCreate(**base(valid_until=START)).valid_from is None


def test_naive_and_aware_ordered_window_is_valid() -> None:
    naive_start = datetime(2026, 1, 1, 0, 0)
    aware_end = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    m = PrivateUserCreate(**base(valid_from=naive_start, valid_until=aware_end))
    assert m.valid_until == aware_end


def test_each_flag_alone_is_valid() -> None:
    assert PrivateUserCreate(**base(is_verified=True)).is_verified is True
    assert (
        PrivateUserCreate(**base(send_verification_email=True)).send_verification_email
        is True
    )


def test_fault_inverted_range_window() -> None:
    assert_rejected(["valid_from", "valid_until"], valid_from=END, valid_until=START)


def test_fault_inverted_range_naive_vs_aware() -> None:
    naive_start = datetime(2026, 1, 2, 0, 0)
    aware_end = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert_rejected(
        ["valid_from", "valid_until"], valid_from=naive_start, valid_until=aware_end
    )


def test_fault_boundary_equal_window_rejected() -> None:
    assert_rejected(["valid_from", "valid_until"], valid_from=START, valid_until=START)


def test_fault_boundary_equal_across_timezones() -> None:
    other_tz = START.astimezone(timezone(timedelta(hours=5, minutes=30)))
    assert_rejected(
        ["valid_from", "valid_until"], valid_from=START, valid_until=other_tz
    )


def test_just_after_boundary_is_valid() -> None:
    m = PrivateUserCreate(
        **base(valid_from=START, valid_until=START + timedelta(microseconds=1))
    )
    assert m.valid_until is not None


def test_fault_mutually_exclusive_verified_and_send_email() -> None:
    assert_rejected(
        ["is_verified", "send_verification_email"],
        is_verified=True,
        send_verification_email=True,
    )


def test_fault_inverted_range_and_mutually_exclusive_reported_together() -> None:
    assert_rejected(
        ["valid_from", "valid_until", "is_verified", "send_verification_email"],
        valid_from=END,
        valid_until=START,
        is_verified=True,
        send_verification_email=True,
    )


def test_fault_inverted_range_endpoint_returns_422(client: TestClient) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/private/users/",
        json=base(
            email=random_email(),
            valid_from=END.isoformat(),
            valid_until=START.isoformat(),
        ),
    )
    assert r.status_code == 422
    body = str(r.json())
    assert "valid_from" in body and "valid_until" in body


def test_fault_mutually_exclusive_endpoint_returns_422(client: TestClient) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/private/users/",
        json=base(
            email=random_email(), is_verified=True, send_verification_email=True
        ),
    )
    assert r.status_code == 422
    body = str(r.json())
    assert "is_verified" in body and "send_verification_email" in body


def test_endpoint_accepts_valid_window(client: TestClient) -> None:
    email = random_email()
    r = client.post(
        f"{settings.API_V1_STR}/private/users/",
        json=base(
            email=email,
            password=random_lower_string(),
            valid_from=START.isoformat(),
            valid_until=END.isoformat(),
            send_verification_email=True,
        ),
    )
    assert r.status_code == 200
    assert r.json()["email"] == email
