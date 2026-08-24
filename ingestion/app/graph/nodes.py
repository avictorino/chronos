"""LangGraph node functions.

`discover_events` and the three finishing nodes (`generate_chunks`,
`generate_embeddings`, `persist_graph`) return plain dict updates and use
static edges. `entity_resolution` also returns a plain dict (single pass, no
self-loop needed).

Every other node returns `Command` and routes dynamically via
`_route_after_stage` (or, for `extract_relationships`/`generate_claims`, a
local self-loop): each call processes a batch of up to `LLM_CONCURRENCY`
pending items — the LLM calls in that batch run concurrently via
`asyncio.gather` (phase A), then entity resolution + persistence + state
bookkeeping for the batch happen strictly sequentially, in order (phase B) —
see spec/03-architecture-spec.md for why that split exists (resolve-then-write
is not atomic, so it can't be parallelized without risking duplicate
entities).

`discover_people`/`discover_places` are also `Command` nodes now: each makes
its one-shot LLM discovery call exactly once (guarded by their
`*_discovery_done` flag) and then falls into the same `_route_after_stage`
decision as `expand_events`/`expand_people`/`expand_places`. This is what
makes expansion genuinely recursive — an event can surface new people/places,
a person can surface new events/places, a place can surface new events/people
(see `_enqueue_mentions`) — with `_route_after_stage` revisiting whichever
stage has queued work, in events -> people -> places order, until all three
are simultaneously empty. Recursion depth is capped by `max_expansion_depth`
(hops from the civilization root); volume per kind is capped by
`max_*_per_civilization`, counted across initial discovery plus everything
recursively queued.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import TypeVar

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from app.domain.enums import EntityType, EventType
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
    PolityCandidate,
    PolityCandidateList,
    PolityProfile,
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
    build_polity_discovery_prompt,
    build_polity_expansion_prompt,
    build_relationship_extraction_prompt,
)
from app.services.embedding_service import embed_and_persist_chunks
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


# --- subject "dates" hints, threaded into build_relationship_extraction_prompt --
#
# Short best-effort strings summarizing what's already known about a
# subject's own timeframe, so relationship extraction (see
# extract_relationships below) can ground any start_year/end_year it invents
# instead of guessing blind — see spec/06, "relationship coherence".


def _timeframe_hint(start_year: int | None, end_year: int | None) -> str | None:
    if start_year is None and end_year is None:
        return None
    span = f"{start_year} to {end_year}" if start_year is not None and end_year is not None else str(
        start_year if start_year is not None else end_year
    )
    return f"known timeframe: {span}"


def _historical_date_year(date) -> str | None:  # HistoricalDate | None
    if date is None:
        return None
    if date.estimated_year is not None:
        return str(date.estimated_year)
    if date.earliest_year is not None and date.latest_year is not None:
        return f"{date.earliest_year} to {date.latest_year}"
    if date.earliest_year is not None:
        return str(date.earliest_year)
    if date.latest_year is not None:
        return str(date.latest_year)
    return None


def _person_dates_hint(birth_date, death_date) -> str | None:  # HistoricalDate | None each
    born = _historical_date_year(birth_date)
    died = _historical_date_year(death_date)
    if born and died:
        return f"born {born}, died {died}"
    if born:
        return f"born {born}"
    if died:
        return f"died {died}"
    return None


def _event_dates_hint(date) -> str | None:  # HistoricalDate
    year = _historical_date_year(date)
    return f"occurred {year}" if year else None


# --- recursive expansion helpers ------------------------------------------------
#
# "True" recursion: expanding an event surfaces people/places it mentions,
# expanding a person surfaces events/places, expanding a place surfaces
# events/people — each recursively queued at depth+1 (capped by
# `max_expansion_depth`, a hop count from the civilization root) and against a
# per-kind budget (`max_*_per_civilization`, counted across initial discovery
# *and* everything recursively queued so far). `_route_after_stage` is the
# shared control-flow decision that keeps revisiting whichever of the three
# stages still has queued work until all three are simultaneously empty.


def _norm_name(name: str) -> str:
    return name.strip().lower()


def _name_known(name: str, entities: dict[str, dict], events: dict[str, dict]) -> bool:
    """True if `name` already matches a known entity or event (by canonical
    name or alias) — takes the caller's locally-updated dicts (not raw
    `state`) so a name resolved earlier in the *same* batch is already seen."""
    needle = _norm_name(name)
    if not needle:
        return True
    for entity in entities.values():
        pool = [entity["canonical_name"], *entity.get("aliases", [])]
        if any(_norm_name(p) == needle for p in pool):
            return True
    for event in events.values():
        pool = [event["name"], *event.get("aliases", [])]
        if any(_norm_name(p) == needle for p in pool):
            return True
    return False


def _name_pending(name: str, pending: list[dict]) -> bool:
    needle = _norm_name(name)
    return any(_norm_name(item.get("name", "")) == needle for item in pending)


def _enqueue_mentions(
    names: list[str],
    *,
    depth: int,
    max_depth: int,
    budget: int,
    entities: dict[str, dict],
    events: dict[str, dict],
    pending: list[dict],
    extra_fields: dict,
) -> None:
    """Queues by-name-only mentions surfaced during expansion as new
    candidates for the matching discover_*/expand_* pair, mutating `pending`
    in place. No-op past `max_depth` hops, past `budget` total candidates for
    this kind, or for a name that's already known/queued."""
    if depth > max_depth:
        return
    for name in names:
        name = name.strip()
        if not name:
            continue
        if len(pending) >= budget:
            break
        if _name_known(name, entities, events) or _name_pending(name, pending):
            continue
        pending.append({"name": name, "_depth": depth, **extra_fields})


