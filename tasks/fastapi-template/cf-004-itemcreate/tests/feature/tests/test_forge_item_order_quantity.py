"""fault cases for impossible order-quantity limits on item creation."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import settings
from app.models import ItemCreate

MIN = "min_order_quantity"
MAX = "max_order_quantity"


def test_item_without_order_limits_still_valid() -> None:
    item = ItemCreate(title="Widget", description="plain")
    assert item.min_order_quantity is None
    assert item.max_order_quantity is None


def test_item_with_ordered_limits_is_valid() -> None:
    item = ItemCreate(title="Widget", min_order_quantity=1, max_order_quantity=10)
    assert (item.min_order_quantity, item.max_order_quantity) == (1, 10)


@pytest.mark.parametrize("field", [MIN, MAX])
def test_single_limit_is_valid(field: str) -> None:
    item = ItemCreate(title="Widget", **{field: 3})
    assert getattr(item, field) == 3


def test_fault_inverted_range() -> None:
    with pytest.raises(ValidationError) as exc:
        ItemCreate(title="Widget", min_order_quantity=5, max_order_quantity=3)
    msg = str(exc.value)
    assert MIN in msg and MAX in msg, msg


def test_fault_boundary_equal_is_allowed() -> None:
    item = ItemCreate(title="Widget", min_order_quantity=4, max_order_quantity=4)
    assert item.min_order_quantity == 4
    assert item.max_order_quantity == 4


def test_fault_boundary_equal_off_by_one_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        ItemCreate(title="Widget", min_order_quantity=5, max_order_quantity=4)
    msg = str(exc.value)
    assert MIN in msg and MAX in msg, msg


@pytest.mark.parametrize("field", [MIN, MAX])
@pytest.mark.parametrize("value", [0, -1, -100])
def test_fault_negative_or_zero(field: str, value: int) -> None:
    with pytest.raises(ValidationError) as exc:
        ItemCreate(title="Widget", **{field: value})
    assert field in str(exc.value), str(exc.value)


def test_fault_inverted_range_rejected_by_api(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/items/",
        headers=superuser_token_headers,
        json={"title": "Widget", MIN: 9, MAX: 2},
    )
    assert r.status_code == 422, r.text
    assert MIN in r.text and MAX in r.text, r.text


def test_api_accepts_equal_limits(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/items/",
        headers=superuser_token_headers,
        json={"title": "Widget", MIN: 2, MAX: 2},
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Widget"
