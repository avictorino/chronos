import React, { useEffect, useMemo, useRef } from "react";
import { scaleLinear } from "d3-scale";
import useCivilizations from "../hooks/useCivilizations";
import { colorVarForType, formatYearRange } from "../lib/entityStyle";

const ROW_H = 22;
const PX_PER_YEAR = 0.34;
const AXIS_H = 26;

/** Best-effort single year for any entity, not just the civilizations this
 * strip plots — PERSON carries birth/death dates instead of start/end
 * years, everything else may have neither. Used to find "the most
 * appropriate" chronology row for whatever got selected elsewhere (the
 * graph, search, connections list), even when the selection itself isn't
 * a civilization/polity. */
function estimateYear(entity) {
  if (!entity) return null;
  if (entity.start_year != null) return entity.start_year;
  if (entity.end_year != null) return entity.end_year;
  if (entity.birth_date?.estimated_year != null) return entity.birth_date.estimated_year;
  if (entity.death_date?.estimated_year != null) return entity.death_date.estimated_year;
  return null;
}

/** The dated row whose [start,end] contains — or is closest to — a target
 * year. Exact id match always wins (the selection *is* one of the plotted
 * civilizations). */
function findNearestRow(dated, targetYear, selfId) {
  if (dated.some((d) => d.id === selfId)) return selfId;
  if (targetYear == null) return null;
  let best = null;
  let bestDist = Infinity;
  for (const item of dated) {
    const s = item.start_year ?? item.end_year;
    const e = item.end_year ?? s;
    const dist = targetYear < s ? s - targetYear : targetYear > e ? targetYear - e : 0;
    if (dist < bestDist) {
      bestDist = dist;
      best = item.id;
    }
  }
  return best;
}

/** A real horizontal chronology strip (year axis + one bar per
 * civilization/polity, positioned and sized by start_year/end_year).
 *
 * Only entities with at least one known year are placed on the axis —
 * most of the ingested set today are auto-created stubs with neither
 * start_year nor end_year (see the root README's ingestion notes), and
 * plotting those anyway would stack them all at the same x, 4px wide,
 * indistinguishable from an empty strip.
 *
 * Whenever the selected entity changes (from the graph, search, wherever),
 * this centers the strip on whichever row is the closest chronological
 * match — the entity's own row if it's a plotted civilization/polity,
 * otherwise the row whose date range best matches its estimated year (e.g.
 * a person's birth/death date) — and drops a video-editor-style red
 * playhead at the entity's own estimated year, always, regardless of
 * whether that lines up with a plotted row. */
export default function HorizontalTimeline({ entity, onSelectEntity }) {
  const { status, items } = useCivilizations();
  const scrollRef = useRef(null);

  const dated = useMemo(() => items.filter((i) => i.start_year != null || i.end_year != null), [items]);
  const undatedCount = items.length - dated.length;

  const { scale, maxYear, ticks } = useMemo(() => {
    const years = dated.flatMap((i) => [i.start_year, i.end_year]).filter((y) => y != null);
    const min = years.length ? Math.min(...years) : -3500;
    const max = years.length ? Math.max(...years, min + 200) : 200;
    const s = scaleLinear().domain([min, max]).range([0, (max - min) * PX_PER_YEAR]);
    const t = s.ticks(Math.max(Math.round((max - min) / 250), 6));
    return { scale: s, minYear: min, maxYear: max, ticks: t };
  }, [dated]);

  const totalWidth = scale(maxYear) + 60;

  const targetYear = useMemo(() => estimateYear(entity), [entity]);
  const nearestId = useMemo(() => findNearestRow(dated, targetYear, entity?.id), [dated, targetYear, entity?.id]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || nearestId == null) return;
    const item = dated.find((d) => d.id === nearestId);
    if (!item) return;
    const start = item.start_year ?? item.end_year;
    const end = item.end_year ?? start;
    const centerX = scale((start + end) / 2);
    el.scrollTo({ left: Math.max(centerX - el.clientWidth / 2, 0), behavior: "smooth" });
  }, [nearestId]); // eslint-disable-line react-hooks/exhaustive-deps -- dated/scale are derived from the same `items` load, re-running per row-add isn't useful here

  return (
    <section className="chrono">
      {status !== "ready" && (
        <div className="state-msg">{status === "error" ? "Couldn't reach Firestore." : "Loading…"}</div>
      )}

      {status === "ready" && dated.length === 0 && (
        <div className="state-msg">
          Nenhuma civilização/polity ingerida ainda tem `start_year`/`end_year` — a cronologia aparece assim que
          essas datas existirem no Firestore. ({undatedCount} sem data)
        </div>
      )}

      {status === "ready" && dated.length > 0 && (
        <div className="chrono-scroll" ref={scrollRef}>
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
                const isSelected = item.id === entity?.id;
                const isNearest = !isSelected && item.id === nearestId;
                return (
                  <div
                    key={item.id}
                    className={`chrono-row${isSelected ? " selected" : ""}${isNearest ? " nearest" : ""}`}
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
            {targetYear != null && (
              <div
                className="chrono-playhead"
                style={{ left: scale(targetYear) }}
                title={`${entity?.canonical_name ?? "Selecionado"} — ~${formatYearRange(targetYear, null)}`}
              >
                <div className="chrono-playhead-flag" />
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