def _route_after_stage(state: IngestionState) -> str:
    """Shared 'what's next' decision for the events/people/places/polities
    expansion loop. discover_people/discover_places/discover_polities each
    run their one-shot LLM discovery call exactly once (guarded by their
    *_discovery_done flag); after that, this keeps revisiting whichever stage
    has recursively-queued work — in events -> people -> places -> polities
    order — until every queue is simultaneously empty, at which point the
    pipeline moves on to extract_relationships."""
    if state["pending_events"]:
        return "expand_events"
    if not state["people_discovery_done"]:
        return "discover_people"
    if state["pending_people"]:
        return "expand_people"
    if not state["places_discovery_done"]:
        return "discover_places"
    if state["pending_places"]:
        return "expand_places"
    if not state["polities_discovery_done"]:
        return "discover_polities"
    if state["pending_polities"]:
        return "expand_polities"
    return "extract_relationships"


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
        source_civilizations=[state["civilization_id"]],
    )
    if not deps.dry_run:
        await deps.entity_repo.upsert(civilization)
        log.info("FIRESTORE", "Civilization persisted", name=civilization.canonical_name)
    else:
        log.info("LLM", "Civilization profile extracted (dry-run, not persisted)", name=civilization.canonical_name)

    subject = {
        "id": civilization.id,
        "name": civilization.canonical_name,
        "kind": "civilization",
        "context": civilization.summary or "",
        "dates": _timeframe_hint(civilization.start_year, civilization.end_year),
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
    pending = [{**c.model_dump(mode="json"), "_depth": 0} for c in items]
    return {"pending_events": pending, "processed_events": []}


async def discover_people(state: IngestionState, config: RunnableConfig) -> Command:
    """One-shot LLM discovery (guarded by people_discovery_done so the
    events/people/places loop never re-runs it) — merges its own candidates
    onto whatever expand_events already queued recursively, deduping by name,
    and only asks the LLM for however much budget is left."""
    deps = _deps(config)
    profile = CivilizationProfile.model_validate(state["profile"])
    event_names = [e["name"] for e in state["events"].values()]

    pending = list(state["pending_people"])
    remaining_budget = max(0, deps.settings.max_people_per_civilization - len(pending))
    if remaining_budget > 0:
        log.info("LLM", "Discovering people", civilization=profile.canonical_name)
        prompt = build_person_discovery_prompt(profile, event_names, remaining_budget)
        result = await deps.llm_client.generate_structured(prompt, PersonCandidateList)
        for c in result.items[:remaining_budget]:
            if _name_known(c.name, state["entities"], state["events"]) or _name_pending(c.name, pending):
                continue
            pending.append({**c.model_dump(mode="json"), "_depth": 0})
    log.info("LLM", f"{len(pending)} candidate people queued total (incl. recursively discovered)")

    update = {"pending_people": pending, "processed_people": [], "people_discovery_done": True}
    return Command(update=update, goto=_route_after_stage({**state, **update}))


async def discover_places(state: IngestionState, config: RunnableConfig) -> Command:
    deps = _deps(config)
    profile = CivilizationProfile.model_validate(state["profile"])
    event_names = [e["name"] for e in state["events"].values()]
    person_names = [
        e["canonical_name"] for e in state["entities"].values() if e.get("entity_type") == "PERSON"
    ]

    pending = list(state["pending_places"])
    remaining_budget = max(0, deps.settings.max_places_per_civilization - len(pending))
    if remaining_budget > 0:
        log.info("LLM", "Discovering places", civilization=profile.canonical_name)
        prompt = build_place_discovery_prompt(profile, event_names, person_names, remaining_budget)
        result = await deps.llm_client.generate_structured(prompt, PlaceCandidateList)
        for c in result.items[:remaining_budget]:
            if _name_known(c.name, state["entities"], state["events"]) or _name_pending(c.name, pending):
                continue
            pending.append({**c.model_dump(mode="json"), "_depth": 0})
    log.info("LLM", f"{len(pending)} candidate places queued total (incl. recursively discovered)")

    update = {"pending_places": pending, "processed_places": [], "places_discovery_done": True}
    return Command(update=update, goto=_route_after_stage({**state, **update}))


async def discover_polities(state: IngestionState, config: RunnableConfig) -> Command:
    deps = _deps(config)
    profile = CivilizationProfile.model_validate(state["profile"])
    event_names = [e["name"] for e in state["events"].values()]
    person_names = [
        e["canonical_name"] for e in state["entities"].values() if e.get("entity_type") == "PERSON"
    ]

    pending = list(state["pending_polities"])
    remaining_budget = max(0, deps.settings.max_polities_per_civilization - len(pending))
    if remaining_budget > 0:
        log.info("LLM", "Discovering polities", civilization=profile.canonical_name)
        prompt = build_polity_discovery_prompt(profile, event_names, person_names, remaining_budget)
        result = await deps.llm_client.generate_structured(prompt, PolityCandidateList)
        for c in result.items[:remaining_budget]:
            if _name_known(c.name, state["entities"], state["events"]) or _name_pending(c.name, pending):
                continue
            pending.append({**c.model_dump(mode="json"), "_depth": 0})
    log.info("LLM", f"{len(pending)} candidate polities queued total (incl. recursively discovered)")

    update = {"pending_polities": pending, "processed_polities": [], "polities_discovery_done": True}
    return Command(update=update, goto=_route_after_stage({**state, **update}))


# --- self-looping expansion nodes -----------------------------------------------


async def expand_events(state: IngestionState, config: RunnableConfig) -> Command:
    deps = _deps(config)
    pending = state["pending_events"]
    if not pending:
        return Command(goto=_route_after_stage(state))

    profile = CivilizationProfile.model_validate(state["profile"])

    async def call(candidate_dict: dict) -> EventExpansion:
        candidate = EventCandidate.model_validate(candidate_dict)
        prompt = build_event_expansion_prompt(candidate.name, candidate.event_type, profile.canonical_name)
        return await deps.llm_client.generate_structured(prompt, EventExpansion)

    batch, rest = await _gather_batch(pending, deps.settings.llm_concurrency, call)

    events = dict(state["events"])
    entities = dict(state["entities"])
    processed = list(state["processed_events"])
    errors = list(state["errors"])
    relationship_subjects = list(state["pending_relationship_subjects"])
    claim_subjects = list(state["pending_claim_subjects"])
    chunk_subjects = list(state["pending_chunk_subjects"])
    new_pending_people = list(state["pending_people"])
    new_pending_places = list(state["pending_places"])

    for candidate_dict, result in batch:
        candidate = EventCandidate.model_validate(candidate_dict)
        if isinstance(result, BaseException):
            errors.append(_error("expand_events", candidate.name, result))
            continue
        try:
            log.info("EVENT", f"Processing {candidate.name}")
            event = await resolve_and_persist_event(result, deps, state["civilization_id"])
            events[event.id] = event.model_dump(mode="json")
            processed.append(event.id)
            subject = {
                "id": event.id,
                "name": event.name,
                "kind": "event",
                "context": event.description,
                "dates": _event_dates_hint(event.date),
            }
            relationship_subjects.append(subject)
            claim_subjects.append(subject)
            chunk_subjects.append(subject)

            depth = candidate_dict.get("_depth", 0) + 1
            mention_note = f"Mentioned in the event '{event.name}'; discovered via recursive expansion."
            _enqueue_mentions(
                result.people,
                depth=depth,
                max_depth=deps.settings.max_expansion_depth,
                budget=deps.settings.max_people_per_civilization,
                entities=entities,
                events=events,
                pending=new_pending_people,
                extra_fields={"short_description": mention_note},
            )
            _enqueue_mentions(
                result.places,
                depth=depth,
                max_depth=deps.settings.max_expansion_depth,
                budget=deps.settings.max_places_per_civilization,
                entities=entities,
                events=events,
                pending=new_pending_places,
                extra_fields={"short_description": mention_note},
            )
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
        "pending_people": new_pending_people,
        "pending_places": new_pending_places,
    }
    return Command(update=update, goto=_route_after_stage({**state, **update}))


