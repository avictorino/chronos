"""Vector index over :Chunk.embedding. See spec/04-neo4j-schema-spec.md."""

from __future__ import annotations

from app.config import Settings
from app.llm import EmbeddingClient
from app.persistence.neo4j import Neo4jConnection
from app.utils.logging import get_logger

log = get_logger("neo4j")

VECTOR_INDEX_NAME = "chunk_embedding_idx"

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


async def ensure_vector_index(conn: Neo4jConnection, dimension: int) -> None:
    existing = await conn.read(
        "SHOW VECTOR INDEXES YIELD name, options WHERE name = $name RETURN options",
        name=VECTOR_INDEX_NAME,
    )
    if existing:
        options = existing[0]["options"]
        existing_dim = (options or {}).get("indexConfig", {}).get("vector.dimensions")
        if existing_dim is not None and int(existing_dim) != dimension:
            raise RuntimeError(
                f"Vector index '{VECTOR_INDEX_NAME}' already exists with dimension "
                f"{existing_dim}, but the current embedding model produces "
                f"{dimension}-dim vectors. Changing OLLAMA_EMBEDDING_MODEL/"
                "OPENAI_EMBEDDING_MODEL after data was already ingested requires a "
                "manual migration (drop the index, re-embed, recreate) — see "
                "spec/06-acceptance-tests-spec.md."
            )
        return
    await conn.write(
        f"CREATE VECTOR INDEX {VECTOR_INDEX_NAME} IF NOT EXISTS "
        "FOR (c:Chunk) ON (c.embedding) "
        "OPTIONS {indexConfig: {`vector.dimensions`: $dim, `vector.similarity_function`: 'cosine'}}",
        dim=dimension,
    )
    log.info("NEO4J", "Vector index created", name=VECTOR_INDEX_NAME, dimension=dimension)
