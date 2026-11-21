"""Retries and redeliveries of POST /items/ carrying an Idempotency-Key."""

import threading
import uuid
from collections.abc import Generator
from typing import Any

import httpx
from fastapi.testclient import TestClient
from sqlmodel import Session, func, select

from app.api.deps import get_db
from app.core.config import settings
from app.core.db import engine
from app.main import app
from app.models import Item

ITEMS_URL = f"{settings.API_V1_STR}/items/"


def new_title() -> str:
    return f"idem-{uuid.uuid4().hex}"


def new_key() -> str:
    return f"req-{uuid.uuid4().hex}"


def count_items(title: str) -> int:
    with Session(engine) as session:
        return session.exec(
            select(func.count()).select_from(Item).where(Item.title == title)
        ).one()


def post_item(
    client: TestClient,
    headers: dict[str, str],
    title: str,
    key: str | None = None,
    description: str | None = None,
) -> httpx.Response:
    request_headers = dict(headers)
    if key is not None:
        request_headers["Idempotency-Key"] = key
    body: dict[str, Any] = {"title": title}
    if description is not None:
        body["description"] = description
    return client.post(ITEMS_URL, headers=request_headers, json=body)


class CommitLandsThenConnectionDrops(Session):
    def commit(self) -> None:
        super().commit()
        raise ConnectionError("connection dropped after commit")


class ConnectionDropsBeforeCommit(Session):
    def commit(self) -> None:
        self.flush()
        raise ConnectionError("connection dropped before commit")


def post_through_session(
    session_cls: type[Session], headers: dict[str, str], title: str, key: str
) -> httpx.Response:
    def overridden_db() -> Generator[Session, None, None]:
        with session_cls(engine) as session:
            yield session

    app.dependency_overrides[get_db] = overridden_db
    try:
        with TestClient(app, raise_server_exceptions=False) as failing_client:
            return post_item(failing_client, headers, title, key)
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_fault_duplicate_delivery(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    title, key = new_title(), new_key()
    first = post_item(client, superuser_token_headers, title, key, "delivery")
    second = post_item(client, superuser_token_headers, title, key, "delivery")
    third = post_item(client, superuser_token_headers, title, key, "delivery")
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert third.status_code == 200, third.text
    assert second.json() == first.json()
    assert third.json() == first.json()
    assert count_items(title) == 1


def test_fault_retry_after_partial_commit_landed_response_lost(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    title, key = new_title(), new_key()
    failed = post_through_session(
        CommitLandsThenConnectionDrops, superuser_token_headers, title, key
    )
    assert failed.status_code == 500
    assert count_items(title) == 1

    retry = post_item(client, superuser_token_headers, title, key)
    assert retry.status_code == 200, retry.text
    assert count_items(title) == 1

    again = post_item(client, superuser_token_headers, title, key)
    assert again.status_code == 200, again.text
    assert again.json()["id"] == retry.json()["id"]
    assert count_items(title) == 1


def test_fault_retry_after_partial_flush_never_committed(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    title, key = new_title(), new_key()
    failed = post_through_session(
        ConnectionDropsBeforeCommit, superuser_token_headers, title, key
    )
    assert failed.status_code == 500
    assert count_items(title) == 0

    retry = post_item(client, superuser_token_headers, title, key)
    assert retry.status_code == 200, retry.text
    assert count_items(title) == 1

    again = post_item(client, superuser_token_headers, title, key)
    assert again.status_code == 200, again.text
    assert again.json()["id"] == retry.json()["id"]
    assert count_items(title) == 1


def test_fault_back_to_back_duplicate(
    superuser_token_headers: dict[str, str],
) -> None:
    title, key = new_title(), new_key()
    barrier = threading.Barrier(2)
    responses: list[httpx.Response | None] = [None, None]
    errors: list[BaseException] = []

    def deliver(slot: int) -> None:
        try:
            own_client = TestClient(app)
            barrier.wait(timeout=30)
            responses[slot] = post_item(
                own_client, superuser_token_headers, title, key, "concurrent"
            )
        except BaseException as exc:  # surfaced in the main thread
            errors.append(exc)

    workers = [threading.Thread(target=deliver, args=(i,)) for i in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=60)

    assert not errors, errors
    first, second = responses
    assert first is not None and second is not None
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] == second.json()["id"]
    assert count_items(title) == 1


def test_fault_distinct_events(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    title = new_title()
    key_a, key_b = new_key(), new_key()
    a = post_item(client, superuser_token_headers, title, key_a)
    b = post_item(client, superuser_token_headers, title, key_b)
    assert a.status_code == 200, a.text
    assert b.status_code == 200, b.text
    assert a.json()["id"] != b.json()["id"]
    assert count_items(title) == 2

    replay_a = post_item(client, superuser_token_headers, title, key_a)
    assert replay_a.status_code == 200, replay_a.text
    assert replay_a.json()["id"] == a.json()["id"]
    assert count_items(title) == 2


def test_requests_without_key_still_create_each_time(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    title = new_title()
    first = post_item(client, superuser_token_headers, title)
    second = post_item(client, superuser_token_headers, title)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] != second.json()["id"]
    assert count_items(title) == 2


def test_reused_key_with_different_payload_is_rejected(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    key = new_key()
    title_a, title_b = new_title(), new_title()
    first = post_item(client, superuser_token_headers, title_a, key)
    assert first.status_code == 200, first.text
    clash = post_item(client, superuser_token_headers, title_b, key)
    assert clash.status_code == 422, clash.text
    assert count_items(title_a) == 1
    assert count_items(title_b) == 0


def test_same_key_from_different_users_creates_separate_items(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
) -> None:
    title, key = new_title(), new_key()
    admin_item = post_item(client, superuser_token_headers, title, key)
    user_item = post_item(client, normal_user_token_headers, title, key)
    assert admin_item.status_code == 200, admin_item.text
    assert user_item.status_code == 200, user_item.text
    assert admin_item.json()["id"] != user_item.json()["id"]
    assert admin_item.json()["owner_id"] != user_item.json()["owner_id"]
    assert count_items(title) == 2


def test_blank_key_is_rejected(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    title = new_title()
    response = post_item(client, superuser_token_headers, title, "")
    assert response.status_code == 422, response.text
    assert count_items(title) == 0


def test_key_length_limit(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    too_long_title = new_title()
    too_long = post_item(client, superuser_token_headers, too_long_title, "k" * 256)
    assert too_long.status_code == 422, too_long.text
    assert count_items(too_long_title) == 0

    max_title = new_title()
    max_key = (uuid.uuid4().hex * 8)[:255]
    first = post_item(client, superuser_token_headers, max_title, max_key)
    second = post_item(client, superuser_token_headers, max_title, max_key)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
    assert count_items(max_title) == 1