async def expand_people(state: IngestionState, config: RunnableConfig) -> Command:
    deps = _deps(config)
    pending = state["pending_people"]
    if not pending:
        return Command(goto=_route_after_stage(state))

    profile = CivilizationProfile.model_validate(state["profile"])

    async def call(candidate_dict: dict) -> PersonProfile:
        candidate = PersonCandidate.model_validate(candidate_dict)
        prompt = build_person_expansion_prompt(candidate.name, profile.canonical_name)
        return await deps.llm_client.generate_structured(prompt, PersonProfile)

    batch, rest = await _gather_batch(pending, deps.settings.llm_concurrency, call)

    entities = dict(state["entities"])
    events = dict(state["events"])
    processed = list(state["processed_people"])
    errors = list(state["errors"])
    relationship_subjects = list(state["pending_relationship_subjects"])
    claim_subjects = list(state["pending_claim_subjects"])
    chunk_subjects = list(state["pending_chunk_subjects"])
    new_pending_events = list(state["pending_events"])
    new_pending_places = list(state["pending_places"])

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
                source_civilizations=[state["civilization_id"]],
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
                "dates": _person_dates_hint(person.birth_date, person.death_date),
            }
            relationship_subjects.append(subject)
            claim_subjects.append(subject)
            chunk_subjects.append(subject)

            depth = candidate_dict.get("_depth", 0) + 1
            mention_note = f"Mentioned in connection with {person.canonical_name}; discovered via recursive expansion."
            _enqueue_mentions(
                result.notable_events,
                depth=depth,
                max_depth=deps.settings.max_expansion_depth,
                budget=deps.settings.max_events_per_civilization,
                entities=entities,
                events=events,
                pending=new_pending_events,
                extra_fields={"event_type": EventType.GENERIC.value, "short_description": mention_note},
            )
            _enqueue_mentions(
                result.associated_places,
                depth=depth,
                max_depth=deps.settings.max_expansion_depth,
                budget=deps.settings.max_places_per_civilization,
                entities=entities,
                events=events,
                pending=new_pending_places,
                extra_fields={"short_description": mention_note},
            )
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
        "pending_events": new_pending_events,
        "pending_places": new_pending_places,
    }
    return Command(update=update, goto=_route_after_stage({**state, **update}))


