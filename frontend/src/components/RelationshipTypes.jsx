import React, { useMemo } from "react";

// Moved out of the old RightPanel into the left column's footer, per
// request — same donut, unchanged logic, just relocated.
const PALETTE = ["--c-polity", "--c-event", "--c-person", "--c-doc", "--c-place", "--c-concept"];

export default function RelationshipTypes({ neighbors }) {
  const counts = useMemo(() => {
    const map = new Map();
    for (const { relationship } of neighbors) {
      map.set(relationship.relationship_type, (map.get(relationship.relationship_type) ?? 0) + 1);
    }
    return [...map.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
  }, [neighbors]);

  if (counts.length === 0) return null;
  const total = counts.reduce((sum, [, n]) => sum + n, 0);

  let offset = 0;
  const arcs = counts.map(([type, n], i) => {
    const pct = (n / total) * 100;
    const arc = { type, n, pct, color: PALETTE[i % PALETTE.length], offset };
    offset -= pct;
    return arc;
  });

  return (
    <div className="panel rel-types-panel">
      <div className="panel-title">Relationship Types</div>
      <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
        <svg width="72" height="72" viewBox="0 0 42 42">
          <circle cx="21" cy="21" r="15.9" fill="transparent" stroke="var(--panel-2)" strokeWidth="6" />
          {arcs.map((a) => (
            <circle
              key={a.type}
              cx="21"
              cy="21"
              r="15.9"
              fill="transparent"
              stroke={`var(${a.color})`}
              strokeWidth="6"
              strokeDasharray={`${a.pct} ${100 - a.pct}`}
              strokeDashoffset={a.offset + 25}
            />
          ))}
        </svg>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 5 }}>
          {arcs.map((a) => (
            <div key={a.type} style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 10.5, color: "var(--text-dim)" }}>
              <span className="legend-dot" style={{ width: 7, height: 7, background: `var(${a.color})` }} />
              {a.type}
              <span style={{ marginLeft: "auto", color: "var(--text-faint)" }}>{a.n}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
