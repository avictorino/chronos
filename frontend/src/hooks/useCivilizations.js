import { useEffect, useState } from "react";
import { listEntitiesByTypes } from "../lib/firestore";

// Matches ingestion/app/domain/enums.py::EntityType — values are stored
// uppercase in Postgres/Firestore (Python `str, Enum` members whose value
// equals their name).
const TIMELINE_TYPES = ["CIVILIZATION", "POLITY", "EMPIRE", "KINGDOM", "DYNASTY"];

/** Every civilization/polity-like entity, sorted by start year — the rows of
 * the center Timeline panel. */
export default function useCivilizations() {
  const [state, setState] = useState({ status: "loading", items: [] });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const items = await listEntitiesByTypes(TIMELINE_TYPES, { limitTo: 200 });
        items.sort((a, b) => (a.start_year ?? 0) - (b.start_year ?? 0));
        if (!cancelled) setState({ status: "ready", items });
      } catch (err) {
        console.error("[useCivilizations] Firestore query failed:", err);
        if (!cancelled) setState({ status: "error", items: [], error: err });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
