"""Curates a "race pair" for the frontend's multiplayer graph-race mode
(see the root plan/README section on race mode) — given a start and target
entity, verifies a path actually exists between them over the same
`neighbor_ids` adjacency the frontend's knowledge-graph panel already reads
(populated by RelationshipRepository.upsert, see
app/persistence/repositories.py — undirected by construction: every
relationship ArrayUnions both entities into each other's `neighbor_ids`),
and pre-computes the shortest-hop distance from *every* node reachable from
the target, not just along the optimal path.

That full distance map is the point: the frontend's "opponent's estimated
remaining clicks" HUD is a plain `distances[opponentCurrentEntityId]`
lookup — no live BFS per move, and the number rises on its own if a player
wanders off the optimal path, since that's exactly what a wider BFS
distance means.

Usage (run from ingestion/, same convention as `python -m app.main ...`):

    python -m scripts.curate_race_pairs --start <id_or_name> --target <id_or_name> --label "Sargon II -> Hammurabi"
    python -m scripts.curate_race_pairs --start <id_or_name> --target <id_or_name> --label "..." --apply

Dry-run by default (prints the resolved pair, hop count, and reachable-set
size) — nothing is written until --apply is passed, so a mistyped name
doesn't silently create a broken race pair.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import deque

from google.cloud import firestore

from app.config import get_settings
from app.persistence.firestore import FirestoreConnection
from app.utils.logging import configure_logging, get_logger

log = get_logger("curate_race_pairs")


async def _load_adjacency(conn: FirestoreConnection) -> dict[str, dict]:
    """One full scan of `entities`, projected to just what BFS + name
    resolution need. Fine at this dataset's size (low hundreds — same
    assumption the frontend's searchEntitiesByName makes, see
    frontend/src/lib/firestore.js); revisit if the graph gets much bigger."""
    snap = await conn.db.collection("entities").select(["canonical_name", "aliases", "neighbor_ids"]).get()
    nodes: dict[str, dict] = {}
    for doc in snap:
        data = doc.to_dict() or {}
        nodes[doc.id] = {
            "canonical_name": data.get("canonical_name") or "",
            "aliases": data.get("aliases") or [],
            "neighbor_ids": data.get("neighbor_ids") or [],
        }
    return nodes


def _resolve(ref: str, nodes: dict[str, dict]) -> str:
    """Accepts either a literal entity id or a name/alias (case-insensitive,
    exact match preferred, falls back to substring like the frontend
    search) — resolves to exactly one id or exits with a clear error, same
    "fail loud, don't guess" spirit as the rest of the pipeline's CLI."""
    if ref in nodes:
        return ref

    needle = ref.strip().lower()
    exact = [
        node_id
        for node_id, data in nodes.items()
        if data["canonical_name"].strip().lower() == needle or needle in [a.strip().lower() for a in data["aliases"]]
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        _fail(f"'{ref}' matches {len(exact)} entities by exact name — pass the entity id instead: {exact}")

    substring = [node_id for node_id, data in nodes.items() if needle in data["canonical_name"].strip().lower()]
    if len(substring) == 1:
        return substring[0]
    if len(substring) > 1:
        names = [f"{node_id} ({nodes[node_id]['canonical_name']})" for node_id in substring[:10]]
        _fail(f"'{ref}' matches {len(substring)} entities by substring — be more specific or pass an id: {names}")

    _fail(f"'{ref}' matched no entity by id, name, or alias.")


def _bfs_distances(target_id: str, nodes: dict[str, dict]) -> dict[str, int]:
    """Undirected BFS from the target over `neighbor_ids` — distances to
    every node in the target's connected component. `neighbor_ids` is
    already bidirectional by construction (see module docstring), so no
    need to also walk the `relationships` collection here."""
    distances = {target_id: 0}
    queue = deque([target_id])
    while queue:
        current = queue.popleft()
        for neighbor_id in nodes.get(current, {}).get("neighbor_ids", []):
            if neighbor_id not in nodes or neighbor_id in distances:
                continue
            distances[neighbor_id] = distances[current] + 1
            queue.append(neighbor_id)
    return distances


def _fail(message: str) -> None:
    log.error("CURATE", message)
    sys.exit(1)


async def _run(args: argparse.Namespace) -> None:
    settings = get_settings()
    conn = FirestoreConnection(settings)
    await conn.connect()
    try:
        nodes = await _load_adjacency(conn)
        if not nodes:
            _fail("No entities found in Firestore — has the ingestion pipeline populated anything yet?")

        start_id = _resolve(args.start, nodes)
        target_id = _resolve(args.target, nodes)
        if start_id == target_id:
            _fail("--start and --target resolved to the same entity.")

        distances = _bfs_distances(target_id, nodes)
        if start_id not in distances:
            _fail(
                f"No path exists from '{nodes[start_id]['canonical_name']}' ({start_id}) to "
                f"'{nodes[target_id]['canonical_name']}' ({target_id}) — they're in different "
                "connected components of the graph as ingested so far."
            )

        pair_id = args.pair_id or f"{start_id}__{target_id}"
        optimal_hops = distances[start_id]

        log.info(
            "CURATE",
            "Resolved race pair",
            start=f"{nodes[start_id]['canonical_name']} ({start_id})",
            target=f"{nodes[target_id]['canonical_name']} ({target_id})",
            optimal_hops=optimal_hops,
            reachable_nodes=len(distances),
        )

        if not args.apply:
            log.info("CURATE", "Dry-run — pass --apply to write race_pairs/" + pair_id)
            return

        doc = {
            "startEntityId": start_id,
            "targetEntityId": target_id,
            "label": args.label,
            "optimalHops": optimal_hops,
            "distances": distances,
            "active": True,
            "createdAt": firestore.SERVER_TIMESTAMP,
        }
        await conn.db.collection("race_pairs").document(pair_id).set(doc, merge=True)
        log.info("CURATE", f"Wrote race_pairs/{pair_id}")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", required=True, help="Start entity id, canonical name, or alias.")
    parser.add_argument("--target", required=True, help="Target entity id, canonical name, or alias.")
    parser.add_argument("--label", required=True, help='Display label, e.g. "Sargon II -> Hammurabi".')
    parser.add_argument("--pair-id", default=None, help="Override the generated race_pairs doc id.")
    parser.add_argument("--apply", action="store_true", help="Write to Firestore (default: dry-run only).")
    args = parser.parse_args()

    configure_logging(get_settings().log_level)
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
