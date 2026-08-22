# Chronos — ingestion

Generates a historical knowledge graph in Postgres + [pgvector](https://github.com/pgvector/pgvector) from a local LLM (or OpenAI), through a deterministic, checkpointed [LangGraph](https://github.com/langchain-ai/langgraph) workflow. See [`spec/`](spec/) for the full design and [`../README.md`](../README.md) for how this fits into the wider Chronos platform.

**What this is not (yet):** no frontend, no chatbot, no query-time GraphRAG. This module only produces the graph — see [`spec/01-product-spec.md`](spec/01-product-spec.md) for exact scope.

## Requirements

- Python 3.12+ (managed via [`uv`](https://docs.astral.sh/uv/) — if you don't have 3.12, `uv python install 3.12` fetches it without touching your system Python)
- Postgres with the [`vector`](https://github.com/pgvector/pgvector) extension available (either a local install that already has it, or `docker compose up -d` from the repo root)
- [Ollama](https://ollama.com) running locally (default provider), **or** an OpenAI API key

## Setup

```bash
cd ingestion
uv sync
cp .env.example .env
```

Edit `.env` if needed — every model/endpoint/limit is configurable there, nothing is hardcoded. The committed defaults point at models that are cheap to have on hand (`qwen3.5:9b` / `embeddinggemma`); swap in `qwen3:14b` / `nomic-embed-text` or anything else you have pulled.

### Point at Postgres

Set `POSTGRES_DSN` in `.env` to your instance, e.g.:

```
POSTGRES_DSN=postgresql://postgres:postgres@localhost:5432/chronos
```

If you already have Postgres running locally with the `vector` extension available, just point at it — no need to touch `docker-compose.yml`. Otherwise, from the repo root (`chronos/`, one level up):

```bash
docker compose up -d
```

That starts a `pgvector/pgvector:pg16` container matching the DSN above. Either way, `init-schema` (below) creates the extension/tables/indexes — the role in your DSN needs permission to `CREATE EXTENSION`.

### Pull Ollama models (if using the default provider)

```bash
ollama pull qwen3.5:9b
ollama pull embeddinggemma
```

Any chat-capable / embedding model works — these are just the ones this repo defaults to. Neither is a hard requirement; set `OLLAMA_MODEL` / `OLLAMA_EMBEDDING_MODEL` to whatever you have.

### Using OpenAI instead

Set in `.env`:

```
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
LLM_CONCURRENCY=4
```

`LLM_CONCURRENCY` controls how many pending items (events/people/places/...) get sent to the LLM concurrently within one expansion step — safe to raise against a hosted API; keep it at `1` for a local Ollama instance (it only serves one request at a time anyway). See [`spec/03-architecture-spec.md`](spec/03-architecture-spec.md).

## Run

Initialize the Postgres schema (extension + tables + indexes) without ingesting anything:

```bash
uv run python -m app.main init-schema
```

Dry run — calls the LLM, prints the structured result, writes nothing to Postgres:

```bash
uv run python -m app.main ingest --civilization sumer --max-events 5 --max-people 10 --max-places 10 --dry-run
```

Real run:

```bash
uv run python -m app.main ingest --civilization sumer --max-events 5 --max-people 10 --max-places 10
```

Ingest everything in [`data/civilizations.yaml`](data/civilizations.yaml):

```bash
uv run python -m app.main ingest --all
```

Resume a run that was interrupted (crash, Ctrl-C mid-way) — LangGraph's checkpoint means already-processed items aren't redone:

```bash
uv run python -m app.main ingest --civilization sumer --resume <run_id>
```

(the `run_id` is logged at the start of every run, e.g. `[INGESTION] Starting Sumer run_id=...`)

Re-running the exact same command (with or without `--resume`) is safe — every write is `INSERT ... ON CONFLICT (id) DO UPDATE` on a stable, deterministic id, so nothing is duplicated.

## Inspect the result

```sql
SELECT entity_type, count(*) FROM entities GROUP BY entity_type;
SELECT count(*) FROM events;
SELECT count(*) FROM relationships;
SELECT * FROM ingestion_runs ORDER BY (data->>'started_at') DESC LIMIT 5;
```

Multi-hop traversal (the `WITH RECURSIVE` building block for future cross-civilization exploration — see `RelationshipRepository.find_connected`):

```sql
WITH RECURSIVE traversal(id, path, depth) AS (
    SELECT 'some-entity-id'::text, ARRAY['some-entity-id'::text], 0
    UNION ALL
    SELECT
        CASE WHEN r.source_id = t.id THEN r.target_id ELSE r.source_id END,
        t.path || CASE WHEN r.source_id = t.id THEN r.target_id ELSE r.source_id END,
        t.depth + 1
    FROM traversal t
    JOIN relationships r ON r.source_id = t.id OR r.target_id = t.id
    WHERE t.depth < 4
      AND NOT (CASE WHEN r.source_id = t.id THEN r.target_id ELSE r.source_id END = ANY(t.path))
)
SELECT DISTINCT id, path, depth FROM traversal WHERE depth > 0 ORDER BY depth;
```

## Tests

```bash
uv run pytest
```

No test requires a real Ollama/OpenAI or Postgres — the LLM is faked (`tests/conftest.py::FakeLLMClient`) and repositories are in-memory. Two tests are marked `@pytest.mark.integration` and skip themselves unless `POSTGRES_DSN` is set in the environment: `test_entity_upsert_is_idempotent` (exercises the real `ON CONFLICT` idempotency) and `test_relationship_traversal_with_recursive_cte` (exercises the real `WITH RECURSIVE` traversal).

## Project layout

See [`spec/03-architecture-spec.md`](spec/03-architecture-spec.md) for the full breakdown; in short:

- `app/domain/` — Pydantic models (persistent, `models.py`) and LLM I/O contracts (ephemeral, `schemas.py`).
- `app/llm.py` — the entire LLM layer (Ollama + OpenAI clients, prompts, provider factory) in one file, by design.
- `app/graph/` — the LangGraph `StateGraph`: state shape, node functions, workflow wiring.
- `app/persistence/` — asyncpg connection wrapper, schema DDL, vector column sizing, repositories.
- `app/services/` — entity resolution, and the orchestration glue between the graph and persistence/LLM layers.

## Known V1 limitations

See [`spec/06-acceptance-tests-spec.md`](spec/06-acceptance-tests-spec.md) — in short: fuzzy name matching doesn't catch cross-language transliterations unless the LLM already listed them as aliases; claim ids are sensitive to the exact statement text (rephrased reruns can create near-duplicate claims); changing the embedding model after data has been ingested requires a manual reindex; `WITH RECURSIVE` traversal is deliberately unoptimized (re-walks `relationships` per hop).

## What's next

This module only builds the graph. Two things are intentionally not here yet (see [`../README.md`](../README.md) for the roadmap): a source-ingestion pipeline that can confirm/contest LLM-generated claims against primary texts, and a GraphRAG query layer (`pgvector` similarity search combined with `WITH RECURSIVE` traversal) — the schema here (in particular the `chunks.embedding` column and `RelationshipRepository.find_connected`) was deliberately kept ready for when it's built.
