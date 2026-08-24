import React, { useEffect, useState } from "react";
import { COUNTDOWN_MS, getAiCurrentEntityId } from "../../lib/race";

/** Sticky HUD (top bar per the plan's mobile-first layout, not a side
 * panel) showing the player's own click count and, per the spec, an
 * estimate of how many clicks the opponent has left — derived from the
 * curated pair's precomputed `distances` map (see race_pairs/{pairId}),
 * so it's a plain lookup that automatically rises if the opponent wanders
 * off the optimal path. Ticks locally (not just on Firestore updates) so
 * an AI opponent's derived position — which never itself triggers a
 * Firestore write, see lib/race.js::getAiCurrentEntityId — stays current. */
export default function RaceHud({ match, myUid, distances }) {
  const [, forceTick] = useState(0);

  useEffect(() => {
    if (!match?.aiSchedule) return undefined; // only an AI opponent needs local ticking
    const interval = setInterval(() => forceTick((n) => n + 1), 1000);
    return () => clearInterval(interval);
  }, [match]);

  if (!match) return null;
  const players = match.players || {};
  const me = players[myUid];
  const opponentUid = Object.keys(players).find((id) => id !== myUid);
  const opponent = opponentUid ? players[opponentUid] : null;
  if (!me || !opponent) return null;

  const opponentEntityId = opponent.isAI ? getAiCurrentEntityId(match) || opponent.currentEntityId : opponent.currentEntityId;
  const opponentRemaining = distances ? distances[opponentEntityId] : undefined;

  const raceStartAt = (match.countdownStartAt?.toMillis?.() ?? Date.now()) + COUNTDOWN_MS;
  const elapsedSec = Math.max(0, Math.round((Date.now() - raceStartAt) / 1000));

  return (
    <div className="race-hud">
      <div className="race-hud-stat">
        <span className="race-hud-label">Você</span>
        <span className="race-hud-value">{me.clicks} cliques</span>
      </div>
      <div className="race-hud-timer">{elapsedSec}s</div>
      <div className="race-hud-stat race-hud-stat-right">
        <span className="race-hud-label">{opponent.username}</span>
        <span className="race-hud-value">
          {opponentRemaining === undefined ? "posição desconhecida" : `~${opponentRemaining} pra terminar`}
        </span>
      </div>
    </div>
  );
}
