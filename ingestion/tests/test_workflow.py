from __future__ import annotations

import os

import pytest

from app.config import Settings
from app.domain.enums import DatePrecision, EntityType, EventType, RelationshipType
from app.domain.models import HistoricalDate
from app.domain.schemas import (
    ChunkDraft,
    ChunkDraftList,
    CivilizationProfile,
    ClaimCandidate,
    ClaimCandidateList,
    EventCandidate,
    EventCandidateList,
    EventExpansion,
    PersonCandidate,
    PersonCandidateList,
    PersonProfile,
    PlaceCandidate,
    PlaceCandidateList,
    PlaceProfile,
    PolityCandidate,
    PolityCandidateList,
    PolityProfile,
    RelationshipCandidate,
    RelationshipCandidateList,
)
from app.graph.state import GraphDeps
from app.graph.workflow import DEFAULT_RECURSION_LIMIT, build_workflow
from app.services.ingestion_service import _initial_state
from tests.conftest import (
    FakeEmbeddingClient,
    FakeLLMClient,
    InMemoryEntityRepo,
    InMemoryEventRepo,
    InMemoryUpsertRepo,
)


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "max_events_per_civilization": 2,
        "max_people_per_civilization": 5,
        "max_places_per_civilization": 5,
        "max_polities_per_civilization": 5,
        "llm_concurrency": 1,
        "entity_resolution_use_llm": False,
    }
    base.update(overrides)
    return Settings(**base)


def _config(deps: GraphDeps, thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id, "deps": deps}, "recursion_limit": DEFAULT_RECURSION_LIMIT}


