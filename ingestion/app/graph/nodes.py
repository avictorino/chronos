"""LangGraph node functions.

Discovery nodes (`discover_events`/`discover_people`/`discover_places`) and
the two finishing nodes (`generate_chunks`, `generate_embeddings`,
`persist_graph`) return plain dict updates and use static edges.

Expansion/extraction nodes (`expand_events`, `expand_people`, `expand_places`,
`extract_relationships`, `generate_claims`) return `Command` and self-loop:
each call processes a batch of up to `LLM_CONCURRENCY` pending items — the LLM
calls in that batch run concurrently via `asyncio.gather` (phase A), then
entity resolution + persistence + state bookkeeping for the batch happen
strictly sequentially, in order (phase B) — see spec/03-architecture-spec.md
for why that split exists (resolve-then-write is not atomic, so it can't be
parallelized without risking duplicate entities).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import TypeVar

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from app.domain.enums import EntityType
from app.domain.models import (
    AnyEntity,
    Civilization,
    Concept,
    Document,
    HistoricalClaim,
    HistoricalRelationship,
    IngestionError,
    IngestionRun,
    KnowledgeChunk,
    Person,
    Place,
    Polity,
)
from app.domain.schemas import (
    ChunkDraftList,
    CivilizationProfile,
    CivilizationSeed,
    ClaimCandidateList,
    EventCandidate,
    EventCandidateList,
    EventExpansion,
    OrphanEntityGuess,
    PersonCandidate,
    PersonCandidateList,
    PersonProfile,
    PlaceCandidate,
    PlaceCandidateList,
    PlaceProfile,
    RelationshipCandidateList,
)
from app.graph.state import GraphDeps, IngestionState
from app.llm import (
    build_chunk_generation_prompt,
    build_civilization_profile_prompt,
    build_claim_generation_prompt,
    build_event_discovery_prompt,
    build_event_expansion_prompt,
    build_orphan_entity_type_prompt,
    build_person_discovery_prompt,
    build_person_expansion_prompt,
    build_place_discovery_prompt,
    build_place_expansion_prompt,
    build_relationship_extraction_prompt,
)
from app.services.embedding_service import ensure_index_ready, embed_and_persist_chunks
from app.services.entity_resolution import resolve_entity
from app.services.event_service import resolve_and_persist_event
from app.utils.ids import (
    stable_chunk_id,
    stable_claim_id,
    stable_entity_id,
    stable_relationship_id,
)
from app.utils.logging import get_logger

log = get_logger("graph")

T = TypeVar("T")
R = TypeVar("R")


def _deps(config: RunnableConfig) -> GraphDeps:
    return config["configurable"]["deps"]


async def _gather_batch(
    items: list[T], concurrency: int, call: Callable[[T], Awaitable[R]]
) -> tuple[list[tuple[T, R | BaseException]], list[T]]:
    """Phase A: pop up to `concurrency` items, run `call` on them concurrently."""
    batch = items[: max(1, concurrency)]
    rest = items[len(batch) :]
    results = await asyncio.gather(*(call(item) for item in batch), return_exceptions=True)
    return list(zip(batch, results, strict=True)), rest


def _error(node: str, item: str, exc: BaseException) -> dict:
    log.error(node.upper(), f"Item failed: {item}", error=str(exc))
    return IngestionError(node=node, item=item, message=str(exc)).model_dump(mode="json")


def _log_resolution_merge(candidate_name: str, resolution) -> None:  # noqa: ANN001 - EntityResolutionResult
    log.info(
        "ENTITY",
        "Existing entity found",
        candidate=candidate_name,
        existing_id=resolution.existing_entity_id,
        confidence=round(resolution.confidence, 2),
        reason=resolution.reason,
    )


# --- linear nodes --------------------------------------------------------------


async def load_civilization(state: IngestionState, config: RunnableConfig) -> dict:
    deps = _deps(config)
    seed = CivilizationSeed.model_validate(state["civilization_seed"])
    log.info("INGESTION", f"Starting {seed.name}", run_id=deps.run_id, dry_run=deps.dry_run)
    return {}


async def extract_civilization_profile(state: IngestionState, config: RunnableConfig) -> dict:
    deps = _deps(config)
    seed = CivilizationSeed.model_validate(state["civilization_seed"])
    log.info("LLM", "Extracting civilization profile", civilization=seed.name)
    prompt = build_civilization_profile_prompt(seed)
    profile = await deps.llm_client.generate_structured(prompt, CivilizationProfile)
    return {"profile": profile.model_dump(mode="json")}


async def persist_civilization(state: IngestionState, config: RunnableConfig) -> dict:
    deps = _deps(config)
    profile = CivilizationProfile.model_validate(state["profile"])
    civilization = Civilization(
        id=stable_entity_id(EntityType.CIVILIZATION, profile.canonical_name),
        canonical_name=profile.canonical_name,
        aliases=profile.alternative_names,
        summary=profile.summary,
        start_year=profile.start_year,
        end_year=profile.end_year,
        generated_by_model=deps.model_name,
        ingestion_run_id=deps.run_id,
    )
    if not deps.dry_run:
        await deps.entity_repo.upsert(civilization)
        log.info("POSTGRES", "Civilization persisted", name=civilization.canonical_name)
    else:
        log.info("LLM", "Civilization profile extracted (dry-run, not persisted)", name=civilization.canonical_name)

    subject = {
        "id": civilization.id,
        "name": civilization.canonical_name,
        "kind": "civilization",
        "context": civilization.summary or "",
    }
    return {
        "entities": {**state["entities"], civilization.id: civilization.model_dump(mode="json")},
        "pending_chunk_subjects": [*state["pending_chunk_subjects"], subject],
    }


async def discover_events(state: IngestionState, config: RunnableConfig) -> dict:
    deps = _deps(config)
    profile = CivilizationProfile.model_validate(state["profile"])
    log.info("LLM", "Discovering events", civilization=profile.canonical_name)
    prompt = build_event_discovery_prompt(profile, deps.settings.max_events_per_civilization)
    result = await deps.llm_client.generate_structured(prompt, EventCandidateList)
    items = result.items[: deps.settings.max_events_per_civilization]
    log.info("LLM", f"Found {len(items)} candidate events")
    return {"pending_events": [c.model_dump(mode="json") for c in items], "processed_events": []}


async def discover_people(state: IngestionState, config: RunnableConfig) -> dict:
    deps = _deps(config)
    profile = CivilizationProfile.model_validate(state["profile"])
    event_names = [e["name"] for e in state["events"].values()]
    log.info("LLM", "Discovering people", civilization=profile.canonical_name)
    prompt = build_person_discovery_prompt(profile, event_names, deps.settings.max_people_per_civilization)
    result = await deps.llm_client.generate_structured(prompt, PersonCandidateList)
    items = result.items[: deps.settings.max_people_per_civilization]
    log.info("LLM", f"Found {len(items)} candidate people")
    return {"pending_people": [c.model_dump(mode="json") for c in items], "processed_people": []}


async def discover_places(state: IngestionState, config: RunnableConfig) -> dict:
    deps = _deps(config)
    profile = CivilizationProfile.model_validate(state["profile"])
    event_names = [e["name"] for e in state["events"].values()]
    person_names = [
        e["canonical_name"] for e in state["entities"].values() if e.get("entity_type") == "PERSON"
    ]
    log.info("LLM", "Discovering places", civilization=profile.canonical_name)
    prompt = build_place_discovery_prompt(
        profile, event_names, person_names, deps.settings.max_places_per_civilization
    )
    result = await deps.llm_client.generate_structured(prompt, PlaceCandidateList)
    items = result.items[: deps.settings.max_places_per_civilization]
    log.info("LLM", f"Found {len(items)} candidate places")
    return {"pending_places": [c.model_dump(mode="json") for c in items], "processed_places": []}


# --- self-looping expansion nodes -----------------------------------------------


async def expand_events(state: IngestionState, config: RunnableConfig) -> Command:
    deps = _deps(config)
    pending = state["pending_events"]
    if not pending:
        return Command(goto="discover_people")

    profile = CivilizationProfile.model_validate(state["profile"])

    async def call(candidate_dict: dict) -> EventExpansion:
        candidate = EventCandidate.model_validate(candidate_dict)
        prompt = build_event_expansion_prompt(candidate.name, candidate.event_type, profile.canonical_name)
        return await deps.llm_client.generate_structured(prompt, EventExpansion)

    batch, rest = await _gather_batch(pending, deps.settings.llm_concurrency, call)

    events = dict(state["events"])
    processed = list(state["processed_events"])
    errors = list(state["errors"])
    relationship_subjects = list(state["pending_relationship_subjects"])
    claim_subjects = list(state["pending_claim_subjects"])
    chunk_subjects = list(state["pending_chunk_subjects"])

    for candidate_dict, result in batch:
        candidate = EventCandidate.model_validate(candidate_dict)
        if isinstance(result, BaseException):
            errors.append(_error("expand_events", candidate.name, result))
            continue
        try:
            log.info("EVENT", f"Processing {candidate.name}")
            event = await resolve_and_persist_event(result, deps)
            events[event.id] = event.model_dump(mode="json")
            processed.append(event.id)
            subject = {"id": event.id, "name": event.name, "kind": "event", "context": event.description}
            relationship_subjects.append(subject)
            claim_subjects.append(subject)
            chunk_subjects.append(subject)
        except Exception as exc:  # noqa: BLE001 - isolate per-item failure, keep looping
            errors.append(_error("expand_events", candidate.name, exc))

    update = {
        "events": events,
        "processed_events": processed,
        "pending_events": rest,
        "errors": errors,
        "pending_relationship_subjects": relationship_subjects,
        "pending_claim_subjects": claim_subjects,
        "pending_chunk_subjects": chunk_subjects,
    }
    return Command(update=update, goto="expand_events" if rest else "discover_people")


async def expand_people(state: IngestionState, config: RunnableConfig) -> Command:
    deps = _deps(config)
    pending = state["pending_people"]
    if not pending:
        return Command(goto="discover_places")

    profile = CivilizationProfile.model_validate(state["profile"])

    async def call(candidate_dict: dict) -> PersonProfile:
        candidate = PersonCandidate.model_validate(candidate_dict)
        prompt = build_person_expansion_prompt(candidate.name, profile.canonical_name)
        return await deps.llm_client.generate_structured(prompt, PersonProfile)

    batch, rest = await _gather_batch(pending, deps.settings.llm_concurrency, call)

    entities = dict(state["entities"])
    processed = list(state["processed_people"])
    errors = list(state["errors"])
    relationship_subjects = list(state["pending_relationship_subjects"])
    claim_subjects = list(state["pending_claim_subjects"])
    chunk_subjects = list(state["pending_chunk_subjects"])

    for candidate_dict, result in batch:
        candidate = PersonCandidate.model_validate(candidate_dict)
        if isinstance(result, BaseException):
            errors.append(_error("expand_people", candidate.name, result))
            continue
        try:
            log.info("ENTITY", f"Resolving {result.canonical_name}")
            existing = await deps.entity_repo.find_candidates(EntityType.PERSON)
            resolution = await resolve_entity(
                result.canonical_name,
                result.aliases,
                existing,
                deps.embedding_client,
                deps.llm_client,
                deps.settings.entity_resolution_use_llm,
            )
            person_id = stable_entity_id(EntityType.PERSON, result.canonical_name)
            if resolution.action == "merge" and resolution.existing_entity_id:
                person_id = resolution.existing_entity_id
                _log_resolution_merge(result.canonical_name, resolution)
            person = Person(
                id=person_id,
                canonical_name=result.canonical_name,
                aliases=result.aliases,
                summary=result.summary,
                titles=result.titles,
                birth_date=result.birth_date,
                death_date=result.death_date,
                confidence=result.confidence,
                generated_by_model=deps.model_name,
                ingestion_run_id=deps.run_id,
            )
            if not deps.dry_run:
                await deps.entity_repo.upsert(person)
            entities[person.id] = person.model_dump(mode="json")
            processed.append(person.id)
            subject = {
                "id": person.id,
                "name": person.canonical_name,
                "kind": "person",
                "context": person.summary or "",
            }
            relationship_subjects.append(subject)
            claim_subjects.append(subject)
            chunk_subjects.append(subject)
        except Exception as exc:  # noqa: BLE001
            errors.append(_error("expand_people", candidate.name, exc))

    update = {
        "entities": entities,
        "processed_people": processed,
        "pending_people": rest,
        "errors": errors,
        "pending_relationship_subjects": relationship_subjects,
        "pending_claim_subjects": claim_subjects,
        "pending_chunk_subjects": chunk_subjects,
    }
    return Command(update=update, goto="expand_people" if rest else "discover_places")


async def expand_places(state: IngestionState, config: RunnableConfig) -> Command:
    deps = _deps(config)
    pending = state["pending_places"]
    if not pending:
        return Command(goto="extract_relationships")

    profile = CivilizationProfile.model_validate(state["profile"])

    async def call(candidate_dict: dict) -> PlaceProfile:
        candidate = PlaceCandidate.model_validate(candidate_dict)
        prompt = build_place_expansion_prompt(candidate.name, profile.canonical_name)
        return await deps.llm_client.generate_structured(prompt, PlaceProfile)

    batch, rest = await _gather_batch(pending, deps.settings.llm_concurrency, call)

    entities = dict(state["entities"])
    processed = list(state["processed_places"])
    errors = list(state["errors"])
    relationship_subjects = list(state["pending_relationship_subjects"])
    claim_subjects = list(state["pending_claim_subjects"])
    chunk_subjects = list(state["pending_chunk_subjects"])

    for candidate_dict, result in batch:
        candidate = PlaceCandidate.model_validate(candidate_dict)
        if isinstance(result, BaseException):
            errors.append(_error("expand_places", candidate.name, result))
            continue
        try:
            log.info("ENTITY", f"Resolving {result.canonical_name}")
            existing = await deps.entity_repo.find_candidates(result.place_kind)
            resolution = await resolve_entity(
                result.canonical_name,
                result.aliases,
                existing,
                deps.embedding_client,
                deps.llm_client,
                deps.settings.entity_resolution_use_llm,
            )
            place_id = stable_entity_id(result.place_kind, result.canonical_name)
            if resolution.action == "merge" and resolution.existing_entity_id:
                place_id = resolution.existing_entity_id
                _log_resolution_merge(result.canonical_name, resolution)
            place = Place(
                id=place_id,
                entity_type=result.place_kind,
                canonical_name=result.canonical_name,
                aliases=result.aliases,
                summary=result.summary,
                latitude=result.latitude,
                longitude=result.longitude,
                modern_country=result.modern_country,
                ancient_region=result.ancient_region,
                coordinate_origin="llm_generated" if result.latitude is not None else None,
                confidence=result.confidence,
                generated_by_model=deps.model_name,
                ingestion_run_id=deps.run_id,
            )
            if not deps.dry_run:
                await deps.entity_repo.upsert(place)
            entities[place.id] = place.model_dump(mode="json")
            processed.append(place.id)
            subject = {
                "id": place.id,
                "name": place.canonical_name,
                "kind": "place",
                "context": place.summary or "",
            }
            relationship_subjects.append(subject)
            claim_subjects.append(subject)
            chunk_subjects.append(subject)
        except Exception as exc:  # noqa: BLE001
            errors.append(_error("expand_places", candidate.name, exc))

    update = {
        "entities": entities,
        "processed_places": processed,
        "pending_places": rest,
        "errors": errors,
        "pending_relationship_subjects": relationship_subjects,
        "pending_claim_subjects": claim_subjects,
        "pending_chunk_subjects": chunk_subjects,
    }
    return Command(update=update, goto="expand_places" if rest else "extract_relationships")


# --- name resolution shared by extract_relationships/generate_claims -----------

_NAME_RESOLUTION_TYPES = [
    EntityType.PERSON,
    EntityType.PLACE,
    EntityType.POLITY,
    EntityType.DOCUMENT,
    EntityType.CONCEPT,
]


async def _resolve_name_to_id(name: str, state: IngestionState, deps: GraphDeps) -> str | None:
    """Resolves a bare name (as mentioned in a relationship/claim) to an
    already-known entity/event id. Checks this run's in-memory state first
    (cheap), then falls back to Postgres across the likely entity types plus
    events. Returns None if nothing sufficiently similar is found — the
    caller queues the name for the final `entity_resolution` stub sweep."""
    needle = name.strip().lower()
    if not needle:
        return None

    for entity in state["entities"].values():
        pool = [entity["canonical_name"], *entity.get("aliases", [])]
        if any(p.strip().lower() == needle for p in pool):
            return entity["id"]
    for event in state["events"].values():
        pool = [event["name"], *event.get("aliases", [])]
        if any(p.strip().lower() == needle for p in pool):
            return event["id"]

    for entity_type in _NAME_RESOLUTION_TYPES:
        candidates = await deps.entity_repo.find_candidates(entity_type)
        if not candidates:
            continue
        resolution = await resolve_entity(name, [], candidates, deps.embedding_client, deps.llm_client)
        if resolution.action == "merge" and resolution.existing_entity_id:
            return resolution.existing_entity_id

    event_candidates = await deps.event_repo.find_candidates()
    if event_candidates:
        resolution = await resolve_entity(
            name, [], event_candidates, deps.embedding_client, deps.llm_client, require_embedding_confirmation=True
        )
        if resolution.action == "merge" and resolution.existing_entity_id:
            return resolution.existing_entity_id

    return None


async def extract_relationships(state: IngestionState, config: RunnableConfig) -> Command:
    deps = _deps(config)
    pending = state["pending_relationship_subjects"]
    if not pending:
        return Command(goto="generate_claims")

    async def call(subject: dict) -> RelationshipCandidateList:
        prompt = build_relationship_extraction_prompt(subject["name"], subject["context"])
        return await deps.llm_client.generate_structured(prompt, RelationshipCandidateList)

    batch, rest = await _gather_batch(pending, deps.settings.llm_concurrency, call)

    relationships = dict(state["relationships"])
    errors = list(state["errors"])
    unresolved = list(state["pending_unresolved_mentions"])

    for subject, result in batch:
        if isinstance(result, BaseException):
            errors.append(_error("extract_relationships", subject["name"], result))
            continue
        for candidate in result.items[: deps.settings.max_relationships_per_entity]:
            try:
                source_id = await _resolve_name_to_id(candidate.source_name, state, deps)
                target_id = await _resolve_name_to_id(candidate.target_name, state, deps)
                if source_id is None:
                    unresolved.append(candidate.source_name)
                if target_id is None:
                    unresolved.append(candidate.target_name)
                if source_id is None or target_id is None:
                    continue
                rel = HistoricalRelationship(
                    id=stable_relationship_id(source_id, candidate.relationship_type.value, target_id),
                    source_entity_id=source_id,
                    target_entity_id=target_id,
                    relationship_type=candidate.relationship_type,
                    description=candidate.description,
                    start_year=candidate.start_year,
                    end_year=candidate.end_year,
                    confidence=candidate.confidence,
                    generated_by_model=deps.model_name,
                    ingestion_run_id=deps.run_id,
                )
                if not deps.dry_run:
                    await deps.relationship_repo.upsert(rel)
                relationships[rel.id] = rel.model_dump(mode="json")
            except Exception as exc:  # noqa: BLE001
                errors.append(_error("extract_relationships", subject["name"], exc))

    update = {
        "relationships": relationships,
        "pending_relationship_subjects": rest,
        "errors": errors,
        "pending_unresolved_mentions": unresolved,
    }
    return Command(update=update, goto="extract_relationships" if rest else "generate_claims")


async def generate_claims(state: IngestionState, config: RunnableConfig) -> Command:
    deps = _deps(config)
    pending = state["pending_claim_subjects"]
    if not pending:
        return Command(goto="entity_resolution")

    async def call(subject: dict) -> ClaimCandidateList:
        prompt = build_claim_generation_prompt(subject["name"], subject["context"])
        return await deps.llm_client.generate_structured(prompt, ClaimCandidateList)

    batch, rest = await _gather_batch(pending, deps.settings.llm_concurrency, call)

    claims = dict(state["claims"])
    errors = list(state["errors"])
    unresolved = list(state["pending_unresolved_mentions"])

    for subject, result in batch:
        if isinstance(result, BaseException):
            errors.append(_error("generate_claims", subject["name"], result))
            continue
        for candidate in result.items:
            try:
                object_id = None
                if candidate.object_name:
                    object_id = await _resolve_name_to_id(candidate.object_name, state, deps)
                    if object_id is None:
                        unresolved.append(candidate.object_name)
                claim = HistoricalClaim(
                    id=stable_claim_id(subject["id"], candidate.predicate, object_id, candidate.statement),
                    subject_id=subject["id"],
                    predicate=candidate.predicate,
                    object_id=object_id,
                    statement=candidate.statement,
                    estimated_date=candidate.estimated_date,
                    confidence=candidate.confidence,
                    generated_by_model=deps.model_name,
                    ingestion_run_id=deps.run_id,
                )
                if not deps.dry_run:
                    await deps.claim_repo.upsert(claim)
                claims[claim.id] = claim.model_dump(mode="json")
            except Exception as exc:  # noqa: BLE001
                errors.append(_error("generate_claims", subject["name"], exc))

    update = {
        "claims": claims,
        "pending_claim_subjects": rest,
        "errors": errors,
        "pending_unresolved_mentions": unresolved,
    }
    return Command(update=update, goto="generate_claims" if rest else "entity_resolution")


# --- final sweep + chunks/embeddings/finish -------------------------------------


_STUB_SUMMARY = "Auto-created stub: mentioned in a relationship/claim but not independently expanded."

# Dispatch table mirroring ENTITY_LABELS/entity_type_discriminator in
# domain/models.py — picks the right AnyEntity subclass for a classified stub.
_STUB_CLASS_BY_ENTITY_TYPE: dict[EntityType, type[AnyEntity]] = {
    EntityType.CIVILIZATION: Civilization,
    EntityType.PERSON: Person,
    EntityType.PLACE: Place,
    EntityType.CITY: Place,
    EntityType.REGION: Place,
    EntityType.POLITY: Polity,
    EntityType.EMPIRE: Polity,
    EntityType.KINGDOM: Polity,
    EntityType.DYNASTY: Polity,
    EntityType.DOCUMENT: Document,
    EntityType.TEXT: Document,
    EntityType.INSCRIPTION: Document,
    EntityType.RELIGION: Concept,
    EntityType.DEITY: Concept,
    EntityType.CULTURE: Concept,
    EntityType.LANGUAGE: Concept,
    EntityType.CONCEPT: Concept,
}


def _build_stub_entity(entity_type: EntityType, name: str, deps: GraphDeps) -> AnyEntity:
    cls = _STUB_CLASS_BY_ENTITY_TYPE[entity_type]
    kwargs = dict(
        id=stable_entity_id(entity_type, name),
        canonical_name=name,
        summary=_STUB_SUMMARY,
        generated_by_model=deps.model_name,
        ingestion_run_id=deps.run_id,
    )
    # Only Place/Polity/Document/Concept actually vary their entity_type across
    # multiple EntityType values — Civilization/Person have it fixed already.
    if cls in (Place, Polity, Document, Concept):
        kwargs["entity_type"] = entity_type
    return cls(**kwargs)


async def entity_resolution(state: IngestionState, config: RunnableConfig) -> dict:
    """Not a self-loop: a single pass over the (deduplicated) names mentioned
    in relationships/claims that didn't resolve to any known entity/event.
    Resolution already happened per-item inside expand_people/expand_places —
    this only handles mention-only orphans. Each is classified by the LLM
    (PERSON/PLACE/POLITY/...) before being stubbed, so e.g. "Akkadian Empire"
    doesn't end up as a wrongly-typed Person node — see spec/03."""
    deps = _deps(config)
    names = sorted({n.strip() for n in state["pending_unresolved_mentions"] if n and n.strip()})
    if not names:
        return {"pending_unresolved_mentions": []}

    log.info("ENTITY", f"Resolving {len(names)} orphaned mention(s)")
    entities = dict(state["entities"])
    errors = list(state["errors"])
    chunk_subjects = list(state["pending_chunk_subjects"])

    still_unresolved: list[str] = []
    for name in names:
        if await _resolve_name_to_id(name, state, deps) is None:
            still_unresolved.append(name)

    async def classify(name: str) -> OrphanEntityGuess:
        return await deps.llm_client.generate_structured(build_orphan_entity_type_prompt(name), OrphanEntityGuess)

    remaining = still_unresolved
    while remaining:
        batch, remaining = await _gather_batch(remaining, deps.settings.llm_concurrency, classify)
        for name, result in batch:
            try:
                entity_type = EntityType.PERSON if isinstance(result, BaseException) else result.entity_type
                if isinstance(result, BaseException):
                    log.error("ENTITY", f"Failed to classify orphaned mention {name}", error=str(result))
                log.info("ENTITY", f"Creating stub {entity_type.value} for orphaned mention: {name}")
                stub = _build_stub_entity(entity_type, name, deps)
                if not deps.dry_run:
                    await deps.entity_repo.upsert(stub)
                entities[stub.id] = stub.model_dump(mode="json")
                chunk_subjects.append(
                    {"id": stub.id, "name": stub.canonical_name, "kind": entity_type.value.lower(), "context": _STUB_SUMMARY}
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(_error("entity_resolution", name, exc))

    return {
        "entities": entities,
        "errors": errors,
        "pending_unresolved_mentions": [],
        "pending_chunk_subjects": chunk_subjects,
    }


async def generate_chunks(state: IngestionState, config: RunnableConfig) -> dict:
    """Static node (not a Command self-loop) — chunk generation has no
    per-item resolve+write race to protect against, so it just drains
    `pending_chunk_subjects` internally, batching LLM calls by
    LLM_CONCURRENCY. Chunks are NOT persisted here (no embedding yet);
    generate_embeddings persists them once the vector is computed."""
    deps = _deps(config)
    remaining = state["pending_chunk_subjects"]
    if not remaining:
        return {}

    log.info("LLM", f"Generating chunks for {len(remaining)} subject(s)")
    chunks = dict(state["chunks"])
    errors = list(state["errors"])

    async def call(subject: dict) -> ChunkDraftList:
        prompt = build_chunk_generation_prompt(subject["name"], subject["kind"], subject["context"])
        return await deps.llm_client.generate_structured(prompt, ChunkDraftList)

    while remaining:
        batch, remaining = await _gather_batch(remaining, deps.settings.llm_concurrency, call)
        for subject, result in batch:
            if isinstance(result, BaseException):
                errors.append(_error("generate_chunks", subject["name"], result))
                continue
            for draft in result.items:
                chunk = KnowledgeChunk(
                    id=stable_chunk_id([subject["id"]], draft.chunk_type, draft.text),
                    entity_ids=[subject["id"]],
                    text=draft.text,
                    chunk_type=draft.chunk_type,
                    generated_by_model=deps.model_name,
                    ingestion_run_id=deps.run_id,
                )
                chunks[chunk.id] = chunk.model_dump(mode="json")

    return {"chunks": chunks, "errors": errors, "pending_chunk_subjects": []}


async def generate_embeddings(state: IngestionState, config: RunnableConfig) -> dict:
    deps = _deps(config)
    chunks = state["chunks"]
    if not chunks:
        return {}

    await ensure_index_ready(deps)

    log.info("EMBEDDING", f"Embedding {len(chunks)} chunk(s)")
    batch_size = max(1, deps.settings.llm_concurrency) * 4  # embedding calls batch cheaply
    updated, batch_errors = await embed_and_persist_chunks(chunks, deps, batch_size)

    return {"chunks": updated, "errors": [*state["errors"], *batch_errors]}


async def persist_graph(state: IngestionState, config: RunnableConfig) -> dict:
    deps = _deps(config)
    if deps.dry_run:
        log.info("INGESTION", "Dry-run complete — nothing was written to Postgres")
        return {}

    run = IngestionRun(
        id=deps.run_id,
        civilization_id=state["civilization_id"],
        status="completed",
        finished_at=datetime.now(timezone.utc),
        model=deps.model_name,
        entities_created=len(state["entities"]),
        entities_updated=0,
        errors=[IngestionError.model_validate(e) for e in state["errors"]],
    )
    await deps.run_repo.save(run)
    log.info(
        "INGESTION",
        "Ingestion run finished",
        entities=len(state["entities"]),
        events=len(state["events"]),
        relationships=len(state["relationships"]),
        claims=len(state["claims"]),
        chunks=len(state["chunks"]),
        errors=len(state["errors"]),
    )
    return {}
