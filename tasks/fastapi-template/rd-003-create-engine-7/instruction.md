# Size the database connection pool from the connection budget

`backend/app/core/db.py` builds the SQLAlchemy engine with SQLAlchemy's fixed default pool sizes: 5 persistent connections plus 10 overflow connections per process. Every worker process gets its own pool. On a laptop with one worker this is fine. In production with several workers (`WEB_CONCURRENCY`), the total number of connections can go over what the Postgres server allows, and requests then fail with "too many clients". A zero or negative size is also accepted without complaint and only breaks later.

Make the pool sizes come from configured limits, and reject impossible combinations at startup.

## Settings

Add a pydantic-settings class `DatabasePoolSettings` in a new module `app.core.db_pool`. It reads these environment variables:

| variable | type | default | meaning |
|---|---|---|---|
| `WEB_CONCURRENCY` | int | `1` | number of worker processes sharing the database |
| `DB_POOL_SIZE` | int | `5` | persistent connections per worker |
| `DB_MAX_OVERFLOW` | int, optional | unset | extra burst connections per worker; derived when unset |
| `DB_MAX_CONNECTIONS` | int, optional | unset | total connections the app may open across all workers |

The class must accept the usual pydantic-settings construction, `DatabasePoolSettings(_env_file=None, **values)`. It exposes two read-only attributes: `pool_size` and `max_overflow`.

## Formula (document it in the module)

- `pool_size` = `DB_POOL_SIZE`.
- If `DB_MAX_OVERFLOW` is set, `max_overflow` = `DB_MAX_OVERFLOW`.
- Otherwise, if `DB_MAX_CONNECTIONS` is set, `max_overflow` = `DB_MAX_CONNECTIONS // WEB_CONCURRENCY - DB_POOL_SIZE`. Each worker's share of the budget, minus its persistent connections.
- Otherwise (no limit configured), `max_overflow` = `2 * DB_POOL_SIZE` as the safe default. With the shipped defaults this gives 5 + 10, the same as today.

## Validation (raise at construction; a `ValueError` or pydantic `ValidationError` both count)

1. `WEB_CONCURRENCY`, `DB_POOL_SIZE` and `DB_MAX_CONNECTIONS` (when set) must be at least 1. `DB_MAX_OVERFLOW` (when set) must be at least 0. The error names each offending variable.
2. When `DB_MAX_CONNECTIONS` is set and `WEB_CONCURRENCY * DB_POOL_SIZE` is greater than it, reject. The message must name `DB_POOL_SIZE`, `WEB_CONCURRENCY` and `DB_MAX_CONNECTIONS`. This includes the case where there are more workers than allowed connections.
3. When `DB_MAX_CONNECTIONS` and `DB_MAX_OVERFLOW` are both set and `WEB_CONCURRENCY * (DB_POOL_SIZE + DB_MAX_OVERFLOW)` is greater than the limit, reject. The message must name `DB_MAX_OVERFLOW` and `DB_MAX_CONNECTIONS`.
4. A total exactly equal to the limit is allowed.

## Engine wiring

- Add `build_engine(database_url, pool_settings=None)` to `app.core.db`. It returns the engine created with `pool_pre_ping=True`, `pool_size=pool_settings.pool_size` and `max_overflow=pool_settings.max_overflow`. If no settings object is passed, it uses `DatabasePoolSettings()`.
- The module-level `engine` must be built through this function, so the derived values are the ones actually used.

The shipped defaults must still load, and the existing test suite must still pass.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
