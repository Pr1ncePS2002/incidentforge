"""Token checks must be recorded once per (user, Idempotency-Key), even on retry."""

import threading
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.core import token_audit
from app.core.config import settings
from app.main import app

URL = f"{settings.API_V1_STR}/login/test-token"


@pytest.fixture(autouse=True)
def _clean_audit_log() -> Generator[None, None, None]:
    token_audit.reset_token_checks()
    yield
    token_audit.reset_token_checks()


def _user_id(client: TestClient, headers: dict[str, str]) -> str:
    r = client.get(f"{settings.API_V1_STR}/users/me", headers=headers)
    assert r.status_code == 200
    return str(r.json()["id"])


def _events(user_id: str) -> list[token_audit.TokenCheckEvent]:
    return [e for e in token_audit.list_token_checks() if str(e.user_id) == user_id]


def test_check_without_key_records_every_call(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    uid = _user_id(client, normal_user_token_headers)
    r1 = client.post(URL, headers=normal_user_token_headers)
    r2 = client.post(URL, headers=normal_user_token_headers)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.headers["X-Token-Check-Id"] != r2.headers["X-Token-Check-Id"]
    assert "Idempotency-Replayed" not in r1.headers
    assert "Idempotency-Replayed" not in r2.headers
    events = _events(uid)
    assert len(events) == 2
    assert all(e.idempotency_key is None for e in events)


def test_first_keyed_check_reports_recorded_event(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    uid = _user_id(client, normal_user_token_headers)
    headers = {**normal_user_token_headers, "Idempotency-Key": "first-only"}
    r = client.post(URL, headers=headers)
    assert r.status_code == 200
    assert r.json()["id"] == uid
    assert "Idempotency-Replayed" not in r.headers
    events = _events(uid)
    assert len(events) == 1
    assert str(events[0].id) == r.headers["X-Token-Check-Id"]
    assert events[0].idempotency_key == "first-only"
    assert events[0].created_at.tzinfo is not None


def test_fault_duplicate_delivery(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    uid = _user_id(client, normal_user_token_headers)
    headers = {**normal_user_token_headers, "Idempotency-Key": "retry-abc"}
    first = client.post(URL, headers=headers)
    second = client.post(URL, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    assert second.headers["X-Token-Check-Id"] == first.headers["X-Token-Check-Id"]
    assert "Idempotency-Replayed" not in first.headers
    assert second.headers.get("Idempotency-Replayed") == "true"
    events = _events(uid)
    assert len(events) == 1
    assert str(events[0].id) == first.headers["X-Token-Check-Id"]


def test_fault_duplicate_delivery_many_retries(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    uid = _user_id(client, superuser_token_headers)
    headers = {**superuser_token_headers, "Idempotency-Key": "retry-many"}
    responses = [client.post(URL, headers=headers) for _ in range(5)]
    assert all(r.status_code == 200 for r in responses)
    assert len({r.headers["X-Token-Check-Id"] for r in responses}) == 1
    assert [r.headers.get("Idempotency-Replayed") for r in responses[1:]] == [
        "true"
    ] * 4
    assert len(_events(uid)) == 1


def test_fault_back_to_back_duplicate(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    uid = _user_id(client, normal_user_token_headers)
    headers = {**normal_user_token_headers, "Idempotency-Key": "burst-1"}
    n = 8
    barrier = threading.Barrier(n)
    results: list = [None] * n
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            c = TestClient(app)
            barrier.wait(timeout=30)
            results[i] = c.post(URL, headers=headers)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors
    assert all(r is not None and r.status_code == 200 for r in results)
    ids = {r.headers["X-Token-Check-Id"] for r in results}
    assert len(ids) == 1
    events = _events(uid)
    assert len(events) == 1
    assert str(events[0].id) in ids
    replayed = [r.headers.get("Idempotency-Replayed") == "true" for r in results]
    assert sum(replayed) == n - 1


def test_fault_distinct_events_different_keys(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    uid = _user_id(client, normal_user_token_headers)
    ra = client.post(
        URL, headers={**normal_user_token_headers, "Idempotency-Key": "key-a"}
    )
    rb = client.post(
        URL, headers={**normal_user_token_headers, "Idempotency-Key": "key-b"}
    )
    assert ra.status_code == 200 and rb.status_code == 200
    assert ra.headers["X-Token-Check-Id"] != rb.headers["X-Token-Check-Id"]
    assert "Idempotency-Replayed" not in rb.headers
    events = _events(uid)
    assert sorted(e.idempotency_key or "" for e in events) == ["key-a", "key-b"]


def test_fault_distinct_events_same_key_different_users(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    normal_id = _user_id(client, normal_user_token_headers)
    super_id = _user_id(client, superuser_token_headers)
    assert normal_id != super_id
    rn = client.post(
        URL, headers={**normal_user_token_headers, "Idempotency-Key": "shared"}
    )
    rs = client.post(
        URL, headers={**superuser_token_headers, "Idempotency-Key": "shared"}
    )
    assert rn.status_code == 200 and rs.status_code == 200
    assert rn.json()["id"] == normal_id
    assert rs.json()["id"] == super_id
    assert rn.headers["X-Token-Check-Id"] != rs.headers["X-Token-Check-Id"]
    assert "Idempotency-Replayed" not in rs.headers
    assert len(_events(normal_id)) == 1
    assert len(_events(super_id)) == 1


@pytest.mark.parametrize("bad_key", ["", "k" * 256])
def test_invalid_idempotency_key_is_rejected(
    client: TestClient, normal_user_token_headers: dict[str, str], bad_key: str
) -> None:
    uid = _user_id(client, normal_user_token_headers)
    r = client.post(
        URL, headers={**normal_user_token_headers, "Idempotency-Key": bad_key}
    )
    assert r.status_code == 422
    assert _events(uid) == []


def test_max_length_key_is_accepted(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    uid = _user_id(client, normal_user_token_headers)
    r = client.post(
        URL, headers={**normal_user_token_headers, "Idempotency-Key": "k" * 255}
    )
    assert r.status_code == 200
    assert len(_events(uid)) == 1


def test_reset_forgets_keys(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    uid = _user_id(client, normal_user_token_headers)
    headers = {**normal_user_token_headers, "Idempotency-Key": "reset-me"}
    first = client.post(URL, headers=headers)
    token_audit.reset_token_checks()
    assert _events(uid) == []
    again = client.post(URL, headers=headers)
    assert again.status_code == 200
    assert "Idempotency-Replayed" not in again.headers
    assert again.headers["X-Token-Check-Id"] != first.headers["X-Token-Check-Id"]
    assert len(_events(uid)) == 1
