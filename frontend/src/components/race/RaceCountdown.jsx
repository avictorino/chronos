import React, { useEffect, useState } from "react";
import { COUNTDOWN_MS } from "../../lib/race";

/** "3, 2, 1, GO" derived purely from match.countdownStartAt — both
 * players' clients count down off the same server timestamp, no ticking
 * server involved. */
export default function RaceCountdown({ match }) {
  const [label, setLabel] = useState("");

  useEffect(() => {
    const startMs = match?.countdownStartAt?.toMillis?.();
    if (!startMs) return undefined;
    const raceStartAt = startMs + COUNTDOWN_MS;

    function tick() {
      const remaining = raceStartAt - Date.now();
      setLabel(remaining <= 0 ? "GO!" : String(Math.ceil(remaining / 1000)));
    }
    tick();
    const interval = setInterval(tick, 100);
    return () => clearInterval(interval);
  }, [match]);

  return (
    <div className="race-countdown">
      <div className="race-countdown-number">{label}</div>
    </div>
  );
}
