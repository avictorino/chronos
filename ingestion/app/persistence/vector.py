"""Sizes and indexes chunks.embedding. See spec/04-postgres-schema-spec.md.

Unlike Neo4j's vector index (created with an explicit dimension up front),
pgvector lets a column be declared as plain `vector` (no fixed length) — we
ALTER it to a fixed `vector(n)` once we know the embedding dimension, then add
an ANN index. Until that ALTER runs, similarity queries still work fine via a
full sequential scan; no premature optimization needed at V1 scale.
"""

from __future__ import annotations

from app.config import Settings
from app.llm import EmbeddingClient
from app.persistence.postgres import PostgresConnection
from app.utils.logging import get_logger

log = get_logger("postgres")

_dimension_cache: int | None = None


async def get_or_detect_dimension(settings: Settings, embedding_client: EmbeddingClient) -> int:
    """Dimension isn't hardcoded — detected empirically from the embedding model
    on first use (one throwaway embed call), unless overridden via .env."""
    global _dimension_cache
    if settings.embedding_dimensions:
        return settings.embedding_dimensions
    if _dimension_cache is None:
        [vector] = await embedding_client.embed(["dimension probe"])
        _dimension_cache = len(vector)
        log.info("EMBEDDING", "Detected embedding dimension", dimension=_dimension_cache)
    return _dimension_cache


async def ensure_vector_ready(conn: PostgresConnection, dimension: int) -> None:
    row = await conn.fetchrow(
        "SELECT format_type(atttypid, atttypmod) AS type "
        "FROM pg_attribute WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
    )
    current_type = row["type"] if row else None  # "vector(768)" once sized, "vector" until then

    if current_type and current_type != "vector":
        current_dim = int(current_type.removeprefix("vector(").removesuffix(")"))
        if current_dim != dimension:
            raise RuntimeError(
                f"chunks.embedding is already vector({current_dim}), but the current "
                f"embedding model produces {dimension}-dim vectors. Changing "
                "OLLAMA_EMBEDDING_MODEL/OPENAI_EMBEDDING_MODEL after data was already "
                "ingested requires a manual migration (ALTER the column, re-embed) — "
                "see spec/06-acceptance-tests-spec.md."
            )
        return

    await conn.execute(f"ALTER TABLE chunks ALTER COLUMN embedding TYPE vector({dimension})")
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx ON chunks USING hnsw (embedding vector_cosine_ops)"
    )
    log.info("POSTGRES", "chunks.embedding sized and indexed", dimension=dimension)
