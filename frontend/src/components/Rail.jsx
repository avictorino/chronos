import React from "react";
import { IconColumns } from "./icons";

// Placeholder icon rail matching the design canvas — only "Timeline" (home)
// does anything real today; the rest are visual anchors for future tabs
// (Map/Graph/Library) that aren't built yet.
export default function Rail() {
  return (
    <nav className="rail">
      <div className="rail-icon active">
        <IconColumns size={19} />
      </div>
    </nav>
  );
}
