import React, { useMemo } from "react";
import { colorVarForType } from "../lib/entityStyle";

const LEGEND = [
  { label: "Person", varName: "--c-person" },
  { label: "Place", varName: "--c-place" },
  { label: "Civilization", varName: "--c-civ" },
  { label: "Polity", varName: "--c-polity" },
  { label: "Document", varName: "--c-doc" },
  { label: "Concept", varName: "--c-concept" },
];

// Lays neighbors out on a circle around the selected entity — a simple,
// honest V1 for "the knowledge graph panel" (no physics simulation): real
// node positions computed from real data, not a hand-placed illustration.
function layoutOnCircle(count, radius, cx, cy) {
  return Array.from({ length: count }, (_, i) => {
    const angle = (2 * Math.PI * i) / Math.max(count, 1) - Math.PI / 2;
    return { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) };
  });
}

function RelationshipMetrics({ neighbors }) {
  const counts = useMemo(() => {
    const map = new Map();
    for (const { relationship } of neighbors) {
      map.set(relationship.relationship_type, (map.get(relationship.relationship_type) ?? 0) + 1);
    }
    return [...map.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
  }, [neighbors]);

  if (counts.length === 0) return null;
  const total = counts.reduce((sum, [, n]) => sum + n, 0);
  const palette = ["--c-polity", "--c-event", "--c-person", "--c-doc", "--c-place", "--c-concept"];

  let offset = 0;
  const arcs = counts.map(([type, n], i) => {
    const pct = (n / total) * 100;
    const arc = { type, n, pct, color: palette[i % palette.length], offset };
    offset -= pct;
    return arc;
  });

  return (
    <div className="panel">
      <div className="panel-title">Relationship Types</div>
      <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
        <svg width="86" height="86" viewBox="0 0 42 42">
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
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6 }}>
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

export default function RightPanel({ entity, neighbors, onSelectEntity }) {
  const positions = useMemo(() => layoutOnCircle(neighbors.length, 78, 141, 100), [neighbors.length]);

  return (
    <aside className="right">
      <div className="panel">
        <div className="panel-title">Knowledge Graph</div>
        <div className="legend">
          {LEGEND.map((l) => (
            <div className="legend-item" key={l.label}>
              <span className="legend-dot" style={{ background: `var(${l.varName})` }} />
              {l.label}
            </div>
          ))}
        </div>

        {!entity ? (
          <div className="empty-note">Select an entity to see its connections graphed here.</div>
        ) : (
          <div style={{ position: "relative", height: 210, background: "var(--bg-raised)", borderRadius: 8, border: "1px solid var(--border-soft)" }}>
            <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }} viewBox="0 0 282 200">
              {positions.map((p, i) => (
                <line key={i} x1="141" y1="100" x2={p.x} y2={p.y} stroke="#3a4150" strokeWidth="1.5" />
              ))}
            </svg>
            <div
              style={{
                position: "absolute",
                left: 141,
                top: 100,
                transform: "translate(-50%,-50%)",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 4,
              }}
            >
              <div
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: "50%",
                  background: `var(${colorVarForType(entity.entity_type)})`,
                  border: "2px solid var(--accent)",
                }}
              />
              <span style={{ fontSize: 9, color: "var(--text-dim)", background: "rgba(16,18,22,.75)", padding: "1px 6px", borderRadius: 5 }}>
                {entity.canonical_name}
              </span>
            </div>
            {neighbors.map(({ entity: n }, i) => {
              const p = positions[i];
              return (
                <div
                  key={n.id}
                  onClick={() => onSelectEntity(n.id)}
                  style={{
                    position: "absolute",
                    left: p.x,
                    top: p.y,
                    transform: "translate(-50%,-50%)",
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    gap: 4,
                    cursor: "pointer",
                  }}
                >
                  <div
                    style={{
                      width: 22,
                      height: 22,
                      borderRadius: "50%",
                      background: `var(${colorVarForType(n.entity_type)})`,
                      border: "2px solid var(--bg-raised)",
                    }}
                  />
                  <span style={{ fontSize: 9, color: "var(--text-dim)", background: "rgba(16,18,22,.75)", padding: "1px 5px", borderRadius: 4, whiteSpace: "nowrap" }}>
                    {n.canonical_name}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <RelationshipMetrics neighbors={neighbors} />
    </aside>
  );
}
