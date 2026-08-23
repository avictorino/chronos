import React, { useState } from "react";
import "./App.css";
import TopBar from "./components/TopBar";
import Rail from "./components/Rail";
import EntityDetail from "./components/EntityDetail";
import Timeline from "./components/Timeline";
import RightPanel from "./components/RightPanel";
import useEntityDetail from "./hooks/useEntityDetail";

export default function App() {
  const [selectedEntityId, setSelectedEntityId] = useState(null);
  const { status, entity, neighbors, claims } = useEntityDetail(selectedEntityId);

  return (
    <div className="app">
      <TopBar onSelectEntity={setSelectedEntityId} />
      <div className="body">
        <Rail />
        <EntityDetail
          entityId={selectedEntityId}
          status={status}
          entity={entity}
          neighbors={neighbors}
          claims={claims}
          onSelectEntity={setSelectedEntityId}
        />
        <Timeline selectedEntityId={selectedEntityId} onSelectEntity={setSelectedEntityId} />
        <RightPanel entity={entity} neighbors={neighbors} onSelectEntity={setSelectedEntityId} />
      </div>
    </div>
  );
}