async def test_full_graph_with_fake_llm(sample_civilization_seed):
    """Runs the whole graph end-to-end against fakes: verifies every stage
    populates state correctly, MAX_EVENTS_PER_CIVILIZATION is respected, and
    everything gets persisted through the (in-memory) repositories."""
    settings = _settings()
    llm = FakeLLMClient()
    embeddings = FakeEmbeddingClient(dimension=8)

    llm.queue(
        CivilizationProfile,
        CivilizationProfile(
            canonical_name="Sumer",
            summary="A cradle-of-civilization region in southern Mesopotamia.",
            start_year=-4500,
            end_year=-1900,
        ),
    )

    # 3 candidates offered, only 2 should survive MAX_EVENTS_PER_CIVILIZATION=2
    llm.queue(
        EventCandidateList,
        EventCandidateList(
            items=[
                EventCandidate(name="Battle of Eridu", event_type=EventType.BATTLE, short_description="."),
                EventCandidate(name="Founding of Uruk", event_type=EventType.FOUNDATION, short_description="."),
                EventCandidate(name="Trimmed event", event_type=EventType.GENERIC, short_description="."),
            ]
        ),
    )
    llm.queue(
        EventExpansion,
        EventExpansion(
            name="Battle of Eridu",
            event_type=EventType.BATTLE,
            description="A battle fought near the city of Eridu.",
            date=HistoricalDate(estimated_year=-2500, precision=DatePrecision.APPROXIMATE),
            confidence=0.6,
        ),
    )
    llm.queue(
        EventExpansion,
        EventExpansion(
            name="Founding of Uruk",
            event_type=EventType.FOUNDATION,
            description="The city of Uruk is founded.",
            date=HistoricalDate(estimated_year=-4000, precision=DatePrecision.APPROXIMATE),
            confidence=0.6,
        ),
    )

    llm.queue(
        PersonCandidateList,
        PersonCandidateList(items=[PersonCandidate(name="Gilgamesh", short_description="A legendary king.")]),
    )
    llm.queue(
        PersonProfile,
        PersonProfile(canonical_name="Gilgamesh", aliases=["Bilgames"], summary="A legendary king of Uruk."),
    )

    llm.queue(
        PlaceCandidateList,
        PlaceCandidateList(items=[PlaceCandidate(name="Eridu", short_description="One of the oldest cities.")]),
    )
    llm.queue(
        PlaceProfile,
        PlaceProfile(canonical_name="Eridu", summary="One of the oldest cities of Sumer.", place_kind=EntityType.CITY),
    )

    llm.queue(
        PolityCandidateList,
        PolityCandidateList(items=[PolityCandidate(name="Akkadian Empire", short_description="A Mesopotamian empire.")]),
    )
    llm.queue(
        PolityProfile,
        PolityProfile(
            canonical_name="Akkadian Empire",
            summary="A Mesopotamian empire that unified Sumerian and Akkadian city-states.",
            entity_type=EntityType.EMPIRE,
            start_year=-2334,
            end_year=-2154,
        ),
    )

    # extract_relationships: 5 subjects in order [event1, event2, person1, place1, polity1]
    llm.queue(
        RelationshipCandidateList,
        RelationshipCandidateList(
            items=[
                RelationshipCandidate(
                    source_name="Battle of Eridu",
                    relationship_type=RelationshipType.OCCURRED_AT,
                    target_name="Eridu",
                    confidence=0.8,
                )
            ]
        ),
    )
    for _ in range(4):
        llm.queue(RelationshipCandidateList, RelationshipCandidateList(items=[]))

    # generate_claims: same 5 subjects
    llm.queue(
        ClaimCandidateList,
        ClaimCandidateList(
            items=[
                ClaimCandidate(
                    predicate="occurred_near",
                    object_name="Eridu",
                    statement="The Battle of Eridu occurred near the city of Eridu.",
                    confidence=0.6,
                )
            ]
        ),
    )
    for _ in range(4):
        llm.queue(ClaimCandidateList, ClaimCandidateList(items=[]))

    # generate_chunks: 6 subjects [civilization, event1, event2, person1, place1, polity1]
    for _ in range(6):
        llm.queue(
            ChunkDraftList,
            ChunkDraftList(items=[ChunkDraft(chunk_type="civilization_overview", text="Some chunk text.")]),
        )

    entity_repo = InMemoryEntityRepo()
    event_repo = InMemoryEventRepo()
    relationship_repo = InMemoryUpsertRepo()
    claim_repo = InMemoryUpsertRepo()
    chunk_repo = InMemoryUpsertRepo()
    run_repo = InMemoryUpsertRepo()

    deps = GraphDeps(
        settings=settings,
        llm_client=llm,
        embedding_client=embeddings,
        entity_repo=entity_repo,
        event_repo=event_repo,
        relationship_repo=relationship_repo,
        claim_repo=claim_repo,
        chunk_repo=chunk_repo,
        run_repo=run_repo,
        conn=None,
        run_id="test-run",
        model_name="fake-model",
        dry_run=False,
    )

    graph = build_workflow(checkpointer=None)
    final_state = await graph.ainvoke(_initial_state(sample_civilization_seed), config=_config(deps, "test-1"))

    assert len(final_state["events"]) == 2  # MAX_EVENTS_PER_CIVILIZATION respected
    assert len(final_state["entities"]) == 4  # civilization + person + place + polity
    for key in (
        "pending_events",
        "pending_people",
        "pending_places",
        "pending_polities",
        "pending_relationship_subjects",
        "pending_claim_subjects",
        "pending_chunk_subjects",
        "pending_unresolved_mentions",
    ):
        assert final_state[key] == []
    assert len(final_state["relationships"]) == 1
    assert len(final_state["claims"]) == 1
    assert len(final_state["chunks"]) == 6
    assert all(c["embedding"] for c in final_state["chunks"].values())
    assert final_state["errors"] == []

    # the polity picked up real dates from the LLM (B2 — no longer stub-only)
    polity = next(e for e in final_state["entities"].values() if e["entity_type"] == "EMPIRE")
    assert polity["start_year"] == -2334
    assert polity["end_year"] == -2154

    # persisted through the repositories, not just present in graph state
    assert len(entity_repo.by_id) == 4
    assert len(event_repo.by_id) == 2
    assert len(relationship_repo.by_id) == 1
    assert len(claim_repo.by_id) == 1
    assert len(chunk_repo.by_id) == 6
    assert len(run_repo.by_id) == 1


