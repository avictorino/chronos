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

import time

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
    # find_candidates() used to hit Firestore on every single call — cheap in
    # isolation, but _resolve_name_to_id (graph/nodes.py) calls it for every
    # EntityType against every relationship/claim source_name/target_name, so
    # one civilization's run could re-scan the same (growing) collection
    # hundreds of times. Measured in production: ~150 reads per write. A
    # short TTL cache per entity_type cuts that dramatically while still
    # refreshing periodically to see entities another concurrently-running
    # civilization (a sibling shard process — see ingestion/scripts/) just
    # created — see app/services/entity_resolution.py for why we can't just
    # trust in-memory-only state instead.
    # 45s was still too short once the collection grew into the hundreds of
    # docs: the cache cut refresh *frequency*, but each refresh re-scans the
    # whole (growing) collection, so cost per refresh climbs right along
    # with it — measured in production continuing to creep back up as
    # entities/events accumulated. _resolve_name_to_id already checks this
    # run's in-memory state first (see graph/nodes.py), so most calls never
    # reach here at all; a much longer TTL mainly trades a few extra minutes
    # of staleness for seeing a sibling shard process's new entities, which
    # is a soft nice-to-have (embedding/fuzzy resolution is already a
    # best-effort safety net, not a guarantee — see entity_resolution.py),
    # for a large cut in total read volume over a long-running batch.
    _CACHE_TTL_SECONDS = 600.0

    def __init__(self, conn: FirestoreConnection) -> None:
        self._conn = conn
        self._cache: dict[EntityType, tuple[float, list[dict]]] = {}
        self._all_cache: tuple[float, list[dict]] | None = None

    async def upsert(self, entity: AnyEntity) -> None:
        doc_ref = self._conn.db.collection("entities").document(entity.id)
        await doc_ref.set(_payload(entity), merge=True)
        log.info("FIRESTORE", "Entity upserted", entity_type=entity.entity_type.value, name=entity.canonical_name)
        row = {
            "id": entity.id,
            "canonical_name": entity.canonical_name,
            "aliases": entity.aliases,
            "summary": entity.summary,
        }
        self._cache_upsert(self._cache.get(entity.entity_type), row)
        self._cache_upsert(self._all_cache, row)

    @staticmethod
    def _cache_upsert(cached: tuple[float, list[dict]] | None, row: dict) -> None:
        if cached is None:
            return  # not cached yet — the next find_*() call fetches fresh anyway
        _, candidates = cached
        for i, existing in enumerate(candidates):
            if existing["id"] == row["id"]:
                candidates[i] = row
                return
        candidates.append(row)

    async def find_candidates(self, entity_type: EntityType) -> list[dict]:
        """Queries Firestore (never just in-memory state) — the only way to
        reuse entities discovered by a *previous* ingestion run of a
        different civilization (e.g. Judah/Babylon mentioned by Assyria) —
        but only re-fetches every `_CACHE_TTL_SECONDS`; upsert() keeps the
        cache current for entities created by *this* run in between."""
        cached = self._cache.get(entity_type)
        if cached is not None and (time.monotonic() - cached[0]) < self._CACHE_TTL_SECONDS:
            return list(cached[1])

        query = (
            self._conn.db.collection("entities")
            .where(filter=FieldFilter("entity_type", "==", entity_type.value))
            .select(["canonical_name", "aliases", "summary"])
        )
        docs = [doc async for doc in query.stream()]
        candidates = [
            {
                "id": doc.id,
                "canonical_name": data.get("canonical_name"),
                "aliases": data.get("aliases") or [],
                "summary": data.get("summary"),
            }
            for doc in docs
            if (data := doc.to_dict()) is not None
        ]
        self._cache[entity_type] = (time.monotonic(), candidates)
        return list(candidates)

    async def find_all_candidates(self) -> list[dict]:
        """Every entity regardless of type, in one query — used by
        graph/nodes.py::_resolve_name_to_id, which needs to check a bare
        mentioned name against every entity type at once (a relationship
        target could be a person, place, polity, document, concept, or even
        a civilization). Replaces what used to be up to 6 separate
        find_candidates() calls per name — measured in production as the
        single biggest source of Firestore read cost (~150 reads per write
        before this + the cache above). Same TTL-cache treatment."""
        if self._all_cache is not None and (time.monotonic() - self._all_cache[0]) < self._CACHE_TTL_SECONDS:
            return list(self._all_cache[1])

        query = self._conn.db.collection("entities").select(["canonical_name", "aliases", "summary"])
        docs = [doc async for doc in query.stream()]
        candidates = [
            {
                "id": doc.id,
                "canonical_name": data.get("canonical_name"),
                "aliases": data.get("aliases") or [],
                "summary": data.get("summary"),
            }
            for doc in docs
            if (data := doc.to_dict()) is not None
        ]
        self._all_cache = (time.monotonic(), candidates)
        return list(candidates)

    async def get(self, entity_id: str) -> dict | None:
        doc = await self._conn.db.collection("entities").document(entity_id).get()
        return doc.to_dict() if doc.exists else None


class EventRepository:
    # 45s was still too short once the collection grew into the hundreds of
    # docs: the cache cut refresh *frequency*, but each refresh re-scans the
    # whole (growing) collection, so cost per refresh climbs right along
    # with it — measured in production continuing to creep back up as
    # entities/events accumulated. _resolve_name_to_id already checks this
    # run's in-memory state first (see graph/nodes.py), so most calls never
    # reach here at all; a much longer TTL mainly trades a few extra minutes
    # of staleness for seeing a sibling shard process's new entities, which
    # is a soft nice-to-have (embedding/fuzzy resolution is already a
    # best-effort safety net, not a guarantee — see entity_resolution.py),
    # for a large cut in total read volume over a long-running batch.
    _CACHE_TTL_SECONDS = 600.0  # see EntityRepository — same reasoning

    def __init__(self, conn: FirestoreConnection) -> None:
        self._conn = conn
        self._cache: tuple[float, list[dict]] | None = None

    async def upsert(self, event: HistoricalEvent) -> None:
        doc_ref = self._conn.db.collection("events").document(event.id)
        await doc_ref.set(_payload(event), merge=True)
        log.info("FIRESTORE", "Event upserted", name=event.name)
        if self._cache is not None:
            _, candidates = self._cache
            row = {"id": event.id, "canonical_name": event.name, "aliases": event.aliases, "summary": event.description}
            for i, existing in enumerate(candidates):
                if existing["id"] == event.id:
                    candidates[i] = row
                    break
            else:
                candidates.append(row)

    async def find_candidates(self) -> list[dict]:
        if self._cache is not None and (time.monotonic() - self._cache[0]) < self._CACHE_TTL_SECONDS:
            return list(self._cache[1])

        query = self._conn.db.collection("events").select(["name", "aliases", "description"])
        docs = [doc async for doc in query.stream()]
        candidates = [
            {
                "id": doc.id,
                "canonical_name": data.get("name"),
                "aliases": data.get("aliases") or [],
                "summary": data.get("description"),
            }
            for doc in docs
            if (data := doc.to_dict()) is not None
        ]
        self._cache = (time.monotonic(), candidates)
        return list(candidates)


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
