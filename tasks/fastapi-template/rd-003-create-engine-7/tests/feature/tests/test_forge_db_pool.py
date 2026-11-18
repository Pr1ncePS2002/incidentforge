"""connection-pool sizing must follow the configured connection budget."""

import pytest

from app.core import db
from app.core.config import settings
from app.core.db_pool import DatabasePoolSettings

POOL_VARS = (
    "WEB_CONCURRENCY",
    "DB_POOL_SIZE",
    "DB_MAX_OVERFLOW",
    "DB_MAX_CONNECTIONS",
)


@pytest.fixture(autouse=True)
def _clean_pool_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in POOL_VARS:
        monkeypatch.delenv(name, raising=False)


def make(**overrides: object) -> DatabasePoolSettings:
    return DatabasePoolSettings(_env_file=None, **overrides)  # type: ignore[arg-type]


def assert_rejected(names: list[str], **overrides: object) -> None:
    with pytest.raises(ValueError) as exc:
        make(**overrides)
    for name in names:
        assert name in str(exc.value), f"{name} missing from: {exc.value}"


def test_shipped_defaults_load() -> None:
    s = make()
    assert s.pool_size == 5
    assert s.max_overflow == 10


def test_module_engine_uses_pool_settings() -> None:
    expected = DatabasePoolSettings()
    assert db.engine.pool.size() == expected.pool_size  # type: ignore[attr-defined]
    assert db.engine.pool._max_overflow == expected.max_overflow  # type: ignore[attr-defined]


def test_exact_fit_is_allowed() -> None:
    s = make(DB_MAX_CONNECTIONS=20, WEB_CONCURRENCY=2, DB_POOL_SIZE=5, DB_MAX_OVERFLOW=5)
    assert s.pool_size == 5
    assert s.max_overflow == 5


def test_zero_overflow_is_allowed() -> None:
    assert make(DB_MAX_OVERFLOW=0).max_overflow == 0


@pytest.mark.parametrize(
    ("limit", "workers", "pool", "overflow"),
    [(40, 4, 4, 6), (100, 2, 10, 40), (12, 1, 3, 9), (31, 3, 4, 6)],
)
def test_fault_hardcoded_size(limit: int, workers: int, pool: int, overflow: int) -> None:
    s = make(DB_MAX_CONNECTIONS=limit, WEB_CONCURRENCY=workers, DB_POOL_SIZE=pool)
    assert s.pool_size == pool
    assert s.max_overflow == overflow


def test_fault_hardcoded_size_reaches_engine() -> None:
    pool = make(DB_MAX_CONNECTIONS=30, WEB_CONCURRENCY=3, DB_POOL_SIZE=4)
    engine = db.build_engine(str(settings.DATABASE_URL), pool)
    try:
        assert engine.pool.size() == 4  # type: ignore[attr-defined]
        assert engine.pool._max_overflow == 6  # type: ignore[attr-defined]
    finally:
        engine.dispose()


def test_fault_unset_limit_uses_safe_default() -> None:
    s = make(DB_POOL_SIZE=8)
    assert s.pool_size == 8
    assert s.max_overflow == 16
    assert make(WEB_CONCURRENCY=16).max_overflow == 10


def test_fault_unset_limit_keeps_explicit_overflow() -> None:
    assert make(DB_POOL_SIZE=3, DB_MAX_OVERFLOW=2).max_overflow == 2


def test_fault_exceeds_limit_pool_size() -> None:
    assert_rejected(
        ["DB_POOL_SIZE", "WEB_CONCURRENCY", "DB_MAX_CONNECTIONS"],
        DB_MAX_CONNECTIONS=20,
        WEB_CONCURRENCY=4,
        DB_POOL_SIZE=6,
    )


def test_fault_exceeds_limit_more_workers_than_connections() -> None:
    assert_rejected(
        ["WEB_CONCURRENCY", "DB_MAX_CONNECTIONS"],
        DB_MAX_CONNECTIONS=3,
        WEB_CONCURRENCY=4,
        DB_POOL_SIZE=1,
    )


def test_fault_exceeds_limit_with_overflow() -> None:
    assert_rejected(
        ["DB_MAX_OVERFLOW", "DB_MAX_CONNECTIONS"],
        DB_MAX_CONNECTIONS=20,
        WEB_CONCURRENCY=2,
        DB_POOL_SIZE=5,
        DB_MAX_OVERFLOW=6,
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("WEB_CONCURRENCY", 0),
        ("WEB_CONCURRENCY", -2),
        ("DB_POOL_SIZE", 0),
        ("DB_POOL_SIZE", -1),
        ("DB_MAX_CONNECTIONS", 0),
        ("DB_MAX_CONNECTIONS", -5),
        ("DB_MAX_OVERFLOW", -1),
    ],
)
def test_fault_zero_or_negative(name: str, value: int) -> None:
    assert_rejected([name], **{name: value})
