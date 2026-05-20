"""Read-only connection to the legacy uchile Postgres database.

Always opens with `default_transaction_read_only=on` so a buggy query
can't accidentally modify the source. Password is read from the
`LEGACY_DB_PASSWORD` env var — NEVER hardcoded or logged.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row


# Defaults match the discovery configuration; can be overridden by the
# management command via --legacy-host / --legacy-port / etc.
DEFAULT_HOST = "192.168.1.24"
DEFAULT_PORT = 5432
DEFAULT_DB = "uchile"
DEFAULT_USER = "slab_migration_ro"
DEFAULT_SCHEMA = "public"


class LegacyDB:
    """Thin wrapper around a psycopg connection. Use as a context
    manager so the connection always closes:

        with LegacyDB() as db:
            for row in db.iter_rows("SELECT * FROM jugador"):
                ...
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        dbname: str = DEFAULT_DB,
        user: str = DEFAULT_USER,
        password: str | None = None,
        schema: str = DEFAULT_SCHEMA,
    ) -> None:
        self.host = host
        self.port = port
        self.dbname = dbname
        self.user = user
        self.password = password or os.environ.get("LEGACY_DB_PASSWORD", "")
        if not self.password:
            raise RuntimeError(
                "LEGACY_DB_PASSWORD env var is not set. Pass the read-only "
                "password via the env var; never include it in code or CLI flags."
            )
        self.schema = schema
        self._conn: psycopg.Connection | None = None

    def __enter__(self) -> "LegacyDB":
        dsn = (
            f"host={self.host} port={self.port} dbname={self.dbname} "
            f"user={self.user} password={self.password} application_name=slab_migrator"
        )
        self._conn = psycopg.connect(
            dsn,
            row_factory=dict_row,
            # Enforce read-only at the server level — defence in depth.
            options=f"-c default_transaction_read_only=on -c search_path={self.schema}",
            # Autocommit: every SELECT runs in its own implicit txn. Without
            # this, a single failed query (e.g. a JOIN referencing a column
            # that doesn't exist) puts the connection into an aborted-txn
            # state and all subsequent queries fail. Since we're read-only,
            # there's no consistency value to wrapping queries in a single
            # transaction anyway.
            autocommit=True,
        )
        return self

    def __exit__(self, *exc) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> psycopg.Connection:
        if self._conn is None:
            raise RuntimeError("LegacyDB used outside a `with` block.")
        return self._conn

    def iter_rows(self, sql: str, params: tuple = ()) -> Iterator[dict]:
        """Stream rows from a SELECT. dict_row gives column-keyed dicts."""
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            for row in cur:
                yield row

    def fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())
