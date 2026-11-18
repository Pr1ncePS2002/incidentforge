# Derive database pool sizing from the configured limits and reject impossible combinations

Miniflux runs a pool of feed refresh workers (`WORKER_POOL_SIZE`, default 16). Each worker uses a PostgreSQL connection from the pool limited by `DATABASE_MAX_CONNS` (default 20), with `DATABASE_MIN_CONNS` (default 1) idle connections kept open. The parser checks each setting on its own, but nothing checks them against each other. If an operator lowers `DATABASE_MAX_CONNS` below the worker count, the refresh workers take every connection. The web UI, the API and the scheduler then hang waiting for a connection. If `DATABASE_MIN_CONNS` is above `DATABASE_MAX_CONNS`, the pool cannot start in a consistent state. A size of zero or below makes the pool or the worker pool deadlock.

Add one place, in package `internal/config`, that derives the pool sizes from these settings and rejects impossible combinations at startup.

## API

1. An exported struct `PoolSizing` with the `int` fields `Workers`, `MinConns`, `MaxConns` and `ReservedConns`.
2. An exported function `DerivePoolSizing(workers, minConns, maxConns int) (PoolSizing, error)`. The arguments are the values of `WORKER_POOL_SIZE`, `DATABASE_MIN_CONNS` and `DATABASE_MAX_CONNS`.
3. A method on the parsed options, `func (c *configOptions) DatabasePoolSizing() (PoolSizing, error)`. It calls `DerivePoolSizing` with the configured `WORKER_POOL_SIZE`, `DATABASE_MIN_CONNS` and `DATABASE_MAX_CONNS`.

## Formula

Every refresh worker holds at most one connection, and at least one connection must stay free for the web UI and the API. So:

- `Workers`, `MinConns` and `MaxConns` are exactly the configured values. Never use a fixed constant.
- `ReservedConns = DATABASE_MAX_CONNS - WORKER_POOL_SIZE`, and it must be at least 1.

## Errors

Return an error and a zero `PoolSizing` in each of these cases:

- `DATABASE_MAX_CONNS` below 1. The error names `DATABASE_MAX_CONNS`.
- `WORKER_POOL_SIZE` below 1. The error names `WORKER_POOL_SIZE`.
- `DATABASE_MIN_CONNS` negative. The error names `DATABASE_MIN_CONNS`. Zero is allowed.
- `DATABASE_MIN_CONNS` greater than `DATABASE_MAX_CONNS`. A single error names **both** settings. Equal values are allowed.
- `WORKER_POOL_SIZE` greater than or equal to `DATABASE_MAX_CONNS`. A single error names **both** settings.

When one of the first three range checks fails, the error names only the offending setting.

## Compatibility

The shipped defaults (16 workers, 1 to 20 connections) must derive without error, giving `ReservedConns` = 4. The existing test suite must keep passing.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