async def expand_places(state: IngestionState, config: RunnableConfig) -> Command:
    deps = _deps(config)
    pending = state["pending_places"]
    if not pending:
        return Command(goto=_route_after_stage(state))

    profile = CivilizationProfile.model_validate(state["profile"])

    async def call(candidate_dict: dict) -> PlaceProfile:
        candidate = PlaceCandidate.model_validate(candidate_dict)
        prompt = build_place_expansion_prompt(candidate.name, profile.canonical_name)
        return await deps.llm_client.generate_structured(prompt, PlaceProfile)

    batch, rest = await _gather_batch(pending, deps.settings.llm_concurrency, call)

    entities = dict(state["entities"])
    events = dict(state["events"])
    processed = list(state["processed_places"])
    errors = list(state["errors"])
    relationship_subjects = list(state["pending_relationship_subjects"])
    claim_subjects = list(state["pending_claim_subjects"])
    chunk_subjects = list(state["pending_chunk_subjects"])
    new_pending_events = list(state["pending_events"])
    new_pending_people = list(state["pending_people"])

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
                source_civilizations=[state["civilization_id"]],
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
                "dates": None,
            }
            relationship_subjects.append(subject)
            claim_subjects.append(subject)
            chunk_subjects.append(subject)

            depth = candidate_dict.get("_depth", 0) + 1
            mention_note = f"Mentioned in connection with {place.canonical_name}; discovered via recursive expansion."
            _enqueue_mentions(
                result.notable_events,
                depth=depth,
                max_depth=deps.settings.max_expansion_depth,
                budget=deps.settings.max_events_per_civilization,
                entities=entities,
                events=events,
                pending=new_pending_events,
                extra_fields={"event_type": EventType.GENERIC.value, "short_description": mention_note},
            )
            _enqueue_mentions(
                result.notable_people,
                depth=depth,
                max_depth=deps.settings.max_expansion_depth,
                budget=deps.settings.max_people_per_civilization,
                entities=entities,
                events=events,
                pending=new_pending_people,
                extra_fields={"short_description": mention_note},
            )
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
        "pending_events": new_pending_events,
        "pending_people": new_pending_people,
    }
    return Command(update=update, goto=_route_after_stage({**state, **update}))


