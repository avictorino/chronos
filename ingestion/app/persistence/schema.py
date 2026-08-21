"""Constraints and auxiliary indexes. See spec/04-neo4j-schema-spec.md."""

from __future__ import annotations

from app.persistence.neo4j import Neo4jConnection
from app.utils.logging import get_logger

log = get_logger("neo4j")

# Every persisted label carries a uniqueness constraint on the stable `id`
# (never the raw name) — this is what makes `MERGE` idempotent.
_UNIQUE_ID_LABELS = [
    "Civilization",
    "Person",
    "Place",
    "Polity",
    "Document",
    "Concept",
    "Event",
    "Claim",
    "Chunk",
    "IngestionRun",
]

# Range index on canonical_name for the labels entity_resolution queries most.
_NAME_INDEX_LABELS = ["Person", "Place", "Polity"]


async def ensure_constraints(conn: Neo4jConnection) -> None:
    for label in _UNIQUE_ID_LABELS:
        await conn.write(
            f"CREATE CONSTRAINT {label.lower()}_id_unique IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.id IS UNIQUE"
        )
    for label in _NAME_INDEX_LABELS:
        await conn.write(
            f"CREATE INDEX {label.lower()}_name_idx IF NOT EXISTS "
            f"FOR (n:{label}) ON (n.canonical_name)"
        )
    log.info("NEO4J", "Constraints and indexes ensured")
