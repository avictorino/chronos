from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- LLM provider ---
    llm_provider: str = "ollama"  # "ollama" | "openai"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma4:12b"
    ollama_embedding_model: str = "embeddinggemma"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"

    # Pending items sent to the LLM concurrently within one expansion-loop
    # iteration (asyncio.gather, not OS threads — see spec/03-architecture-spec.md).
    llm_concurrency: int = 1

    # --- Firestore (the only datastore — see app/persistence/firestore.py) ---
    # The pipeline used to persist to Postgres and mirror into Firestore via a
    # separate `export-firestore` step; it now writes directly to Firestore,
    # so these are required for `ingest` to persist anything (dry-run works
    # without them — see app/services/ingestion_service.py::_build_deps).
    firebase_project_id: str | None = None
    # Path to a service-account JSON key (Admin SDK). Leave unset to fall back
    # to ambient Application Default Credentials (e.g. `gcloud auth
    # application-default login`) instead.
    google_application_credentials: str | None = None

    # --- Ingestion limits ---
    # Per-civilization budgets, counted across *both* the initial discovery
    # batch and everything recursively queued afterwards (see
    # graph/nodes.py::_enqueue_mentions) — not just the first LLM call's output.
    max_events_per_civilization: int = 100
    max_people_per_civilization: int = 200
    max_places_per_civilization: int = 200
    max_polities_per_civilization: int = 20
    max_relationships_per_entity: int = 30
    # Hop count from the civilization root: an event/person/place discovered by
    # expanding something at depth d can recursively queue new candidates at
    # depth d+1, up to this cap (see graph/nodes.py::_route_after_stage).
    max_expansion_depth: int = 3

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
