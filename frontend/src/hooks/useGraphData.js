import { useEffect, useState } from "react";
import { getEntitiesByIds } from "../lib/firestore";

// Keeps the force layout legible and the extra Firestore read small.
const MAX_TOTAL_NODES = 60;

function normalizeName(name) {
  return (name || "").trim().toLowerCase();
}

/** Entity resolution during ingestion isn't perfect — the same real-world
 * place/person sometimes ends up as two separate Firestore docs with
 * different ids but the same canonical_name (e.g. two "Ur"s, one properly
 * connected, one an auto-created stub). Rather than show it twice, a
 * dedupe pass keeps the first-seen doc per name (center wins over 1-hop,
 * 1-hop wins over 2-hop) and everything else gets folded into it —
 * `resolveId(id)` maps a dropped duplicate's id to the kept node's id, so
 * edges still land on the node that's actually shown instead of pointing
 * at a node that no longer exists in the graph. */
function addNode(known, idByName, entity) {
  const key = normalizeName(entity.canonical_name);
  const existingId = idByName.get(key);
  if (existingId && existingId !== entity.id) return existingId; // duplicate — redirect
  known.set(entity.id, entity);
  idByName.set(key, entity.id);
  return entity.id;
}

/** Builds the 1-hop graph immediately from data useEntityDetail already
 * loaded (no fetch at all) — the default, decluttered view. */
function buildFirstHop(entity, neighbors) {
  const known = new Map();
  const idByName = new Map();
  const redirect = new Map();
  addNode(known, idByName, entity);
  for (const { entity: n } of neighbors) {
    const keptId = addNode(known, idByName, n);
    if (keptId !== n.id) redirect.set(n.id, keptId);
  }

  const links = [];
  const seenEdge = new Set();
  for (const { entity: n, relationship } of neighbors) {
    const targetId = redirect.get(n.id) ?? n.id;
    if (targetId === entity.id) continue; // duplicate of the center itself — no self-loop
    const key = [entity.id, targetId].sort().join("|");
    if (seenEdge.has(key)) continue;
    seenEdge.add(key);
    links.push({ source: entity.id, target: targetId, type: relationship.relationship_type, hop: 1 });
  }

  return { nodes: [...known.values()], links, redirect };
}

/** Expands the 1-hop neighborhood into a 2-hop graph, for when the user
 * asks to see it (KnowledgeGraph's "Expandir conexões" toggle) — with only
 * one extra Firestore read: every neighbor doc already carries its own
 * `neighbor_ids` (the same denormalized field getNeighbors() reads for the
 * 1-hop case), so 2nd-hop candidate ids are already sitting in memory —
 * this just batch-fetches whichever of them aren't already loaded.
 *
 * 1-hop edges carry a `type` (the real relationship_type, for labeling).
 * 2-hop edges don't — labeling them would mean fetching the relationship
 * doc for every 1-hop neighbor too, which isn't worth it two hops out.
 *
 * `expanded` defaults to false: a well-connected entity's full 2-hop
 * neighborhood can hit dozens of nodes, which reads as a tangled mess
 * before the user's asked to see that much (see KnowledgeGraph.jsx). */
export default function useGraphData(entity, neighbors, expanded = false) {
  const [state, setState] = useState({ nodes: [], links: [] });

  useEffect(() => {
    if (!entity) {
      setState({ nodes: [], links: [] });
      return;
    }

    if (!expanded) {
      const { nodes, links } = buildFirstHop(entity, neighbors);
      setState({ nodes, links });
      return;
    }

    let cancelled = false;

    (async () => {
      const { nodes: firstHopNodes, links, redirect } = buildFirstHop(entity, neighbors);
      const known = new Map(firstHopNodes.map((n) => [n.id, n]));
      const idByName = new Map(firstHopNodes.map((n) => [normalizeName(n.canonical_name), n.id]));

      function resolveId(id) {
        return redirect.get(id) ?? id;
      }

      const secondHopIds = new Set();
      for (const { entity: n } of neighbors) {
        const nId = resolveId(n.id);
        for (const rawId of n.neighbor_ids || []) {
          const id = resolveId(rawId);
          if (id !== nId && !known.has(id)) secondHopIds.add(id);
        }
      }

      const remainingBudget = Math.max(MAX_TOTAL_NODES - known.size, 0);
      const idsToFetch = [...secondHopIds].slice(0, remainingBudget);
      const secondHopEntities = idsToFetch.length ? await getEntitiesByIds(idsToFetch) : [];
      if (cancelled) return;

      for (const n of secondHopEntities) {
        const keptId = addNode(known, idByName, n);
        if (keptId !== n.id) redirect.set(n.id, keptId);
      }

      const seenEdge = new Set(links.map((l) => [l.source, l.target].sort().join("|")));
      for (const { entity: n } of neighbors) {
        const nId = resolveId(n.id);
        for (const rawId of n.neighbor_ids || []) {
          const id = resolveId(rawId);
          if (id === nId || !known.has(id)) continue;
          const key = [nId, id].sort().join("|");
          if (seenEdge.has(key)) continue;
          seenEdge.add(key);
          links.push({ source: nId, target: id, hop: 2 });
        }
      }

      setState({ nodes: [...known.values()], links });
    })();

    return () => {
      cancelled = true;
    };
  }, [entity, neighbors, expanded]);

  return state;
}
