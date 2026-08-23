import React from "react";
import useCivilizations from "../hooks/useCivilizations";
import { formatYearRange } from "../lib/entityStyle";

export default function Timeline({ selectedEntityId, onSelectEntity }) {
  const { status, items } = useCivilizations();

  return (
    <main className="center">
      <div className="tl-head">
        <div>
          <div className="tl-title">Timeline</div>
          <div className="tl-sub">
            {status === "ready" && `${items.length} civilizations/polities in Firestore`}
            {(status === "loading" || status === "idle") && "Loading…"}
            {status === "error" && "Couldn't reach Firestore"}
          </div>
        </div>
      </div>

      {status === "ready" && items.length === 0 && (
        <div className="state-msg">
          Firestore has no civilizations yet. Run{" "}
          <code>python -m app.main export-firestore</code> from <code>ingestion/</code>{" "}
          to mirror the ingested graph here.
        </div>
      )}

      {status === "error" && (
        <div className="state-msg">
          Couldn't read Firestore. Check <code>src/lib/firebase.js</code> and the
          project's security rules (read access must be public).
        </div>
      )}

      {items.length > 0 && (
        <div className="timeline">
          {items.map((item) => (
            <div
              key={item.id}
              className={`tl-row${item.id === selectedEntityId ? " selected" : ""}`}
              onClick={() => onSelectEntity(item.id)}
            >
              <div className="tl-row-label">
                <div className="tl-civ-name">{item.canonical_name}</div>
                <div className="tl-civ-range">
                  {formatYearRange(item.start_year, item.end_year) ?? "date unknown"}
                </div>
              </div>
              <div className="tl-civ-summary">{item.summary}</div>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
