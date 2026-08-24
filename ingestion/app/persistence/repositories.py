"""Repositories — one per persisted shape, all Firestore `set(..., merge=True)`
(idempotent, same deterministic-id design as the rest of the app).

`EntityRepository` covers every `AnyEntity` subclass (Civilization, Person,
Place, Polity, Document, Concept) uniformly — they all land in one `entities`
collection distinguished by `entity_type`, rather than one repository/
collection per subtype (spec/01: simplicity over abstraction).

`merge=True` everywhere is deliberate, not just idempotency: the `entities`
collection also carries `image_url`/`image_status`/`image_generated_at`/
`image_model`/`image_prompt_version`, written directly by the on-demand
image-generation Cloud Function (`frontend/functions/index.js`) and never
known to this pipeline. A plain overwrite would wipe those fields out on
every re-ingestion. `source_civilizations` (which civilization run(s) touched
this document — see `app/services/civilization_reset.py`) and, on entities,
`neighbor_ids` (1-hop relationship neighbors) are merged via `ArrayUnion`
rather than overwritten, for the same reason: a document can legitimately be
touched by more than one civilization's ingestion run.
"""

from __future__ import annotations

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.vector import Vector

from app.domain.enums import EntityType
from app.domain.models import (
    AnyEntity,
    HistoricalClaim,
    HistoricalEvent,
    HistoricalRelationship,
    IngestionRun,
    KnowledgeChunk,
)
from app.persistence.firestore import FirestoreConnection
from app.utils.logging import get_logger

log = get_logger("firestore")


def _payload(model, *, extra: dict | None = None) -> dict:
    """Common shape for every write: the full model dump, with
    `source_civilizations` merged (not overwritten) via ArrayUnion."""
    data = model.model_dump(mode="json")
    source_civilizations = data.pop("source_civilizations", [])
    data["source_civilizations"] = firestore.ArrayUnion(source_civilizations) if source_civilizations else []
    if extra:
        data.update(extra)
    return data


class EntityRepository:
    def __init__(self, conn: FirestoreConnection) -> None:
        self._conn = conn

    async def upsert(self, entity: AnyEntity) -> None:
        doc_ref = self._conn.db.collection("entities").document(entity.id)
        await doc_ref.set(_payload(entity), merge=True)
        log.info("FIRESTORE", "Entity upserted", entity_type=entity.entity_type.value, name=entity.canonical_name)

    async def find_candidates(self, entity_type: EntityType) -> list[dict]:
        """Always queries Firestore (never just in-memory state) — the only
        way to reuse entities discovered by a *previous* ingestion run of a
        different civilization (e.g. Judah/Babylon mentioned by Assyria)."""
        query = (
            self._conn.db.collection("entities")
            .where(filter=FieldFilter("entity_type", "==", entity_type.value))
            .select(["canonical_name", "aliases", "summary"])
        )
        docs = [doc async for doc in query.stream()]
        return [
            {
                "id": doc.id,
                "canonical_name": data.get("canonical_name"),
                "aliases": data.get("aliases") or [],
                "summary": data.get("summary"),
            }
            for doc in docs
            if (data := doc.to_dict()) is not None
        ]

    async def get(self, entity_id: str) -> dict | None:
        doc = await self._conn.db.collection("entities").document(entity_id).get()
        return doc.to_dict() if doc.exists else None


class EventRepository:
    def __init__(self, conn: FirestoreConnection) -> None:
        self._conn = conn

    async def upsert(self, event: HistoricalEvent) -> None:
        doc_ref = self._conn.db.collection("events").document(event.id)
        await doc_ref.set(_payload(event), merge=True)
        log.info("FIRESTORE", "Event upserted", name=event.name)

    async def find_candidates(self) -> list[dict]:
        query = self._conn.db.collection("events").select(["name", "aliases", "description"])
        docs = [doc async for doc in query.stream()]
        return [
            {
                "id": doc.id,
                "canonical_name": data.get("name"),
                "aliases": data.get("aliases") or [],
                "summary": data.get("description"),
            }
            for doc in docs
            if (data := doc.to_dict()) is not None
        ]


class RelationshipRepository:
    def __init__(self, conn: FirestoreConnection) -> None:
        self._conn = conn

    async def upsert(self, rel: HistoricalRelationship) -> None:
        db = self._conn.db
        batch = db.batch()
        batch.set(db.collection("relationships").document(rel.id), _payload(rel), merge=True)
        # Denormalized 1-hop neighbors on both sides — the most common
        # frontend query ("what's connected to this?") becomes a single
        # document read, no query needed. Maintained incrementally here
        # instead of a separate post-processing export pass.
        batch.set(
            db.collection("entities").document(rel.source_entity_id),
            {"neighbor_ids": firestore.ArrayUnion([rel.target_entity_id])},
            merge=True,
        )
        batch.set(
            db.collection("entities").document(rel.target_entity_id),
            {"neighbor_ids": firestore.ArrayUnion([rel.source_entity_id])},
            merge=True,
        )
        await batch.commit()
        log.info("FIRESTORE", "Relationship created", type=rel.relationship_type.value)


class ClaimRepository:
    def __init__(self, conn: FirestoreConnection) -> None:
        self._conn = conn

    async def upsert(self, claim: HistoricalClaim) -> None:
        doc_ref = self._conn.db.collection("claims").document(claim.id)
        await doc_ref.set(_payload(claim), merge=True)
        log.info("FIRESTORE", "Claim upserted", predicate=claim.predicate)


class ChunkRepository:
    def __init__(self, conn: FirestoreConnection) -> None:
        self._conn = conn

    async def upsert(self, chunk: KnowledgeChunk) -> None:
        payload = _payload(chunk)
        if chunk.embedding is not None:
            payload["embedding"] = Vector(chunk.embedding)
        doc_ref = self._conn.db.collection("chunks").document(chunk.id)
        await doc_ref.set(payload, merge=True)
        log.info("EMBEDDING", "Chunk embedded and linked", chunk_type=chunk.chunk_type)


class IngestionRunRepository:
    def __init__(self, conn: FirestoreConnection) -> None:
        self._conn = conn

    async def save(self, run: IngestionRun) -> None:
        doc_ref = self._conn.db.collection("ingestion_runs").document(run.id)
        # ingestion_runs isn't touched by more than one civilization by
        # design (see civilization_id below) — plain overwrite is fine, but
        # merge=True costs nothing and keeps the same pattern as everything
        # else in this module.
        await doc_ref.set(run.model_dump(mode="json"), merge=True)
