import React from "react";
import { colorVarForType } from "../../lib/entityStyle";
import useRaceGraphData from "../../hooks/useRaceGraphData";

// Deliberately NOT the KnowledgeGraph.jsx force-simulation pattern: that
// one is tuned for browsing a settled 60-node neighborhood, but a race
// re-renders after every single click, under time pressure, on a phone —
// a physics simulation re-settling each time would jitter the very targets
// the player is trying to tap. A static radial layout (fixed positions,
// derived purely from neighbor count) is simpler and gives every neighbor a
// stable, predictable tap target instead. Same color/token language as the
// explorer graph (colorVarForType) so it still reads as "the same graph".
const VIEWBOX = 320;
const CENTER = VIEWBOX / 2;
const RING_RADIUS = 112;
const R_CENTER = 42;
const R_NEIGHBOR = 34; // sized for touch, not just legibility — see the plan's mobile section

function neighborPosition(index, count) {
  const angle = (index / count) * Math.PI * 2 - Math.PI / 2;
  return { x: CENTER + RING_RADIUS * Math.cos(angle), y: CENTER + RING_RADIUS * Math.sin(angle) };
}

/** The race's actual gameplay surface: the current node in the middle, its
 * real neighbors arranged around it, tap a neighbor to move there
 * (`onMove`, wired to submitMove — see RaceApp.jsx). The target entity, if
 * it's among the current neighbors, gets an accent ring so a winning click
 * is recognizable at a glance. */
export default function RaceGraph({ currentEntityId, targetEntityId, onMove, disabled }) {
  const { status, current, neighbors } = useRaceGraphData(currentEntityId);

  if (status === "loading" && !current) {
    return <div className="state-msg">Carregando o grafo…</div>;
  }
  if (status === "error") {
    return <div className="state-msg">Não deu pra carregar o grafo — tenta de novo.</div>;
  }
  if (!current) return null;

  return (
    <div className="race-graph-wrap">
      <svg className="race-graph-svg" viewBox={`0 0 ${VIEWBOX} ${VIEWBOX}`} role="img">
        {neighbors.map((n, i) => {
          const pos = neighborPosition(i, neighbors.length);
          return (
            <line
              key={`edge-${n.id}`}
              x1={CENTER}
              y1={CENTER}
              x2={pos.x}
              y2={pos.y}
              className="race-graph-edge"
            />
          );
        })}

        {neighbors.map((n, i) => {
          const pos = neighborPosition(i, neighbors.length);
          const isTarget = n.id === targetEntityId;
          return (
            <g
              key={n.id}
              className={`race-graph-node race-graph-neighbor${disabled ? " is-disabled" : ""}`}
              transform={`translate(${pos.x},${pos.y})`}
              onClick={() => !disabled && onMove(n.id)}
            >
              <circle
                r={R_NEIGHBOR}
                fill={`var(${colorVarForType(n.entity_type)})`}
                stroke={isTarget ? "var(--accent)" : "var(--bg-raised)"}
                strokeWidth={isTarget ? 4 : 2}
              />
              <text className="race-graph-label" y={R_NEIGHBOR + 14}>
                {n.canonical_name}
              </text>
              {isTarget && (
                <text className="race-graph-target-tag" y={-R_NEIGHBOR - 8}>
                  🏁 destino
                </text>
              )}
            </g>
          );
        })}

        <g className="race-graph-node race-graph-current" transform={`translate(${CENTER},${CENTER})`}>
          <circle r={R_CENTER} fill={`var(${colorVarForType(current.entity_type)})`} stroke="var(--accent)" strokeWidth={3} />
          <text className="race-graph-label race-graph-current-label" y={R_CENTER + 16}>
            {current.canonical_name}
          </text>
        </g>
      </svg>

      {neighbors.length === 0 && status === "ready" && (
        <div className="state-msg">Sem vizinhos conhecidos a partir daqui — beco sem saída no grafo ingerido.</div>
      )}
    </div>
  );
}
