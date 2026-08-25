import React, { useEffect, useState } from "react";
import "./App.css";
import TopBar from "./components/TopBar";
import Rail from "./components/Rail";
import EntityDetail from "./components/EntityDetail";
import KnowledgeGraph from "./components/KnowledgeGraph";
import HorizontalTimeline from "./components/HorizontalTimeline";
import RelationshipTypes from "./components/RelationshipTypes";
import useEntityDetail from "./hooks/useEntityDetail";
import useAuthUser from "./hooks/useAuthUser";
import useCivilizations from "./hooks/useCivilizations";
import RaceApp from "./components/race/RaceApp";

/** Reads `?entity=<id>` from the URL once, on first paint — the permalink
 * a shared/bookmarked link resolves to. */
function entityIdFromUrl() {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("entity");
}

export default function App() {
  const [selectedEntityId, setSelectedEntityId] = useState(entityIdFromUrl);
  const { status, entity, neighbors, claims } = useEntityDetail(selectedEntityId);
  const [raceOpen, setRaceOpen] = useState(false);
  // Kicked off here (not lazily inside race mode) so the anonymous session
  // is already established by the time the player clicks "GO" — see
  // src/hooks/useAuthUser.js.
  useAuthUser();

  // Landing default: a fresh visit with no `?entity=` in the URL used to
  // show an empty "pick something" state — now it shows a real
  // civilization instead, so there's something to look at immediately.
  // Picks a well-connected one that actually has a real profile (not an
  // auto-created stub), among the civilization/polity-type entities
  // useCivilizations() already loads for the chronology strip. Only ever
  // fires once: it's a no-op the moment anything gets selected, from the
  // URL or otherwise.
  const { status: civStatus, items: civilizations } = useCivilizations();
  useEffect(() => {
    if (selectedEntityId || civStatus !== "ready" || civilizations.length === 0) return;
    const profiled = civilizations.filter((c) => c.summary && !c.summary.startsWith("Auto-created stub"));
    const pool = profiled.length > 0 ? profiled : civilizations;
    // Well-connected, but capped: KnowledgeGraph defaults to a clean 1-hop
    // view specifically to avoid a tangled first impression (see its
    // comments) — picking the single *most* connected civilization here
    // (sometimes 100+ neighbors) would land straight back in that mess.
    const reasonable = pool.filter((c) => (c.neighbor_ids?.length ?? 0) <= 40);
    const candidates = reasonable.length > 0 ? reasonable : pool;
    const featured = candidates.reduce(
      (best, item) => ((item.neighbor_ids?.length ?? 0) > (best?.neighbor_ids?.length ?? -1) ? item : best),
      null
    );
    if (featured) setSelectedEntityId(featured.id);
  }, [selectedEntityId, civStatus, civilizations]);

  // Keep the URL in sync with the selection so the address bar is always a
  // valid permalink to what's on screen — replaceState (not push) so
  // clicking through the graph/timeline doesn't flood browser history.
  useEffect(() => {
    const url = new URL(window.location.href);
    if (selectedEntityId) url.searchParams.set("entity", selectedEntityId);
    else url.searchParams.delete("entity");
    window.history.replaceState(null, "", url);
  }, [selectedEntityId]);

  return (
    <div className="app">
      <TopBar onSelectEntity={setSelectedEntityId} onOpenRace={() => setRaceOpen(true)} />
      {raceOpen && <RaceApp onClose={() => setRaceOpen(false)} />}
      <div className="body">
        <Rail />
        <div className="left-col">
          <EntityDetail
            entityId={selectedEntityId}
            status={status}
            entity={entity}
            neighbors={neighbors}
            claims={claims}
            onSelectEntity={setSelectedEntityId}
          />
          <RelationshipTypes neighbors={neighbors} />
        </div>
        <div className="center-col">
          <div className="graph-area">
            <KnowledgeGraph entity={entity} neighbors={neighbors} onSelectEntity={setSelectedEntityId} />
          </div>
          <HorizontalTimeline entity={entity} onSelectEntity={setSelectedEntityId} />
        </div>
      </div>
    </div>
  );
}
