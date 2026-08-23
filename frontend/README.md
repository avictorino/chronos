# Chronos — frontend

Firebase-hosted React app that browses/visualizes the historical knowledge graph produced by [`../ingestion`](../ingestion/README.md) — the "Google Maps + Wikipedia" layer of the Chronos platform. Live at **https://chronos-29b82.web.app**.

It never talks to Postgres. It reads a read-only mirror in **Firestore**, kept up to date by `ingestion`'s `export-firestore` command (see [`../README.md`](../README.md#firestore-export-free-serverless-frontend)) — no backend/API server, no server-side rendering, just a static site + Firestore's client SDK.

## What's implemented (v1)

- **Search** — name/alias lookup across every ingested entity.
- **Entity detail panel** — summary, confidence score, and an explicit *"Unverified · AI-generated"* badge (nothing from the LLM pipeline is ever presented as a confirmed fact — see the ingestion README's philosophy).
- **Timeline** — every civilization/polity-like entity, click to select.
- **Knowledge-graph panel** — the selected entity's real 1-hop neighbors (via the `neighbor_ids` the export denormalizes onto each entity), laid out on a circle, plus a relationship-type breakdown.

## Not implemented yet

- The Map/Graph/Library tabs, and the Evidence/Narrative/Genealogy/Statistics/Comparisons sub-tabs from the design mockup ([`../docs/vision-mockup.png`](../docs/vision-mockup.png)) — today's app is the Timeline tab only.
- Multi-hop graph traversal (BFS beyond 1 hop).
- Free-text semantic search (would need embedding a query at request time — deliberately out of scope for now; see the root README's Firestore export section).

## Requirements

- Node.js 18+
- A Firestore mirror that actually has data — run `export-firestore` from [`../ingestion`](../ingestion/README.md) at least once first, otherwise every panel here will correctly show an empty state.

## Setup

```bash
cd frontend
npm install
npm run dev
```

Firebase config (`src/lib/firebase.js`) is the project's public web config — safe to commit; it identifies the project, it isn't a secret. Access control is entirely Firestore's security rules ([`firestore.rules`](firestore.rules)): public read, no client write.

## Deploy

```bash
npm run build
npx firebase-tools deploy --only hosting --project chronos-29b82
```

Firestore rules/indexes are deployed separately (rarely change):

```bash
npx firebase-tools deploy --only firestore:rules,firestore:indexes --project chronos-29b82
```
