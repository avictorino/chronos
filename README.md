# Chronos

Chronos is a platform for exploring thousands of years of world history as a navigable knowledge graph — civilizations, empires, kingdoms, people, events, places, religions, documents, and the relationships (causal, temporal, geographic) between them. The long-term vision is something like **"Google Maps + Wikipedia + a Knowledge Graph of History."**

This is a monorepo with two independent projects:

| Project | Status | What it is |
|---|---|---|
| [`ingestion/`](ingestion/README.md) | ✅ implemented | Python pipeline that uses a local LLM (or OpenAI) via LangGraph to generate, validate, deduplicate, and persist historical knowledge directly into Firestore — a single step, no intermediate database. |
| [`frontend/`](frontend/README.md) | ✅ implemented (v1) | Firebase-hosted React app that browses/visualizes the knowledge graph, reading Firestore directly with no backend. Live at **https://chronos-29b82.web.app**. |

## Vision / goal

The mockup below was the target experience used to design `frontend/`: a timeline of civilizations, a knowledge-graph panel for the selected entity (person/place/event/document relationships), a map view, and a primary-source evidence panel with confidence scores — all browsing the same graph the `ingestion/` pipeline populates.

![Chronos frontend vision mockup](docs/vision-mockup.png)

*The first implemented version of `frontend/` covers the timeline, entity detail panel (with confidence score and an explicit unverified/AI-generated indicator), and knowledge-graph panel from this mockup — see [`frontend/README.md`](frontend/README.md) for what's live today versus still planned (Map/Library tabs, evidence/genealogy/statistics views).*

## Data ingested so far

As of 2026-08-23 the Firestore collections were cleared and are being reimported from
scratch with the fixed pipeline (see [`ingestion/`](ingestion/README.md)) — two
civilizations, **Assyria** and **Babylon**, ingested 100%, with any civilization they only
*mention* (Elam, Achaemenid Persia, Ancient Israel and Judah, ...) created as a stub
entity. Reproduce/extend with:

```bash
cd ingestion && python -m app.main ingest --civilization assyria
cd ingestion && python -m app.main ingest --civilization babylon
```

`ingest --civilization X` always does a fresh re-import (deletes X's previous data first —
see [`ingestion/app/services/civilization_reset.py`](ingestion/app/services/civilization_reset.py)),
so it's safe to re-run after a prompt/pipeline change. `ingest --all` instead skips any
civilization already fully imported, so a batch run of the other 40 seeded civilizations
(see [`ingestion/data/civilizations.yaml`](ingestion/data/civilizations.yaml)) can be
interrupted and resumed freely.

## Graph modeled in Firestore, not a native graph database

History isn't a list of isolated facts — it's a dense network of temporal, geographic, and causal relationships between entities of very different kinds (a person can rule a polity, take part in an event, be mentioned in a document, be worshipped as a deity in another culture). A native graph database (Neo4j) would model this more directly, but this project persists straight to **Firestore** instead — an entity/event becomes a document with the full model as its fields, and a relationship becomes a `(source_entity_id, relationship_type, target_entity_id)` document, with a denormalized `neighbor_ids` list maintained on every entity document for zero-query 1-hop navigation. Deliberate trade-off: less optimized than native graph adjacency for deep multi-hop traversals, but keeps the pipeline down to a single datastore that both `ingestion/` and `frontend/` share directly, on Firebase's free Spark plan. See [`ingestion/app/persistence/repositories.py`](ingestion/app/persistence/repositories.py) for the full design.

## Philosophy

- Simplicity over abstraction: one well-organized Python process, no microservices/Kafka/Celery/Redis/Kubernetes, no intermediate database — `ingestion/` writes straight to the same Firestore `frontend/` reads.
- All LLM-generated knowledge is born tagged `origin=llm_generated` / `verification_status=unverified` — never treated as verified fact. A future primary-source ingestion pipeline (texts, inscriptions, academic papers) will be able to confirm or dispute this knowledge.
- Deterministic and controllable: no loose autonomous agent — the ingestion pipeline is an explicit state graph (LangGraph), with depth/quantity limits, checkpointing and resume, and idempotent Firestore writes (`set(..., merge=True)` on deterministic ids).

See [`ingestion/README.md`](ingestion/README.md) for full setup and pipeline instructions.

## Roadmap

1. ✅ `ingestion/` — generates the knowledge graph from a local LLM, straight into Firestore.
2. 🔜 Primary-source ingestion pipeline (historical texts, inscriptions, papers) that creates `SourceClaim`s to confirm/dispute LLM-generated knowledge.
3. 🔜 Query layer (GraphRAG: vector similarity search + multi-hop traversal) over the graph.
4. ✅ `frontend/` (v1) — visual graph exploration (Firebase), live at https://chronos-29b82.web.app. Still 🔜: Map/Graph/Library tabs, evidence/genealogy/statistics views, free-text semantic search (see [`frontend/README.md`](frontend/README.md)).
