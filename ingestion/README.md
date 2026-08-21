# Chronos — ingestion

Generates a historical knowledge graph in Neo4j from a local LLM (or OpenAI), through a deterministic, checkpointed [LangGraph](https://github.com/langchain-ai/langgraph) workflow. See [`spec/`](spec/) for the full design and [`../README.md`](../README.md) for how this fits into the wider Chronos platform.

**What this is not (yet):** no frontend, no chatbot, no query-time GraphRAG. This module only produces the graph — see [`spec/01-product-spec.md`](spec/01-product-spec.md) for exact scope.

## Requirements

- Python 3.12+ (managed via [`uv`](https://docs.astral.sh/uv/) — if you don't have 3.12, `uv python install 3.12` fetches it without touching your system Python)
- Docker (for Neo4j via `docker compose`)
- [Ollama](https://ollama.com) running locally (default provider), **or** an OpenAI API key

## Setup

```bash
cd ingestion
uv sync
cp .env.example .env
```

Edit `.env` if needed — every model/endpoint/limit is configurable there, nothing is hardcoded. The committed defaults point at models that are cheap to have on hand (`qwen3.5:9b` / `embeddinggemma`); swap in `qwen3:14b` / `nomic-embed-text` or anything else you have pulled.

### Start Neo4j

From the repo root (`chronos/`, one level up):

```bash
docker compose up -d
```

Neo4j Browser: http://localhost:7474 (user `neo4j`, password `password` — the local dev default baked into `docker-compose.yml`, matching `.env.example`; change both together if you deploy this anywhere else).

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

Initialize the Neo4j schema (constraints + indexes) without ingesting anything:

```bash
uv run python -m app.main init-schema
```

Dry run — calls the LLM, prints the structured result, writes nothing to Neo4j:

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

Re-running the exact same command (with or without `--resume`) is safe — every write is a Neo4j `MERGE` on a stable, deterministic id, so nothing is duplicated.

## Inspect the result

In Neo4j Browser:

```cypher
MATCH (n) RETURN n LIMIT 100
```

```cypher
SHOW VECTOR INDEXES
```

```cypher
MATCH (r:IngestionRun) RETURN r ORDER BY r.started_at DESC LIMIT 5
```

## Tests

```bash
uv run pytest
```

No test requires a real Ollama/OpenAI or Neo4j — the LLM is faked (`tests/conftest.py::FakeLLMClient`) and repositories are in-memory. One test (`test_entity_upsert_is_idempotent`) is marked `@pytest.mark.integration` and skips itself unless `NEO4J_URI` is set in the environment, in which case it exercises the real `MERGE` idempotency against a live database.

## Project layout

See [`spec/03-architecture-spec.md`](spec/03-architecture-spec.md) for the full breakdown; in short:

- `app/domain/` — Pydantic models (persistent, `models.py`) and LLM I/O contracts (ephemeral, `schemas.py`).
- `app/llm.py` — the entire LLM layer (Ollama + OpenAI clients, prompts, provider factory) in one file, by design.
- `app/graph/` — the LangGraph `StateGraph`: state shape, node functions, workflow wiring.
- `app/persistence/` — Neo4j driver wrapper, schema/constraints, vector index, repositories.
- `app/services/` — entity resolution, and the orchestration glue between the graph and persistence/LLM layers.

## Known V1 limitations

See [`spec/06-acceptance-tests-spec.md`](spec/06-acceptance-tests-spec.md) — in short: fuzzy name matching doesn't catch cross-language transliterations unless the LLM already listed them as aliases; claim ids are sensitive to the exact statement text (rephrased reruns can create near-duplicate claims); changing the embedding model after data has been ingested requires a manual reindex.

## What's next

This module only builds the graph. Two things are intentionally not here yet (see [`../README.md`](../README.md) for the roadmap): a source-ingestion pipeline that can confirm/contest LLM-generated claims against primary texts, and a GraphRAG query layer (`neo4j-graphrag-python`'s `VectorRetriever`/`Text2Cypher` or equivalent) — the schema here (in particular the `:Chunk` vector index) was deliberately kept compatible with that package for when it's built.
