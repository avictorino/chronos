"""Batch-embeds chunks and persists them. Split out of
`graph/nodes.py::generate_embeddings` for the same reason as event_service.py.

No dimension pre-sizing needed here (unlike the old pgvector column, which
had to be `ALTER`ed to a fixed `vector(n)` once the embedding dimension was
known) — Firestore's native vector field doesn't require a declared size.
"""

from __future__ import annotations

from app.domain.models import IngestionError, KnowledgeChunk
from app.graph.state import GraphDeps
from app.utils.logging import get_logger

log = get_logger("embedding")


async def embed_and_persist_chunks(
    chunks: dict[str, dict], deps: GraphDeps, batch_size: int
) -> tuple[dict[str, dict], list[dict]]:
    """Returns (updated chunks with `embedding` populated, error dicts for any
    batch that failed — a failed batch is skipped, not fatal to the others)."""
    updated = dict(chunks)
    errors: list[dict] = []
    ids = list(chunks.keys())

    for start in range(0, len(ids), batch_size):
        batch_ids = ids[start : start + batch_size]
        batch_texts = [chunks[cid]["text"] for cid in batch_ids]
        try:
            vectors = await deps.embedding_client.embed(batch_texts)
        except Exception as exc:  # noqa: BLE001 - one bad batch shouldn't kill the run
            log.error("EMBEDDING", "Failed to embed a batch of chunks", error=str(exc))
            errors.append(
                IngestionError(
                    node="generate_embeddings", item=",".join(batch_ids), message=str(exc)
                ).model_dump(mode="json")
            )
            continue
        for chunk_id, vector in zip(batch_ids, vectors, strict=True):
            chunk_dict = dict(updated[chunk_id])
            chunk_dict["embedding"] = vector
            updated[chunk_id] = chunk_dict
            if not deps.dry_run:
                await deps.chunk_repo.upsert(KnowledgeChunk.model_validate(chunk_dict))

    return updated, errors
