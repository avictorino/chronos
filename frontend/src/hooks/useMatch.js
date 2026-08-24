import { useEffect, useState } from "react";
import { COUNTDOWN_MS, subscribeToMatch } from "../lib/race";

/** Subscribes to matches/{matchId} and derives a `phase` the UI can switch
 * on directly: "countdown" | "active" | "finished". The doc's own
 * `status` field only ever holds "countdown"|"active"|"finished" too, but
 * the countdown->active flip is derived client-side from
 * countdownStartAt+COUNTDOWN_MS rather than waited on — submitMove
 * (functions/index.js) independently re-derives the same elapsed-time
 * check server-side before accepting a move, so a client acting on this
 * locally-computed "active" a few hundred ms early just means its first
 * click round-trips to the server slightly before the server's own clock
 * agrees, not a correctness issue. */
export default function useMatch(matchId) {
  const [match, setMatch] = useState(null);
  const [phase, setPhase] = useState("countdown");

  useEffect(() => {
    if (!matchId) return undefined;
    const unsubscribe = subscribeToMatch(matchId, setMatch);
    return unsubscribe;
  }, [matchId]);

  useEffect(() => {
    if (!match) return undefined;
    if (match.status === "finished") {
      setPhase("finished");
      return undefined;
    }
    if (match.status === "active") {
      setPhase("active");
      return undefined;
    }

    const raceStartAt = (match.countdownStartAt?.toMillis?.() ?? Date.now()) + COUNTDOWN_MS;
    const tick = () => setPhase(Date.now() >= raceStartAt ? "active" : "countdown");
    tick();
    const interval = setInterval(tick, 200);
    return () => clearInterval(interval);
  }, [match]);

  return { match, phase };
}
