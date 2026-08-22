"""Thin wrapper around an asyncpg connection pool.

No ORM, no query builder — every repository writes plain SQL. The pool
registers a JSONB codec (Python dict <-> JSON text) so callers can pass/get
plain dicts for `jsonb` columns. pgvector's `vector` columns are handled via
`vector_literal`/`parse_vector` below (text format) instead of a registered
codec, so there's no bootstrap-ordering problem between `CREATE EXTENSION
vector` and opening the pool — see spec/04-postgres-schema-spec.md.
"""

from __future__ import annotations

import json

import asyncpg

from app.config import Settings


async def _init_connection(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog", format="text")


def vector_literal(values: list[float]) -> str:
    """Python list -> pgvector text input format, e.g. '[0.1,0.2,0.3]'."""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def parse_vector(text: str | None) -> list[float] | None:
    """pgvector text output format ('[0.1,0.2,0.3]') -> Python list, or None."""
    if text is None:
        return None
    stripped = text.strip("[]")
    return [float(x) for x in stripped.split(",")] if stripped else []


class PostgresConnection:
    def __init__(self, settings: Settings) -> None:
        self._dsn = settings.postgres_dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                dsn=self._dsn, min_size=1, max_size=10, init=_init_connection
            )

    async def verify_connectivity(self) -> None:
        await self.connect()
        async with self._pool.acquire() as conn:  # type: ignore[union-attr]
            await conn.execute("SELECT 1")

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def execute(self, query: str, *args: object) -> str:
        assert self._pool is not None, "call connect()/verify_connectivity() first"
        return await self._pool.execute(query, *args)

    async def fetch(self, query: str, *args: object) -> list[asyncpg.Record]:
        assert self._pool is not None, "call connect()/verify_connectivity() first"
        return await self._pool.fetch(query, *args)

    async def fetchrow(self, query: str, *args: object) -> asyncpg.Record | None:
        assert self._pool is not None, "call connect()/verify_connectivity() first"
        return await self._pool.fetchrow(query, *args)
