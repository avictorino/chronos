import { useEffect, useState } from "react";
import { getEntitiesByIds } from "../lib/firestore";

// Keeps the force layout legible and the extra Firestore read small.
const MAX_TOTAL_NODES = 60;

/** Expands the 1-hop neighborhood (already loaded by useEntityDetail) into
 * a 2-hop graph for the force-directed Knowledge Graph — with only one
 * extra Firestore read: every neighbor doc already carries its own
 * `neighbor_ids` (the same denormalized field getNeighbors() reads for the
 * 1-hop case), so 2nd-hop candidate ids are already sitting in memory —
 * this just batch-fetches whichever of them aren't already loaded.
 *
 * 1-hop edges carry a `type` (the real relationship_type, for labeling).
 * 2-hop edges don't — labeling them would mean fetching the relationship
 * doc for every 1-hop neighbor too, which isn't worth it two hops out. */
export default function useGraphData(entity, neighbors) {
  const [state, setState] = useState({ nodes: [], links: [] });

  useEffect(() => {
    if (!entity) {
      setState({ nodes: [], links: [] });
      return;
    }

    let cancelled = false;

    (async () => {
      const known = new Map();
      known.set(entity.id, entity);
      for (const { entity: n } of neighbors) known.set(n.id, n);

      const links = neighbors.map(({ entity: n, relationship }) => ({
        source: entity.id,
        target: n.id,
        type: relationship.relationship_type,
        hop: 1,
      }));

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
  }, [entity, neighbors]);

  return state;
}
