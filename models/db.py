from __future__ import annotations
"""
db.py — PostgreSQL connection pool using psycopg2.

Uses a ThreadedConnectionPool so connections are reused across requests
instead of opened/closed on every query. The pool size is tunable via
DB_POOL_MIN / DB_POOL_MAX env vars (defaults: 2 / 10).

Usage in models:
    from models.db import get_connection, dict_cursor

    conn = get_connection()
    try:
        cur = conn.cursor()
        ...
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()   # returns connection to pool, does NOT close the socket
"""
import logging
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool as pg_pool
from config import DATABASE_URL

logger = logging.getLogger(__name__)

_pool: pg_pool.ThreadedConnectionPool | None = None


def _get_pool() -> pg_pool.ThreadedConnectionPool:
    global _pool
    if _pool is None or _pool.closed:
        min_conn = int(os.environ.get("DB_POOL_MIN", 2))
        max_conn = int(os.environ.get("DB_POOL_MAX", 10))
        _pool = pg_pool.ThreadedConnectionPool(
            min_conn, max_conn, DATABASE_URL
        )
        logger.info("DB pool created (min=%d max=%d)", min_conn, max_conn)
    return _pool


class _PooledConnection:
    """
    Thin wrapper around a pooled psycopg2 connection.
    Calling .close() returns the connection to the pool instead of
    closing the underlying socket, so callers don't need to change
    their finally: conn.close() patterns.
    """
    def __init__(self, conn):
        self._conn = conn

    # Delegate all attribute access to the real connection
    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        try:
            _get_pool().putconn(self._conn)
        except Exception as e:
            logger.warning("Failed to return connection to pool: %s", e)


def get_connection() -> _PooledConnection:
    """
    Get a connection from the pool.
    Always use inside try/finally: conn.close() to return it.
    autocommit is OFF — callers must commit or rollback explicitly.
    """
    conn = _get_pool().getconn()
    conn.autocommit = False
    return _PooledConnection(conn)


def dict_cursor(conn):
    """Return a cursor that yields rows as plain dicts."""
    return conn.cursor(cursor_factory=RealDictCursor)
