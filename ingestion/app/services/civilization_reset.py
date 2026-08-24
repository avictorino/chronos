"""Deletes a civilization's own data from Firestore before a fresh
`ingest --civilization X` re-run (see `app/main.py::_cmd_ingest`) — so
re-ingesting the same civilization never just piles new documents on top of
stale ones from a previous run.

A document can legitimately be touched by more than one civilization's
ingestion run — cross-civilization entity dedup is deliberate (see
`app/services/entity_resolution.py`, e.g. Judah/Babylon mentioned by
Assyria) — tracked via the `source_civilizations` field every repository
upsert merges in (see `app/persistence/repositories.py`). So "delete
civilization X's data" isn't a blind collection wipe:
  - a document touched *only* by X is deleted outright.
  - a document also touched by another civilization is kept (that other
    civilization still depends on it) — only X's marker is removed via
    `ArrayRemove`. The fields that civilization X specifically contributed
    to a shared document aren't unwound field-by-field; this is a conscious
    limitation, acceptable because entity resolution already favors
    reconciling toward the best-available data on every run.

Not used by `ingest --all` (batch mode instead skips civilizations already
marked complete in `ingestion_runs` — see `app/main.py::_cmd_ingest` — so it
never needs to delete anything unless `--force` is passed).
"""

from __future__ import annotations

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.utils.logging import get_logger

log = get_logger("civilization_reset")

# Every collection whose documents carry `source_civilizations`. Deliberately
# excludes `ingestion_runs`, which is scoped by `civilization_id` directly
# instead (see _reset_ingestion_runs) — one run always belongs to exactly one
# civilization.
_SOURCE_TAGGED_COLLECTIONS = ["entities", "events", "relationships", "claims", "chunks"]

# Firestore hard-caps a batch at 500 writes; stay comfortably under that —
# same limit as the old firestore_export.py used.
_BATCH_LIMIT = 400


async def reset_civilization(db: firestore.AsyncClient, civilization_id: str) -> None:
    for collection in _SOURCE_TAGGED_COLLECTIONS:
        await _reset_collection(db, collection, civilization_id)
    await _reset_ingestion_runs(db, civilization_id)


async def _reset_collection(db: firestore.AsyncClient, collection: str, civilization_id: str) -> None:
    query = db.collection(collection).where(
        filter=FieldFilter("source_civilizations", "array_contains", civilization_id)
    )
    docs = [doc async for doc in query.stream()]
    if not docs:
        return

    deleted = 0
    kept_shared = 0
    for start in range(0, len(docs), _BATCH_LIMIT):
        batch = db.batch()
        for doc in docs[start : start + _BATCH_LIMIT]:
            data = doc.to_dict() or {}
            owners = data.get("source_civilizations") or []
            if list(owners) == [civilization_id]:
                batch.delete(doc.reference)
                deleted += 1
            else:
                # Shared with another civilization — keep the document, just
                # drop this civilization's ownership marker.
                batch.set(
                    doc.reference,
                    {"source_civilizations": firestore.ArrayRemove([civilization_id])},
                    merge=True,
                )
                kept_shared += 1
        await batch.commit()
    log.info("RESET", f"{collection}: cleared previous data for {civilization_id}", deleted=deleted, kept_shared=kept_shared)


async def _reset_ingestion_runs(db: firestore.AsyncClient, civilization_id: str) -> None:
    query = db.collection("ingestion_runs").where(filter=FieldFilter("civilization_id", "==", civilization_id))
    docs = [doc async for doc in query.stream()]
    if not docs:
        return
    for start in range(0, len(docs), _BATCH_LIMIT):
        batch = db.batch()
        for doc in docs[start : start + _BATCH_LIMIT]:
            batch.delete(doc.reference)
        await batch.commit()
    log.info("RESET", f"ingestion_runs: cleared previous runs for {civilization_id}", deleted=len(docs))


async def civilization_already_imported(db: firestore.AsyncClient, civilization_id: str) -> bool:
    """True if a completed ingestion run already exists for this
    civilization — the ledger `ingest --all` uses to skip already-imported
    civilizations and resume a batch after a crash (see
    `app/main.py::_cmd_ingest`). Reuses `ingestion_runs`, already written by
    `app/graph/nodes.py::persist_graph` at the end of every successful
    run — no new storage primitive needed."""
    query = (
        db.collection("ingestion_runs")
        .where(filter=FieldFilter("civilization_id", "==", civilization_id))
        .where(filter=FieldFilter("status", "==", "completed"))
        .limit(1)
    )
    docs = [doc async for doc in query.stream()]
    return bool(docs)
