"""LangGraph state + run-scoped dependency bundle.

`IngestionState` only carries mutable working data (see spec/03). Run
parameters (limits, dry_run, model name) and heavyweight/non-serializable
collaborators (LLM client, repositories, Firestore connection) live in
`GraphDeps`, threaded through `config["configurable"]["deps"]` — never inside
the checkpointed state itself.

Pending/processed items and accumulated entities/events/etc. are stored as
plain dicts (via `model_dump(mode="json")`), not live Pydantic instances, so
state stays trivially JSON-serializable for the SQLite checkpointer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from app.config import Settings
from app.llm import EmbeddingClient, LLMClient
from app.persistence.firestore import FirestoreConnection
from app.persistence.repositories import (
    ChunkRepository,
    ClaimRepository,
    EntityRepository,
    EventRepository,
    IngestionRunRepository,
    RelationshipRepository,
)


@dataclass
class GraphDeps:
    settings: Settings
    llm_client: LLMClient
    embedding_client: EmbeddingClient
    entity_repo: EntityRepository
    event_repo: EventRepository
    relationship_repo: RelationshipRepository
    claim_repo: ClaimRepository
    chunk_repo: ChunkRepository
    run_repo: IngestionRunRepository
    conn: FirestoreConnection | None
    run_id: str
    model_name: str
    dry_run: bool


class IngestionState(TypedDict):
    civilization_id: str
    civilization_seed: dict
    profile: dict | None

    pending_events: list[dict]
    processed_events: list[str]

    pending_people: list[dict]
    processed_people: list[str]
    # Set once discover_people has made its one-shot LLM discovery call —
    # guards against re-running it when the events/people/places loop revisits
    # the people stage for recursively-queued candidates. See
    # graph/nodes.py::_route_after_stage.
    people_discovery_done: bool

    pending_places: list[dict]
    processed_places: list[str]
    places_discovery_done: bool

    pending_polities: list[dict]
    processed_polities: list[str]
    polities_discovery_done: bool

    # Subjects for extract_relationships/generate_claims/generate_chunks —
    # populated incrementally by expand_events/expand_people/expand_places/
    # expand_polities and persist_civilization. Shape: {"id", "name", "kind",
    # "context", "dates"} — "dates" (a short best-effort timeframe hint, or
    # None) is threaded into build_relationship_extraction_prompt so
    # relationship dates stay grounded in what's already known about the
    # subject — see graph/nodes.py::_timeframe_hint/_person_dates_hint/_event_dates_hint.
    pending_relationship_subjects: list[dict]
    pending_claim_subjects: list[dict]
    pending_chunk_subjects: list[dict]

    # Names mentioned in relationships/claims that didn't resolve to any known
    # entity/event — resolved (or stubbed) by the final entity_resolution sweep.
    pending_unresolved_mentions: list[str]

    entities: dict[str, dict]
    events: dict[str, dict]
    relationships: dict[str, dict]
    claims: dict[str, dict]
    chunks: dict[str, dict]

    errors: list[dict]
