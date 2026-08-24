import React, { useEffect, useRef, useState } from "react";
import useAuthUser from "../../hooks/useAuthUser";
import { createAiMatch, joinLobby, subscribeToLobbySlot } from "../../lib/race";

const AI_FALLBACK_MS = 5000;

/** Joins (or creates) the shared wait-slot for `pairId` on mount. Either:
 * (a) a second player is already waiting — joinLobby's own response
 * carries the matchId immediately, or (b) we become the one waiting, and
 * listen to lobby_slots/{pairId} for someone else to pair with us, with a
 * 5s local timer that falls back to an AI opponent if nobody does. See
 * the plan doc's matchmaking section for why this needs no separate
 * "lobby" collection per player and no Cloud Function trigger. */
export default function WaitingRoom({ pairId, onMatched }) {
  const { uid } = useAuthUser();
  const [error, setError] = useState(null);
  const matchedRef = useRef(false);

  useEffect(() => {
    if (!uid) return undefined;
    let cancelled = false;
    let unsubscribe = null;
    let aiTimer = null;

    function matched(matchId) {
      if (matchedRef.current) return;
      matchedRef.current = true;
      onMatched(matchId);
    }

    (async () => {
      try {
        const result = await joinLobby(pairId);
        if (cancelled) return;

        if (result.status === "matched") {
          matched(result.matchId);
          return;
        }

        unsubscribe = subscribeToLobbySlot(pairId, (slot) => {
          if (cancelled || !slot) return;
          if (slot.state === "matched" && (slot.matchedUids || []).includes(uid)) {
            matched(slot.matchedMatchId);
          }
        });

        aiTimer = setTimeout(async () => {
          if (cancelled || matchedRef.current) return;
          try {
            const aiResult = await createAiMatch(pairId);
            if (!cancelled) matched(aiResult.matchId);
          } catch {
            if (!cancelled) setError("Não deu pra iniciar a corrida contra a IA — tenta de novo.");
          }
        }, AI_FALLBACK_MS);
      } catch {
        if (!cancelled) setError("Não deu pra entrar na sala de espera — tenta de novo.");
      }
    })();

    return () => {
      cancelled = true;
      if (unsubscribe) unsubscribe();
      if (aiTimer) clearTimeout(aiTimer);
    };
  }, [pairId, uid]);

  return (
    <div className="race-panel panel">
      <div className="panel-title">Sala de espera</div>
      <div className="state-msg">
        {error || "Procurando outro jogador… se ninguém aparecer em alguns segundos, você corre contra uma IA."}
      </div>
    </div>
  );
}
