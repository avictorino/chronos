import { useEffect, useState } from "react";
import { getClaimsFor, getEntitiesByIds, getEntity, getRelationshipsFor } from "../lib/firestore";

/** Loads one entity plus everything needed to render its detail panel:
 * its 1-hop neighbors (via the exported `neighbor_ids`), the relationship
 * record connecting each neighbor (for the type label), and any claims
 * about it (shown as claims, never as fact — see the domain model). */
export default function useEntityDetail(entityId) {
  const [state, setState] = useState({ status: "idle", entity: null, neighbors: [], claims: [] });

  useEffect(() => {
    if (!entityId) {
      setState({ status: "idle", entity: null, neighbors: [], claims: [] });
      return;
    }
    let cancelled = false;
    setState((s) => ({ ...s, status: "loading" }));

    (async () => {
      try {
        const [entity, relationships, claims] = await Promise.all([
          getEntity(entityId),
          getRelationshipsFor(entityId),
          getClaimsFor(entityId),
        ]);
        if (!entity) {
          if (!cancelled) setState({ status: "not-found", entity: null, neighbors: [], claims: [] });
          return;
        }
        const neighborIds = relationships.map((r) =>
          r.source_entity_id === entityId ? r.target_entity_id : r.source_entity_id
        );
        const neighborEntities = await getEntitiesByIds(neighborIds);
        const byId = new Map(neighborEntities.map((n) => [n.id, n]));
        const neighbors = relationships
          .map((r) => {
            const neighborId = r.source_entity_id === entityId ? r.target_entity_id : r.source_entity_id;
            const neighbor = byId.get(neighborId);
            return neighbor ? { relationship: r, entity: neighbor } : null;
          })
          .filter(Boolean);

        if (!cancelled) setState({ status: "ready", entity, neighbors, claims });
      } catch (err) {
        console.error("[useEntityDetail] Firestore query failed:", err);
        if (!cancelled) setState({ status: "error", entity: null, neighbors: [], claims: [], error: err });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [entityId]);

  return state;
}
