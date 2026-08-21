"""Repositories — one per persisted shape, all MERGE-based (idempotent).

`EntityRepository` covers every `AnyEntity` subclass (Civilization, Person,
Place, Polity, Document, Concept) uniformly via `ENTITY_LABELS`, rather than
one repository class per subtype — they all share the exact same upsert shape,
so a separate `CivilizationRepository` would just be indirection with no
behavioral difference (spec/01: simplicity over abstraction).
"""

from __future__ import annotations

import json

from app.domain.enums import EntityType
from app.domain.models import (
    ENTITY_LABELS,
    AnyEntity,
    HistoricalClaim,
    HistoricalEvent,
    HistoricalRelationship,
    IngestionRun,
    KnowledgeChunk,
)
from app.persistence.neo4j import Neo4jConnection
from app.utils.ids import stable_relationship_id
from app.utils.logging import get_logger

log = get_logger("neo4j")


def _flatten_for_neo4j(data: dict) -> dict:
    """Neo4j node/relationship properties must be primitives or arrays of
    primitives, never nested maps. Nested objects (HistoricalDate, the list of
    IngestionError on a run, ...) are serialized to a JSON string instead.
    `None` values are dropped (SET would just null the property anyway)."""
    flat: dict[str, object] = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, dict):
            flat[key] = json.dumps(value)
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            flat[key] = json.dumps(value)
        else:
            flat[key] = value
    return flat


class EntityRepository:
    def __init__(self, conn: Neo4jConnection) -> None:
        self._conn = conn

    async def upsert(self, entity: AnyEntity) -> None:
        label = ENTITY_LABELS[entity.entity_type]
        props = _flatten_for_neo4j(entity.model_dump(mode="json", exclude={"id"}))
        await self._conn.write(f"MERGE (n:{label} {{id: $id}}) SET n += $props", id=entity.id, props=props)
        log.info("NEO4J", "Entity upserted", label=label, name=entity.canonical_name)

    async def find_candidates(self, entity_type: EntityType) -> list[dict]:
        """Always queries Neo4j (never just in-memory state) — the only way to
        reuse entities discovered by a *previous* ingestion run of a different
        civilization (e.g. Judah/Babylon mentioned by Assyria)."""
        label = ENTITY_LABELS[entity_type]
        records = await self._conn.read(
            f"MATCH (n:{label}) RETURN n.id AS id, n.canonical_name AS canonical_name, "
            "n.aliases AS aliases, n.summary AS summary"
        )
        return [dict(r) for r in records]

    async def get(self, entity_id: str) -> dict | None:
        records = await self._conn.read(
            "MATCH (n {id: $id}) RETURN n.id AS id, n.canonical_name AS canonical_name, "
            "n.aliases AS aliases, n.summary AS summary, labels(n) AS labels",
            id=entity_id,
        )
        return dict(records[0]) if records else None


class EventRepository:
    def __init__(self, conn: Neo4jConnection) -> None:
        self._conn = conn

    async def upsert(self, event: HistoricalEvent) -> None:
        props = _flatten_for_neo4j(event.model_dump(mode="json", exclude={"id"}))
        await self._conn.write("MERGE (n:Event {id: $id}) SET n += $props", id=event.id, props=props)
        log.info("NEO4J", "Event upserted", name=event.name)

    async def find_candidates(self) -> list[dict]:
        records = await self._conn.read(
            "MATCH (n:Event) RETURN n.id AS id, n.name AS canonical_name, "
            "n.aliases AS aliases, n.description AS summary"
        )
        return [dict(r) for r in records]


class RelationshipRepository:
    def __init__(self, conn: Neo4jConnection) -> None:
        self._conn = conn

    async def upsert(self, rel: HistoricalRelationship) -> None:
        rel_type = rel.relationship_type.value
        props = _flatten_for_neo4j(
            rel.model_dump(mode="json", exclude={"id", "source_entity_id", "target_entity_id", "relationship_type"})
        )
        # `id` MUST be inside the MERGE pattern itself, never applied via SET
        # after a bare MERGE — otherwise idempotency breaks silently and
        # reruns duplicate edges (spec/03-architecture-spec.md).
        await self._conn.write(
            f"MATCH (s {{id: $source_id}}), (t {{id: $target_id}}) "
            f"MERGE (s)-[r:{rel_type} {{id: $rel_id}}]->(t) SET r += $props",
            source_id=rel.source_entity_id,
            target_id=rel.target_entity_id,
            rel_id=rel.id,
            props=props,
        )
        log.info("NEO4J", "Relationship created", type=rel_type)


class ClaimRepository:
    def __init__(self, conn: Neo4jConnection) -> None:
        self._conn = conn

    async def upsert(self, claim: HistoricalClaim) -> None:
        props = _flatten_for_neo4j(claim.model_dump(mode="json", exclude={"id", "subject_id", "object_id"}))
        await self._conn.write("MERGE (c:Claim {id: $id}) SET c += $props", id=claim.id, props=props)
        if claim.subject_id:
            rid = stable_relationship_id(claim.subject_id, "SUBJECT_OF", claim.id)
            await self._conn.write(
                "MATCH (s {id: $sid}), (c:Claim {id: $cid}) MERGE (s)-[:SUBJECT_OF {id: $rid}]->(c)",
                sid=claim.subject_id, cid=claim.id, rid=rid,
            )
        if claim.object_id:
            rid = stable_relationship_id(claim.id, "ABOUT", claim.object_id)
            await self._conn.write(
                "MATCH (c:Claim {id: $cid}), (o {id: $oid}) MERGE (c)-[:ABOUT {id: $rid}]->(o)",
                cid=claim.id, oid=claim.object_id, rid=rid,
            )
        log.info("NEO4J", "Claim upserted", predicate=claim.predicate)


class ChunkRepository:
    def __init__(self, conn: Neo4jConnection) -> None:
        self._conn = conn

    async def upsert(self, chunk: KnowledgeChunk) -> None:
        props = _flatten_for_neo4j(chunk.model_dump(mode="json", exclude={"id", "entity_ids"}))
        await self._conn.write("MERGE (c:Chunk {id: $id}) SET c += $props", id=chunk.id, props=props)
        for entity_id in chunk.entity_ids:
            rid = stable_relationship_id(chunk.id, "DESCRIBES", entity_id)
            await self._conn.write(
                "MATCH (c:Chunk {id: $cid}), (e {id: $eid}) MERGE (c)-[:DESCRIBES {id: $rid}]->(e)",
                cid=chunk.id, eid=entity_id, rid=rid,
            )
        log.info("EMBEDDING", "Chunk embedded and linked", chunk_type=chunk.chunk_type)


class IngestionRunRepository:
    def __init__(self, conn: Neo4jConnection) -> None:
        self._conn = conn

    async def save(self, run: IngestionRun) -> None:
        props = _flatten_for_neo4j(run.model_dump(mode="json", exclude={"id"}))
        await self._conn.write("MERGE (r:IngestionRun {id: $id}) SET r += $props", id=run.id, props=props)
