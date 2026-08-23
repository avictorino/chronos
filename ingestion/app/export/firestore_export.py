"""One-way export of the knowledge graph from Postgres into Firestore.

Postgres remains the source of truth for the whole `ingestion/` pipeline —
nothing here changes that. This module only mirrors what's already there into
Firestore (free Spark plan) so the future `frontend/` can read the graph
directly, with no server in between: Firestore ends up holding the same
documents Postgres already has (see app/persistence/schema.py), plus a
denormalized `neighbor_ids` field on each entity (1-hop relationship
neighbors, computed here) and `chunks.embedding` stored as a native Firestore
`Vector` so `find_nearest` works client-side without pgvector.

Full-refresh, idempotent: every row already has a deterministic id (see
app/utils/ids.py), reused as the Firestore document id, so re-running this
after every `ingest --all` just overwrites documents in place — safe to run
as often as you like.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from google.cloud import firestore
from google.cloud.firestore_v1.vector import Vector

from app.config import Settings
from app.persistence.postgres import PostgresConnection, parse_vector
from app.utils.logging import get_logger

log = get_logger("firestore_export")

# Firestore hard-caps a batch at 500 writes; stay comfortably under that.
_BATCH_LIMIT = 400


def _build_client(settings: Settings) -> firestore.AsyncClient:
    if not settings.firebase_project_id:
        raise RuntimeError("FIREBASE_PROJECT_ID is not set — required for `export-firestore`.")
    # Credentials: GOOGLE_APPLICATION_CREDENTIALS (service-account JSON) if
    # set, otherwise ambient Application Default Credentials. Either way this
    # is the Admin SDK — only ever used from this script, never the frontend.
    return firestore.AsyncClient(project=settings.firebase_project_id)


async def _commit_documents(
    db: firestore.AsyncClient, collection: str, documents: dict[str, dict[str, Any]]
) -> int:
    items = list(documents.items())
    for start in range(0, len(items), _BATCH_LIMIT):
        batch = db.batch()
        for doc_id, payload in items[start : start + _BATCH_LIMIT]:
            batch.set(db.collection(collection).document(doc_id), payload)
        await batch.commit()
    return len(items)


async def _neighbor_ids(conn: PostgresConnection) -> dict[str, list[str]]:
    """1-hop relationship neighbors per entity — denormalized onto each
    entity document so the most common frontend query ("what's connected to
    this?") is a single document read, no query needed."""
    rows = await conn.fetch("SELECT source_id, target_id FROM relationships")
    neighbors: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        neighbors[row["source_id"]].add(row["target_id"])
        neighbors[row["target_id"]].add(row["source_id"])
    return {entity_id: sorted(ids) for entity_id, ids in neighbors.items()}


async def _export_entities(conn: PostgresConnection, db: firestore.AsyncClient) -> int:
    neighbor_ids = await _neighbor_ids(conn)
    rows = await conn.fetch("SELECT id, data FROM entities")
    documents = {}
    for row in rows:
        payload = dict(row["data"])
        payload["neighbor_ids"] = neighbor_ids.get(row["id"], [])
        documents[row["id"]] = payload
    return await _commit_documents(db, "entities", documents)


async def _export_events(conn: PostgresConnection, db: firestore.AsyncClient) -> int:
    rows = await conn.fetch("SELECT id, data FROM events")
    documents = {row["id"]: dict(row["data"]) for row in rows}
    return await _commit_documents(db, "events", documents)


async def _export_relationships(conn: PostgresConnection, db: firestore.AsyncClient) -> int:
    rows = await conn.fetch("SELECT id, data FROM relationships")
    documents = {row["id"]: dict(row["data"]) for row in rows}
    return await _commit_documents(db, "relationships", documents)


async def _export_claims(conn: PostgresConnection, db: firestore.AsyncClient) -> int:
    rows = await conn.fetch("SELECT id, data FROM claims")
    documents = {row["id"]: dict(row["data"]) for row in rows}
    return await _commit_documents(db, "claims", documents)


async def _export_chunks(conn: PostgresConnection, db: firestore.AsyncClient) -> int:
    # Cast embedding to text explicitly (no pgvector codec is registered on
    # this pool — see persistence/postgres.py) and reuse the existing
    # parse_vector() helper to turn it back into a plain list[float].
    rows = await conn.fetch("SELECT id, data, embedding::text AS embedding FROM chunks")
    documents = {}
    for row in rows:
        payload = dict(row["data"])
        embedding = parse_vector(row["embedding"])
        if embedding is not None:
            payload["embedding"] = Vector(embedding)
        documents[row["id"]] = payload
    return await _commit_documents(db, "chunks", documents)


async def _export_ingestion_runs(conn: PostgresConnection, db: firestore.AsyncClient) -> int:
    rows = await conn.fetch("SELECT id, data FROM ingestion_runs")
    documents = {row["id"]: dict(row["data"]) for row in rows}
    return await _commit_documents(db, "ingestion_runs", documents)


async def export_to_firestore(settings: Settings) -> dict[str, int]:
    """Reads every table already ingested into Postgres and overwrites the
    matching Firestore collections to match — a full-refresh mirror, not an
    incremental sync. Returns the document count written per collection."""
    conn = PostgresConnection(settings)
    await conn.verify_connectivity()
    db = _build_client(settings)
    try:
        counts = {
            "entities": await _export_entities(conn, db),
            "events": await _export_events(conn, db),
            "relationships": await _export_relationships(conn, db),
            "claims": await _export_claims(conn, db),
            "chunks": await _export_chunks(conn, db),
            "ingestion_runs": await _export_ingestion_runs(conn, db),
        }
        log.info("FIRESTORE", "Export complete", **counts)
        return counts
    finally:
        await conn.close()
