import { useEffect, useState } from "react";
import { getEntitiesByIds } from "../lib/firestore";

// Keeps the force layout legible and the extra Firestore read small.
const MAX_TOTAL_NODES = 60;

/** Builds the 1-hop graph immediately from data useEntityDetail already
 * loaded (no fetch at all) — the default, decluttered view. */
function buildFirstHop(entity, neighbors) {
  const nodes = [entity, ...neighbors.map(({ entity: n }) => n)];
  const links = neighbors.map(({ entity: n, relationship }) => ({
    source: entity.id,
    target: n.id,
    type: relationship.relationship_type,
    hop: 1,
  }));
  return { nodes, links };
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
      setState(buildFirstHop(entity, neighbors));
      return;
    }

    let cancelled = false;

    (async () => {
      const { nodes: firstHopNodes, links } = buildFirstHop(entity, neighbors);
      const known = new Map(firstHopNodes.map((n) => [n.id, n]));

      const secondHopIds = new Set();
      for (const { entity: n } of neighbors) {
        for (const id of n.neighbor_ids || []) {
          if (!known.has(id)) secondHopIds.add(id);
        }
      }

      const remainingBudget = Math.max(MAX_TOTAL_NODES - known.size, 0);
      const idsToFetch = [...secondHopIds].slice(0, remainingBudget);
      const secondHopEntities = idsToFetch.length ? await getEntitiesByIds(idsToFetch) : [];
      if (cancelled) return;

      for (const n of secondHopEntities) known.set(n.id, n);

      const seenEdge = new Set([...neighbors].map(({ entity: n }) => [entity.id, n.id].sort().join("|")));
      for (const { entity: n } of neighbors) {
        for (const id of n.neighbor_ids || []) {
          if (!known.has(id)) continue;
          const key = [n.id, id].sort().join("|");
          if (seenEdge.has(key)) continue;
          seenEdge.add(key);
          links.push({ source: n.id, target: id, hop: 2 });
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
