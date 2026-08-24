"""Domain mapping + persistence orchestration for a single expanded event.

Split out of `graph/nodes.py::expand_events` so that node stays focused on
loop/Command control flow (phase A/B batching, per-item error isolation) while
this holds the actual "map LLM output -> domain model -> resolve -> persist"
logic — a real separation of concerns, not a pass-through wrapper.
"""

from __future__ import annotations

from app.domain.models import HistoricalEvent
from app.domain.schemas import EventExpansion
from app.graph.state import GraphDeps
from app.services.entity_resolution import resolve_entity
from app.utils.ids import stable_event_id
from app.utils.logging import get_logger

log = get_logger("event")


async def resolve_and_persist_event(result: EventExpansion, deps: GraphDeps, civilization_id: str) -> HistoricalEvent:
    existing = await deps.event_repo.find_candidates()
    resolution = await resolve_entity(
        result.name,
        result.aliases,
        existing,
        deps.embedding_client,
        deps.llm_client,
        deps.settings.entity_resolution_use_llm,
        require_embedding_confirmation=True,
    )
    event_id = stable_event_id(result.event_type, result.name)
    if resolution.action == "merge" and resolution.existing_entity_id:
        event_id = resolution.existing_entity_id
        log.info(
            "ENTITY",
            "Existing event found",
            candidate=result.name,
            existing_id=resolution.existing_entity_id,
            confidence=round(resolution.confidence, 2),
            reason=resolution.reason,
        )

    event = HistoricalEvent(
        id=event_id,
        name=result.name,
        event_type=result.event_type,
        description=result.description,
        date=result.date,
        people=result.people,
        places=result.places,
        polities=result.polities,
        causes=result.causes,
        consequences=result.consequences,
        aliases=result.aliases,
        confidence=result.confidence,
        generated_by_model=deps.model_name,
        ingestion_run_id=deps.run_id,
        source_civilizations=[civilization_id],
    )
    if not deps.dry_run:
        await deps.event_repo.upsert(event)
    return event
