"""Extension + tables + indexes. See spec/04-postgres-schema-spec.md.

One table per persisted shape, each with a handful of real columns for the
filters/joins we actually run (type, name, source_id/target_id for traversal,
entity_ids for chunk lookups) plus a `data JSONB` column holding the full
Pydantic model dump — so any record round-trips exactly via
`Model.model_validate(row["data"])` without hand-listing every field in SQL.
"""

from __future__ import annotations

from app.persistence.postgres import PostgresConnection
from app.utils.logging import get_logger

log = get_logger("postgres")

_DDL_STATEMENTS = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    """
    CREATE TABLE IF NOT EXISTS entities (
        id TEXT PRIMARY KEY,
        entity_type TEXT NOT NULL,
        canonical_name TEXT NOT NULL,
        aliases TEXT[] NOT NULL DEFAULT '{}',
        data JSONB NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS entities_type_idx ON entities (entity_type)",
    "CREATE INDEX IF NOT EXISTS entities_name_idx ON entities (canonical_name)",
    """
    CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        aliases TEXT[] NOT NULL DEFAULT '{}',
        data JSONB NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS events_name_idx ON events (name)",
    """
    CREATE TABLE IF NOT EXISTS relationships (
        id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        relationship_type TEXT NOT NULL,
        data JSONB NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS relationships_source_idx ON relationships (source_id)",
    "CREATE INDEX IF NOT EXISTS relationships_target_idx ON relationships (target_id)",
    "CREATE INDEX IF NOT EXISTS relationships_type_idx ON relationships (relationship_type)",
    """
    CREATE TABLE IF NOT EXISTS claims (
        id TEXT PRIMARY KEY,
        subject_id TEXT,
        object_id TEXT,
        data JSONB NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS claims_subject_idx ON claims (subject_id)",
    "CREATE INDEX IF NOT EXISTS claims_object_idx ON claims (object_id)",
    """
    CREATE TABLE IF NOT EXISTS chunks (
        id TEXT PRIMARY KEY,
        entity_ids TEXT[] NOT NULL,
        chunk_type TEXT NOT NULL,
        text TEXT NOT NULL,
        embedding vector,
        data JSONB NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS chunks_entity_ids_idx ON chunks USING gin (entity_ids)",
    """
    CREATE TABLE IF NOT EXISTS ingestion_runs (
        id TEXT PRIMARY KEY,
        civilization_id TEXT NOT NULL,
        data JSONB NOT NULL
    )
    """,
]


async def ensure_schema(conn: PostgresConnection) -> None:
    for statement in _DDL_STATEMENTS:
        await conn.execute(statement)
    log.info("POSTGRES", "Schema ensured (extension, tables, indexes)")
