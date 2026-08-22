"""Top-level orchestration: builds dependencies, the initial state (or resumes
one from checkpoint), and invokes the compiled workflow. See
spec/03-architecture-spec.md for the checkpoint/resume/recursion_limit design.
"""

from __future__ import annotations

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.config import Settings, get_settings
from app.domain.schemas import CivilizationSeed
from app.graph.state import GraphDeps, IngestionState
from app.graph.workflow import DEFAULT_RECURSION_LIMIT, build_workflow
from app.llm import build_embedding_client, build_llm_client
from app.persistence.postgres import PostgresConnection
from app.persistence.repositories import (
    ChunkRepository,
    ClaimRepository,
    EntityRepository,
    EventRepository,
    IngestionRunRepository,
    RelationshipRepository,
)
from app.persistence.schema import ensure_schema
from app.services.civilization_service import get_civilization
from app.utils.ids import new_run_id
from app.utils.logging import get_logger

log = get_logger("ingestion")


class _NullRepo:
    """Read-only fallback used when --dry-run runs without a reachable Postgres:
    find_candidates() returns no matches (entity resolution just says
    'create'), and every write method is a no-op — nodes.py already gates all
    writes behind `if not deps.dry_run`, so these should never actually fire."""

    async def find_candidates(self, *_args: object, **_kwargs: object) -> list[dict]:
        return []

    async def get(self, *_args: object, **_kwargs: object) -> dict | None:
        return None

    async def upsert(self, *_args: object, **_kwargs: object) -> None:
        return None

    async def save(self, *_args: object, **_kwargs: object) -> None:
        return None


def _initial_state(seed: CivilizationSeed) -> IngestionState:
    return IngestionState(
        civilization_id=seed.id,
        civilization_seed=seed.model_dump(mode="json"),
        profile=None,
        pending_events=[],
        processed_events=[],
        pending_people=[],
        processed_people=[],
        pending_places=[],
        processed_places=[],
        pending_relationship_subjects=[],
        pending_claim_subjects=[],
        pending_chunk_subjects=[],
        pending_unresolved_mentions=[],
        entities={},
        events={},
        relationships={},
        claims={},
        chunks={},
        errors=[],
    )


async def _build_deps(
    settings: Settings, *, dry_run: bool, run_id: str
) -> tuple[GraphDeps, PostgresConnection | None]:
    llm_client = build_llm_client(settings)
    embedding_client = build_embedding_client(settings)
    model_name = settings.ollama_model if settings.llm_provider == "ollama" else settings.openai_model

    conn: PostgresConnection | None = PostgresConnection(settings)
    try:
        await conn.verify_connectivity()
        if not dry_run:
            await ensure_schema(conn)
    except Exception as exc:
        if not dry_run:
            raise RuntimeError(
                "Could not connect to Postgres. Check POSTGRES_DSN in .env points at your "
                "local instance, or use --dry-run to iterate on prompts without it."
            ) from exc
        log.warning("POSTGRES", "Not reachable — dry-run will skip entity-resolution lookups", error=str(exc))
        conn = None

    entity_repo = EntityRepository(conn) if conn else _NullRepo()
    event_repo = EventRepository(conn) if conn else _NullRepo()
    relationship_repo = RelationshipRepository(conn) if conn else _NullRepo()
    claim_repo = ClaimRepository(conn) if conn else _NullRepo()
    chunk_repo = ChunkRepository(conn) if conn else _NullRepo()
    run_repo = IngestionRunRepository(conn) if conn else _NullRepo()

    deps = GraphDeps(
        settings=settings,
        llm_client=llm_client,
        embedding_client=embedding_client,
        entity_repo=entity_repo,
        event_repo=event_repo,
        relationship_repo=relationship_repo,
        claim_repo=claim_repo,
        chunk_repo=chunk_repo,
        run_repo=run_repo,
        conn=conn,
        run_id=run_id,
        model_name=model_name,
        dry_run=dry_run,
    )
    return deps, conn


async def run_ingestion(
    civilization_id: str,
    *,
    settings: Settings | None = None,
    dry_run: bool = False,
    resume_run_id: str | None = None,
    max_events: int | None = None,
    max_people: int | None = None,
    max_places: int | None = None,
) -> IngestionState:
    settings = settings or get_settings()
    if max_events is not None:
        settings.max_events_per_civilization = max_events
    if max_people is not None:
        settings.max_people_per_civilization = max_people
    if max_places is not None:
        settings.max_places_per_civilization = max_places

    seed = get_civilization(civilization_id)
    run_id = resume_run_id or new_run_id()
    thread_id = f"{civilization_id}:{run_id}"

    deps, conn = await _build_deps(settings, dry_run=dry_run, run_id=run_id)

    try:
        async with AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_db_path)) as checkpointer:
            graph = build_workflow(checkpointer)
            config = {
                "configurable": {"thread_id": thread_id, "deps": deps},
                "recursion_limit": DEFAULT_RECURSION_LIMIT,
            }
            if resume_run_id:
                log.info("INGESTION", f"Resuming run {resume_run_id}", civilization=civilization_id)
                final_state = await graph.ainvoke(None, config=config)
            else:
                final_state = await graph.ainvoke(_initial_state(seed), config=config)
    finally:
        if conn is not None:
            await conn.close()

    return final_state
