# Chronos — ingestion

Generates a historical knowledge graph directly in **Firestore** from a local LLM (or OpenAI), through a deterministic, checkpointed [LangGraph](https://github.com/langchain-ai/langgraph) workflow. See [`spec/`](spec/) for the full design and [`../README.md`](../README.md) for how this fits into the wider Chronos platform.

**What this is not (yet):** no frontend, no chatbot, no query-time GraphRAG. This module only produces the graph — see [`spec/01-product-spec.md`](spec/01-product-spec.md) for exact scope.

## Requirements

- Python 3.12+ (managed via [`uv`](https://docs.astral.sh/uv/) — if you don't have 3.12, `uv python install 3.12` fetches it without touching your system Python)
- A Firebase project with Firestore enabled, and a service-account key (Admin SDK) — or ambient Application Default Credentials (`gcloud auth application-default login`)
- [Ollama](https://ollama.com) running locally (default provider), **or** an OpenAI API key

## Setup

```bash
cd ingestion
uv sync
cp .env.example .env
```

Edit `.env` if needed — every model/endpoint/limit is configurable there, nothing is hardcoded. The committed defaults point at models that are cheap to have on hand (`qwen3.5:9b` / `embeddinggemma`); swap in `qwen3:14b` / `nomic-embed-text` or anything else you have pulled.

### Point at Firestore

Set in `.env`:

```
FIREBASE_PROJECT_ID=chronos-29b82
GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account-key.json
```

Leave `GOOGLE_APPLICATION_CREDENTIALS` empty to fall back to ambient Application Default Credentials instead. Both are required for `ingest` to persist anything — `--dry-run` works without them (calls the LLM, prints the result, skips entity-resolution lookups against Firestore).

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

`LLM_CONCURRENCY` controls how many pending items (events/people/places/polities/...) get sent to the LLM concurrently within one expansion step — safe to raise against a hosted API; keep it at `1` for a local Ollama instance (it only serves one request at a time anyway). See [`spec/03-architecture-spec.md`](spec/03-architecture-spec.md).

## Run

Dry run — calls the LLM, prints the structured result, writes nothing to Firestore:

```bash
uv run python -m app.main ingest --civilization sumer --max-events 5 --max-people 10 --max-places 10 --dry-run
```

Real run:

```bash
uv run python -m app.main ingest --civilization sumer --max-events 5 --max-people 10 --max-places 10
```

`ingest --civilization X` always does a **fresh re-import**: any data belonging only to `X` from a previous run is deleted first (`app/services/civilization_reset.py::reset_civilization`), so tweaking prompts/limits and re-running the same civilization never piles new documents on top of stale ones. A document shared with another already-ingested civilization (cross-civilization entity resolution — see `app/services/entity_resolution.py`) is kept, not deleted.

`--max-events`/`--max-people`/`--max-places`/`--max-polities`/`--depth` override the budget explicitly; left unset, they're derived instead from that civilization's `importance_score` (0-10, set per entry in [`data/civilizations.yaml`](data/civilizations.yaml)) — a score of 10 (Rome, Greece, Egypt, ...) gets the full `MAX_*_PER_CIVILIZATION` ceiling from `.env`, a lower score gets a proportionally (steeply, not linearly) smaller budget, so a less prominent civilization's import stays fast instead of taking hours. See `app/services/civilization_service.py::scaled_budgets`.

Ingest everything in [`data/civilizations.yaml`](data/civilizations.yaml):

```bash
uv run python -m app.main ingest --all
```

`ingest --all` instead **skips** any civilization that already has a completed run recorded in Firestore's `ingestion_runs` collection — so a batch that crashes partway through is safely resumable by just re-running the same command. Pass `--force` to override that and fresh-reimport every civilization in the batch.

Resume a single interrupted run (crash, Ctrl-C mid-way) — LangGraph's checkpoint means already-processed items aren't redone:

```bash
uv run python -m app.main ingest --civilization sumer --resume <run_id>
```

(the `run_id` is logged at the start of every run, e.g. `[INGESTION] Starting Sumer run_id=...`)

Every write is a Firestore `set(..., merge=True)` on a stable, deterministic id, so nothing is duplicated regardless of how many times a civilization is (re-)ingested.

`--continue` generalizes `--resume`/`--force` into one always-safe-to-repeat flag: for each target civilization, skip it if already fully imported, resume its most recent interrupted run automatically (no need to know the run_id), or start fresh otherwise — meant for an unattended/scheduled re-invocation. Combined with `--all --shard I/N`, two (or more) separate processes can each cover a disjoint slice of the full civilization list at the same time, which keeps a local Ollama's `OLLAMA_NUM_PARALLEL` slots busier than a single sequential process. See [`scripts/README.md`](scripts/README.md) for a ready-made nightly-scheduled setup (Windows Task Scheduler, two shards in parallel, plus a stop script).

## Inspect the result

Firestore console, or the [Firebase CLI](https://firebase.google.com/docs/cli):

```bash
firebase firestore:get entities --project chronos-29b82 --limit 5
```

Every entity document carries `neighbor_ids` (1-hop relationship neighbors, maintained incrementally on every relationship write — see `RelationshipRepository.upsert`) and `source_civilizations` (which civilization ingestion run(s) touched it — see `app/services/civilization_reset.py`).

## Tests

```bash
uv run pytest
```

No test requires a real Ollama/OpenAI or Firestore — the LLM is faked (`tests/conftest.py::FakeLLMClient`) and repositories are in-memory. One test is marked `@pytest.mark.integration` and skips itself unless `FIRESTORE_EMULATOR_HOST` is set in the environment (`firebase emulators:start --only firestore`): `test_entity_upsert_is_idempotent`, which exercises a real Firestore `merge=True` write.

## Project layout

See [`spec/03-architecture-spec.md`](spec/03-architecture-spec.md) for the full breakdown; in short:

- `app/domain/` — Pydantic models (persistent, `models.py`) and LLM I/O contracts (ephemeral, `schemas.py`).
- `app/llm.py` — the entire LLM layer (Ollama + OpenAI clients, prompts, provider factory) in one file, by design.
- `app/graph/` — the LangGraph `StateGraph`: state shape, node functions, workflow wiring.
- `app/persistence/` — the Firestore connection wrapper and repositories.
- `app/services/` — entity resolution, civilization reset/reimport bookkeeping, and the orchestration glue between the graph and persistence/LLM layers.

## Known V1 limitations

See [`spec/06-acceptance-tests-spec.md`](spec/06-acceptance-tests-spec.md) — in short: fuzzy name matching doesn't catch cross-language transliterations unless the LLM already listed them as aliases; claim ids are sensitive to the exact statement text (rephrased reruns can create near-duplicate claims); a civilization/polity/event's `start_year`/`end_year` are only as good as the LLM's own historical knowledge — always LLM-derived, unverified estimates, never authoritative dates.

## What's next

This module only builds the graph. Two things are intentionally not here yet (see [`../README.md`](../README.md) for the roadmap): a source-ingestion pipeline that can confirm/contest LLM-generated claims against primary texts, and a GraphRAG query layer (Firestore vector similarity search combined with multi-hop `neighbor_ids` traversal) — the schema here (in particular the `chunks.embedding` field, stored as a native Firestore `Vector`) was deliberately kept ready for when it's built.
