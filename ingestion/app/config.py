from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- LLM provider ---
    llm_provider: str = "ollama"  # "ollama" | "openai"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:9b"
    ollama_embedding_model: str = "embeddinggemma"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"

    # Pending items sent to the LLM concurrently within one expansion-loop
    # iteration (asyncio.gather, not OS threads — see spec/03-architecture-spec.md).
    llm_concurrency: int = 1

    # --- Neo4j ---
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = "password"
    neo4j_database: str = "neo4j"

    # Vector index dimension override. None => auto-detect from the embedding
    # model at first use (see app/persistence/vector.py).
    embedding_dimensions: int | None = None

    # --- Ingestion limits (kept small by default so a run is cheap to test) ---
    max_events_per_civilization: int = 10
    max_people_per_civilization: int = 20
    max_places_per_civilization: int = 20
    max_relationships_per_entity: int = 30
    max_expansion_depth: int = 2

    # --- Entity resolution ---
    entity_resolution_use_llm: bool = False

    # --- LangGraph checkpointing ---
    ingestion_checkpoint_db_path: str = ".data/checkpoints.db"

    # --- Logging ---
    log_level: str = "INFO"

    @property
    def checkpoint_db_path(self) -> Path:
        path = Path(self.ingestion_checkpoint_db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    return Settings()
