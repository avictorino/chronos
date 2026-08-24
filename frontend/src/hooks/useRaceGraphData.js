import { useEffect, useState } from "react";
import { getEntity, getNeighbors } from "../lib/firestore";

/** The player's current node + its real 1-hop neighbors (reusing
 * getEntity/getNeighbors from lib/firestore.js — same `neighbor_ids`
 * denormalized field the explorer's Knowledge Graph panel reads, no new
 * Firestore access pattern). Re-fetches every time `currentEntityId`
 * changes, i.e. after every accepted move. */
export default function useRaceGraphData(currentEntityId) {
  const [state, setState] = useState({ status: "loading", current: null, neighbors: [] });

  useEffect(() => {
    if (!currentEntityId) return undefined;
    let cancelled = false;
    setState((s) => ({ status: "loading", current: s.current, neighbors: s.neighbors }));

    Promise.all([getEntity(currentEntityId), getNeighbors(currentEntityId)])
      .then(([current, neighbors]) => {
        if (!cancelled) setState({ status: "ready", current, neighbors });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "error", current: null, neighbors: [] });
      });

    return () => {
      cancelled = true;
    };
  }, [currentEntityId]);

  return state;
}