async def test_item_error_does_not_abort_run(sample_civilization_seed):
    """event 1 succeeds, event 2 fails -> the run still reaches persist_graph,
    with the failure recorded in state.errors instead of raising."""
    settings = _settings(max_events_per_civilization=2)
    llm = FakeLLMClient()
    embeddings = FakeEmbeddingClient()

    llm.queue(CivilizationProfile, CivilizationProfile(canonical_name="Sumer", summary="A civilization."))
    llm.queue(
        EventCandidateList,
        EventCandidateList(
            items=[
                EventCandidate(name="Event One", event_type=EventType.GENERIC, short_description="."),
                EventCandidate(name="Event Two", event_type=EventType.GENERIC, short_description="."),
            ]
        ),
    )
    llm.queue(
        EventExpansion,
        EventExpansion(
            name="Event One",
            event_type=EventType.GENERIC,
            description="First event, succeeds.",
            date=HistoricalDate(precision=DatePrecision.UNKNOWN),
            confidence=0.5,
        ),
    )
    llm.queue(EventExpansion, RuntimeError("simulated LLM failure"))

    llm.queue(PersonCandidateList, PersonCandidateList(items=[]))
    llm.queue(PlaceCandidateList, PlaceCandidateList(items=[]))
    llm.queue(PolityCandidateList, PolityCandidateList(items=[]))

    llm.queue(RelationshipCandidateList, RelationshipCandidateList(items=[]))  # subject: Event One
    llm.queue(ClaimCandidateList, ClaimCandidateList(items=[]))  # subject: Event One

    llm.queue(ChunkDraftList, ChunkDraftList(items=[]))  # subject: civilization
    llm.queue(ChunkDraftList, ChunkDraftList(items=[]))  # subject: Event One

    deps = GraphDeps(
        settings=settings,
        llm_client=llm,
        embedding_client=embeddings,
        entity_repo=InMemoryEntityRepo(),
        event_repo=InMemoryEventRepo(),
        relationship_repo=InMemoryUpsertRepo(),
        claim_repo=InMemoryUpsertRepo(),
        chunk_repo=InMemoryUpsertRepo(),
        run_repo=InMemoryUpsertRepo(),
        conn=None,
        run_id="test-run-2",
        model_name="fake-model",
        dry_run=False,
    )

    graph = build_workflow(checkpointer=None)
    final_state = await graph.ainvoke(_initial_state(sample_civilization_seed), config=_config(deps, "test-2"))

    assert len(final_state["events"]) == 1
    assert len(final_state["errors"]) == 1
    assert final_state["errors"][0]["node"] == "expand_events"
    assert final_state["errors"][0]["item"] == "Event Two"


def _require_firestore_emulator() -> None:
    if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
        pytest.skip("FIRESTORE_EMULATOR_HOST not set — skipping integration test")


@pytest.mark.integration
async def test_entity_upsert_is_idempotent():
    """Requires a local Firestore emulator (FIRESTORE_EMULATOR_HOST) —
    upserting the same entity twice must not create a duplicate document, and
    the merge=True write must not clobber source_civilizations. Skipped
    automatically otherwise."""
    _require_firestore_emulator()

    from app.domain.models import Person
    from app.persistence.firestore import FirestoreConnection
    from app.persistence.repositories import EntityRepository
    from app.utils.ids import stable_entity_id

    settings = Settings(firebase_project_id="chronos-test")
    conn = FirestoreConnection(settings)
    await conn.connect()
    repo = EntityRepository(conn)

    person = Person(
        id=stable_entity_id(EntityType.PERSON, "Test Idempotency Person"),
        canonical_name="Test Idempotency Person",
        source_civilizations=["test_civ"],
    )
    try:
        await repo.upsert(person)
        await repo.upsert(person)
        doc = await conn.db.collection("entities").document(person.id).get()
        assert doc.exists
        data = doc.to_dict()
        assert data["canonical_name"] == "Test Idempotency Person"
        assert data["source_civilizations"] == ["test_civ"]
    finally:
        await conn.db.collection("entities").document(person.id).delete()
        await conn.close()
