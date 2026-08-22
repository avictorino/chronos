"""Repositories — one per persisted shape, all `INSERT ... ON CONFLICT (id) DO
UPDATE` (idempotent, same deterministic-id design as the rest of the app).

`EntityRepository` covers every `AnyEntity` subclass (Civilization, Person,
Place, Polity, Document, Concept) uniformly — they all land in one `entities`
table distinguished by `entity_type`, rather than one repository/table per
subtype (spec/01: simplicity over abstraction).
"""

from __future__ import annotations

from app.domain.enums import EntityType
from app.domain.models import (
    AnyEntity,
    HistoricalClaim,
    HistoricalEvent,
    HistoricalRelationship,
    IngestionRun,
    KnowledgeChunk,
)
from app.persistence.postgres import PostgresConnection, vector_literal
from app.utils.logging import get_logger

log = get_logger("postgres")


class EntityRepository:
    def __init__(self, conn: PostgresConnection) -> None:
        self._conn = conn

    async def upsert(self, entity: AnyEntity) -> None:
        await self._conn.execute(
            """
            INSERT INTO entities (id, entity_type, canonical_name, aliases, data)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (id) DO UPDATE SET
                entity_type = EXCLUDED.entity_type,
                canonical_name = EXCLUDED.canonical_name,
                aliases = EXCLUDED.aliases,
                data = EXCLUDED.data
            """,
            entity.id,
            entity.entity_type.value,
            entity.canonical_name,
            entity.aliases,
            entity.model_dump(mode="json"),
        )
        log.info("POSTGRES", "Entity upserted", entity_type=entity.entity_type.value, name=entity.canonical_name)

    async def find_candidates(self, entity_type: EntityType) -> list[dict]:
        """Always queries Postgres (never just in-memory state) — the only way
        to reuse entities discovered by a *previous* ingestion run of a
        different civilization (e.g. Judah/Babylon mentioned by Assyria)."""
        rows = await self._conn.fetch(
            "SELECT id, canonical_name, aliases, data->>'summary' AS summary "
            "FROM entities WHERE entity_type = $1",
            entity_type.value,
        )
        return [dict(r) for r in rows]

    async def get(self, entity_id: str) -> dict | None:
        row = await self._conn.fetchrow("SELECT * FROM entities WHERE id = $1", entity_id)
        return dict(row) if row else None


class EventRepository:
    def __init__(self, conn: PostgresConnection) -> None:
        self._conn = conn

    async def upsert(self, event: HistoricalEvent) -> None:
        await self._conn.execute(
            """
            INSERT INTO events (id, name, aliases, data)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, aliases = EXCLUDED.aliases, data = EXCLUDED.data
            """,
            event.id,
            event.name,
            event.aliases,
            event.model_dump(mode="json"),
        )
        log.info("POSTGRES", "Event upserted", name=event.name)

    async def find_candidates(self) -> list[dict]:
        rows = await self._conn.fetch(
            "SELECT id, name AS canonical_name, aliases, data->>'description' AS summary FROM events"
        )
        return [dict(r) for r in rows]


class RelationshipRepository:
    def __init__(self, conn: PostgresConnection) -> None:
        self._conn = conn

    async def upsert(self, rel: HistoricalRelationship) -> None:
        await self._conn.execute(
            """
            INSERT INTO relationships (id, source_id, target_id, relationship_type, data)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (id) DO UPDATE SET
                source_id = EXCLUDED.source_id,
                target_id = EXCLUDED.target_id,
                relationship_type = EXCLUDED.relationship_type,
                data = EXCLUDED.data
            """,
            rel.id,
            rel.source_entity_id,
            rel.target_entity_id,
            rel.relationship_type.value,
            rel.model_dump(mode="json"),
        )
        log.info("POSTGRES", "Relationship created", type=rel.relationship_type.value)

    async def find_connected(self, start_id: str, max_hops: int = 4) -> list[dict]:
        """Multi-hop traversal from `start_id`, following relationships in
        either direction, up to `max_hops` — the WITH RECURSIVE building block
        for the future cross-civilization exploration feature (spec/01,
        "Assyria -> Judah -> Babylon -> Persia -> Greece"). Not wired into the
        ingestion pipeline yet; kept deliberately simple (re-walks
        `relationships` each step, no query-plan tuning) per project
        philosophy — see spec/04-postgres-schema-spec.md.
        """
        rows = await self._conn.fetch(
            """
            WITH RECURSIVE traversal(id, path, depth) AS (
                SELECT $1::text, ARRAY[$1::text], 0
                UNION ALL
                SELECT
                    next_id,
                    t.path || next_id,
                    t.depth + 1
                FROM traversal t
                JOIN relationships r ON r.source_id = t.id OR r.target_id = t.id
                CROSS JOIN LATERAL (
                    SELECT CASE WHEN r.source_id = t.id THEN r.target_id ELSE r.source_id END AS next_id
                ) hop
                WHERE t.depth < $2
                  AND NOT (hop.next_id = ANY(t.path))
            )
            SELECT DISTINCT id, path, depth FROM traversal WHERE depth > 0 ORDER BY depth, id
            """,
            start_id,
            max_hops,
        )
        return [dict(r) for r in rows]


class ClaimRepository:
    def __init__(self, conn: PostgresConnection) -> None:
        self._conn = conn

    async def upsert(self, claim: HistoricalClaim) -> None:
        await self._conn.execute(
            """
            INSERT INTO claims (id, subject_id, object_id, data)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (id) DO UPDATE SET
                subject_id = EXCLUDED.subject_id,
                object_id = EXCLUDED.object_id,
                data = EXCLUDED.data
            """,
            claim.id,
            claim.subject_id,
            claim.object_id,
            claim.model_dump(mode="json"),
        )
        log.info("POSTGRES", "Claim upserted", predicate=claim.predicate)


class ChunkRepository:
    def __init__(self, conn: PostgresConnection) -> None:
        self._conn = conn

    async def upsert(self, chunk: KnowledgeChunk) -> None:
        embedding_literal = vector_literal(chunk.embedding) if chunk.embedding is not None else None
        await self._conn.execute(
            """
            INSERT INTO chunks (id, entity_ids, chunk_type, text, embedding, data)
            VALUES ($1, $2, $3, $4, $5::vector, $6)
            ON CONFLICT (id) DO UPDATE SET
                entity_ids = EXCLUDED.entity_ids,
                chunk_type = EXCLUDED.chunk_type,
                text = EXCLUDED.text,
                embedding = EXCLUDED.embedding,
                data = EXCLUDED.data
            """,
            chunk.id,
            chunk.entity_ids,
            chunk.chunk_type,
            chunk.text,
            embedding_literal,
            chunk.model_dump(mode="json"),
        )
        log.info("EMBEDDING", "Chunk embedded and linked", chunk_type=chunk.chunk_type)


class IngestionRunRepository:
    def __init__(self, conn: PostgresConnection) -> None:
        self._conn = conn

    async def save(self, run: IngestionRun) -> None:
        await self._conn.execute(
            """
            INSERT INTO ingestion_runs (id, civilization_id, data)
            VALUES ($1, $2, $3)
            ON CONFLICT (id) DO UPDATE SET civilization_id = EXCLUDED.civilization_id, data = EXCLUDED.data
            """,
            run.id,
            run.civilization_id,
            run.model_dump(mode="json"),
        )
