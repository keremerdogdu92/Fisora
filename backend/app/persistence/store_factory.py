from __future__ import annotations

import os
from pathlib import Path
from threading import Condition, Lock
from time import monotonic
from typing import Any

from app.persistence.postgres_workflow_store import PostgresWorkflowStore
from app.persistence.workflow_store import JsonWorkflowStore


class ProcessLocalPostgresConnectionPool:
    """Small bounded pool whose leases preserve per-operation transactions."""

    def __init__(
        self,
        *,
        connect: Any,
        max_size: int = 4,
        acquire_timeout_seconds: float = 10.0,
    ) -> None:
        if max_size < 1:
            raise ValueError("PostgreSQL pool max_size must be positive")
        if acquire_timeout_seconds <= 0:
            raise ValueError("PostgreSQL pool acquire timeout must be positive")
        self._connect = connect
        self.max_size = int(max_size)
        self.acquire_timeout_seconds = float(acquire_timeout_seconds)
        self._condition = Condition(Lock())
        self._available: list[Any] = []
        self._created = 0
        self._in_use = 0

    def connection(self) -> _PostgresConnectionLease:
        return _PostgresConnectionLease(self)

    def _acquire(self) -> Any:
        deadline = monotonic() + self.acquire_timeout_seconds
        create = False
        with self._condition:
            while not self._available and self._created >= self.max_size:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError("PostgreSQL connection pool acquire timed out")
                self._condition.wait(remaining)
            if self._available:
                connection = self._available.pop()
            else:
                self._created += 1
                create = True
                connection = None
        if create:
            try:
                connection = self._connect()
            except Exception:
                with self._condition:
                    self._created -= 1
                    self._condition.notify()
                raise
        with self._condition:
            self._in_use += 1
        return connection

    def _release(self, connection: Any, *, discard: bool) -> None:
        closed = bool(getattr(connection, "closed", False))
        with self._condition:
            self._in_use -= 1
            if discard or closed:
                self._created -= 1
            else:
                self._available.append(connection)
            self._condition.notify()
        if discard and not closed:
            try:
                connection.close()
            except Exception:
                pass

    def stats(self) -> dict[str, int]:
        with self._condition:
            return {
                "max_size": self.max_size,
                "created": self._created,
                "available": len(self._available),
                "in_use": self._in_use,
            }


class _PostgresConnectionLease:
    def __init__(self, pool: ProcessLocalPostgresConnectionPool) -> None:
        self._pool = pool
        self._connection: Any | None = None

    def __enter__(self) -> Any:
        self._connection = self._pool._acquire()
        return self._connection

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        connection = self._connection
        if connection is None:
            return False
        discard = False
        transaction_error: Exception | None = None
        try:
            if exc_type is None:
                connection.commit()
            else:
                connection.rollback()
        except Exception as transaction_exc:
            discard = True
            transaction_error = transaction_exc
        finally:
            self._pool._release(connection, discard=discard)
            self._connection = None
        if exc_type is None and transaction_error is not None:
            raise transaction_error
        return False


_POSTGRES_POOLS: dict[tuple[str, int, float], ProcessLocalPostgresConnectionPool] = {}
_POSTGRES_POOLS_LOCK = Lock()


def _postgres_pool(
    dsn: str,
    *,
    max_size: int,
    acquire_timeout_seconds: float,
) -> ProcessLocalPostgresConnectionPool:
    key = (dsn, max_size, acquire_timeout_seconds)
    with _POSTGRES_POOLS_LOCK:
        pool = _POSTGRES_POOLS.get(key)
        if pool is None:
            def connect() -> Any:
                import psycopg

                return psycopg.connect(dsn)

            pool = ProcessLocalPostgresConnectionPool(
                connect=connect,
                max_size=max_size,
                acquire_timeout_seconds=acquire_timeout_seconds,
            )
            _POSTGRES_POOLS[key] = pool
        return pool


def _positive_int_env(name: str, default: int) -> int:
    try:
        return max(int(os.environ.get(name, str(default))), 1)
    except ValueError:
        return default


def _positive_float_env(name: str, default: float) -> float:
    try:
        return max(float(os.environ.get(name, str(default))), 0.1)
    except ValueError:
        return default


def build_workflow_store(
    *,
    store_backend: str | None = None,
    json_path: Path | str | None = None,
    postgres_dsn: str | None = None,
) -> Any:
    backend = (store_backend or os.environ.get("FISORA_STORE_BACKEND") or "json").strip().lower()
    if backend == "json":
        path = json_path or os.environ.get("FISORA_STORE_PATH", "exports/phase0_store.json")
        return JsonWorkflowStore(path)
    if backend == "postgres":
        dsn = postgres_dsn or os.environ.get("FISORA_DATABASE_URL") or os.environ.get("DATABASE_URL") or ""
        pool = _postgres_pool(
            dsn,
            max_size=_positive_int_env("FISORA_POSTGRES_POOL_MAX_SIZE", 4),
            acquire_timeout_seconds=_positive_float_env(
                "FISORA_POSTGRES_POOL_ACQUIRE_TIMEOUT_SECONDS",
                10.0,
            ),
        )
        store = PostgresWorkflowStore(dsn, connect=pool.connection)
        store.connection_pool = pool
        return store
    raise ValueError(f"Unsupported workflow store backend: {backend}")
