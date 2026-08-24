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
            <div className="panel-title graph-area-title">Knowledge Graph</div>
            <KnowledgeGraph entity={entity} neighbors={neighbors} onSelectEntity={setSelectedEntityId} />
          </div>
          <HorizontalTimeline selectedEntityId={selectedEntityId} onSelectEntity={setSelectedEntityId} />
        </div>
      </div>
    </div>
  );
}