async def expand_polities(state: IngestionState, config: RunnableConfig) -> Command:
    deps = _deps(config)
    pending = state["pending_polities"]
    if not pending:
        return Command(goto=_route_after_stage(state))

    profile = CivilizationProfile.model_validate(state["profile"])

    async def call(candidate_dict: dict) -> PolityProfile:
        candidate = PolityCandidate.model_validate(candidate_dict)
        prompt = build_polity_expansion_prompt(candidate.name, profile.canonical_name)
        return await deps.llm_client.generate_structured(prompt, PolityProfile)

    batch, rest = await _gather_batch(pending, deps.settings.llm_concurrency, call)

    entities = dict(state["entities"])
    events = dict(state["events"])
    processed = list(state["processed_polities"])
    errors = list(state["errors"])
    relationship_subjects = list(state["pending_relationship_subjects"])
    claim_subjects = list(state["pending_claim_subjects"])
    chunk_subjects = list(state["pending_chunk_subjects"])
    new_pending_events = list(state["pending_events"])
    new_pending_people = list(state["pending_people"])

    for candidate_dict, result in batch:
        candidate = PolityCandidate.model_validate(candidate_dict)
        if isinstance(result, BaseException):
            errors.append(_error("expand_polities", candidate.name, result))
            continue
        try:
            log.info("ENTITY", f"Resolving {result.canonical_name}")
            existing = await deps.entity_repo.find_candidates(result.entity_type)
            resolution = await resolve_entity(
                result.canonical_name,
                result.aliases,
                existing,
                deps.embedding_client,
                deps.llm_client,
                deps.settings.entity_resolution_use_llm,
            )
            polity_id = stable_entity_id(result.entity_type, result.canonical_name)
            if resolution.action == "merge" and resolution.existing_entity_id:
                polity_id = resolution.existing_entity_id
                _log_resolution_merge(result.canonical_name, resolution)
            polity = Polity(
                id=polity_id,
                entity_type=result.entity_type,
                canonical_name=result.canonical_name,
                aliases=result.aliases,
                summary=result.summary,
                start_year=result.start_year,
                end_year=result.end_year,
                confidence=result.confidence,
                generated_by_model=deps.model_name,
                ingestion_run_id=deps.run_id,
                source_civilizations=[state["civilization_id"]],
            )
            if not deps.dry_run:
                await deps.entity_repo.upsert(polity)
            entities[polity.id] = polity.model_dump(mode="json")
            processed.append(polity.id)
            subject = {
                "id": polity.id,
                "name": polity.canonical_name,
                "kind": "polity",
                "context": polity.summary or "",
                "dates": _timeframe_hint(polity.start_year, polity.end_year),
            }
            relationship_subjects.append(subject)
            claim_subjects.append(subject)
            chunk_subjects.append(subject)

            depth = candidate_dict.get("_depth", 0) + 1
            mention_note = f"Mentioned in connection with {polity.canonical_name}; discovered via recursive expansion."
            _enqueue_mentions(
                result.notable_events,
                depth=depth,
                max_depth=deps.settings.max_expansion_depth,
                budget=deps.settings.max_events_per_civilization,
                entities=entities,
                events=events,
                pending=new_pending_events,
                extra_fields={"event_type": EventType.GENERIC.value, "short_description": mention_note},
            )
            _enqueue_mentions(
                [*result.notable_rulers, *result.notable_people],
                depth=depth,
                max_depth=deps.settings.max_expansion_depth,
                budget=deps.settings.max_people_per_civilization,
                entities=entities,
                events=events,
                pending=new_pending_people,
                extra_fields={"short_description": mention_note},
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(_error("expand_polities", candidate.name, exc))

    update = {
        "entities": entities,
        "processed_polities": processed,
        "pending_polities": rest,
        "errors": errors,
        "pending_relationship_subjects": relationship_subjects,
        "pending_claim_subjects": claim_subjects,
        "pending_chunk_subjects": chunk_subjects,
        "pending_events": new_pending_events,
        "pending_people": new_pending_people,
    }
    return Command(update=update, goto=_route_after_stage({**state, **update}))


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
    (cheap), then falls back to Firestore across the likely entity types plus
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
        prompt = build_relationship_extraction_prompt(subject["name"], subject["context"], subject.get("dates"))
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
                    source_civilizations=[state["civilization_id"]],
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
                    source_civilizations=[state["civilization_id"]],
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


def _build_stub_entity(entity_type: EntityType, name: str, deps: GraphDeps, civilization_id: str) -> AnyEntity:
    cls = _STUB_CLASS_BY_ENTITY_TYPE[entity_type]
    kwargs = dict(
        id=stable_entity_id(entity_type, name),
        canonical_name=name,
        summary=_STUB_SUMMARY,
        generated_by_model=deps.model_name,
        ingestion_run_id=deps.run_id,
        source_civilizations=[civilization_id],
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
                stub = _build_stub_entity(entity_type, name, deps, state["civilization_id"])
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
                    source_civilizations=[state["civilization_id"]],
                )
                chunks[chunk.id] = chunk.model_dump(mode="json")

    return {"chunks": chunks, "errors": errors, "pending_chunk_subjects": []}


async def generate_embeddings(state: IngestionState, config: RunnableConfig) -> dict:
    deps = _deps(config)
    chunks = state["chunks"]
    if not chunks:
        return {}

    log.info("EMBEDDING", f"Embedding {len(chunks)} chunk(s)")
    batch_size = max(1, deps.settings.llm_concurrency) * 4  # embedding calls batch cheaply
    updated, batch_errors = await embed_and_persist_chunks(chunks, deps, batch_size)

    return {"chunks": updated, "errors": [*state["errors"], *batch_errors]}


async def persist_graph(state: IngestionState, config: RunnableConfig) -> dict:
    deps = _deps(config)
    if deps.dry_run:
        log.info("INGESTION", "Dry-run complete — nothing was written to Firestore")
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
