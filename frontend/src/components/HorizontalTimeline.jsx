import React, { useMemo } from "react";
import { scaleLinear } from "d3-scale";
import useCivilizations from "../hooks/useCivilizations";
import { colorVarForType, formatYearRange } from "../lib/entityStyle";

const ROW_H = 22;
const PX_PER_YEAR = 0.34;
const AXIS_H = 26;

/** A real horizontal chronology strip (year axis + one bar per
 * civilization/polity, positioned and sized by start_year/end_year) —
 * replaces the old vertical list. Lives in the bottom 1/4 of the center
 * column: horizontally scrollable for the year range, vertically
 * scrollable for the row count.
 *
 * Only entities with at least one known year are placed on the axis —
 * most of the ingested set today are auto-created stubs with neither
 * start_year nor end_year (see the root README's ingestion notes), and
 * plotting those anyway would stack them all at the same x, 4px wide,
 * indistinguishable from an empty strip. They're counted and named in a
 * note instead, same "say what's missing" honesty as the rest of the app. */
export default function HorizontalTimeline({ selectedEntityId, onSelectEntity }) {
  const { status, items } = useCivilizations();

  const dated = useMemo(() => items.filter((i) => i.start_year != null || i.end_year != null), [items]);
  const undatedCount = items.length - dated.length;

  const { scale, minYear, maxYear, ticks } = useMemo(() => {
    const years = dated.flatMap((i) => [i.start_year, i.end_year]).filter((y) => y != null);
    const min = years.length ? Math.min(...years) : -3500;
    const max = years.length ? Math.max(...years, min + 200) : 200;
    const s = scaleLinear().domain([min, max]).range([0, (max - min) * PX_PER_YEAR]);
    const t = s.ticks(Math.max(Math.round((max - min) / 250), 6));
    return { scale: s, minYear: min, maxYear: max, ticks: t };
  }, [dated]);

  const totalWidth = scale(maxYear) + 60;

  return (
    <section className="chrono">
      <div className="chrono-head">
        <span className="panel-title">Chronology</span>
        {status === "ready" && (
          <span className="tl-sub">
            {dated.length} com datas conhecidas
            {undatedCount > 0 ? ` · ${undatedCount} sem data (não exibidas no eixo)` : ""}
          </span>
        )}
      </div>

      {status !== "ready" && (
        <div className="state-msg">{status === "error" ? "Couldn't reach Firestore." : "Loading…"}</div>
      )}

      {status === "ready" && dated.length === 0 && (
        <div className="state-msg">
          Nenhuma civilização/polity ingerida ainda tem `start_year`/`end_year` — a cronologia aparece assim que
          essas datas existirem no Firestore.
        </div>
      )}

      {status === "ready" && dated.length > 0 && (
        <div className="chrono-scroll">
          <div className="chrono-inner" style={{ width: totalWidth }}>
            <svg className="chrono-axis" width={totalWidth} height={AXIS_H}>
              {ticks.map((y) => (
                <g key={y} transform={`translate(${scale(y)},0)`}>
                  <line y1={0} y2={AXIS_H} stroke="var(--border-soft)" strokeWidth="1" />
                  <text x="4" y="14" fontSize="9.5" fill="var(--text-faint)">
                    {formatYearRange(y, null)}
                  </text>
                </g>
              ))}
            </svg>
            <div className="chrono-rows">
              {dated.map((item) => {
                const start = item.start_year ?? item.end_year;
                const end = item.end_year ?? start;
                const left = scale(start);
                const width = Math.max(scale(end) - scale(start), 4);
                return (
                  <div
                    key={item.id}
                    className={`chrono-row${item.id === selectedEntityId ? " selected" : ""}`}
                    style={{ height: ROW_H }}
                  >
                    <div
                      className="chrono-bar"
                      style={{
                        left,
                        width,
                        background: `var(${colorVarForType(item.entity_type)})`,
                      }}
                      title={`${item.canonical_name} — ${formatYearRange(item.start_year, item.end_year)}`}
                      onClick={() => onSelectEntity(item.id)}
                    >
                      <span className="chrono-bar-label">{item.canonical_name}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
