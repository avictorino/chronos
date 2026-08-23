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
 * scrollable for the row count. */
export default function HorizontalTimeline({ selectedEntityId, onSelectEntity }) {
  const { status, items } = useCivilizations();

  const { scale, minYear, maxYear, ticks } = useMemo(() => {
    const years = items.flatMap((i) => [i.start_year, i.end_year]).filter((y) => y != null);
    const min = years.length ? Math.min(...years) : -3500;
    const max = years.length ? Math.max(...years, 200) : 200;
    const s = scaleLinear().domain([min, max]).range([0, (max - min) * PX_PER_YEAR]);
    const t = s.ticks(Math.max(Math.round((max - min) / 250), 6));
    return { scale: s, minYear: min, maxYear: max, ticks: t };
  }, [items]);

  const totalWidth = scale(maxYear) + 60;

  return (
    <section className="chrono">
      <div className="chrono-head">
        <span className="panel-title">Chronology</span>
        {status === "ready" && <span className="tl-sub">{items.length} civilizations/polities</span>}
      </div>

      {status !== "ready" && (
        <div className="state-msg">{status === "error" ? "Couldn't reach Firestore." : "Loading…"}</div>
      )}

      {status === "ready" && items.length > 0 && (
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
              {items.map((item) => {
                const start = item.start_year ?? minYear;
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
                      title={`${item.canonical_name} — ${formatYearRange(item.start_year, item.end_year) ?? "date unknown"}`}
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
