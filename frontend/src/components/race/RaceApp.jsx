import React, { useEffect, useState } from "react";
import useAuthUser from "../../hooks/useAuthUser";
import useUsername from "../../hooks/useUsername";
import useMatch from "../../hooks/useMatch";
import { getRacePair, submitMove } from "../../lib/race";
import UsernamePrompt from "./UsernamePrompt";
import PairPicker from "./PairPicker";
import WaitingRoom from "./WaitingRoom";
import RaceCountdown from "./RaceCountdown";
import RaceGraph from "./RaceGraph";
import RaceHud from "./RaceHud";
import RaceResult from "./RaceResult";
import Leaderboard from "./Leaderboard";

// Orchestrates race mode's phases as a full-screen overlay over the normal
// explorer (see App.jsx: `view === "race"`). Own client-side `step` covers
// the pre-match flow (username -> pick a pair -> wait for an opponent);
// once matched, rendering hands off to useMatch's server-driven `phase`
// (countdown -> active -> finished) for the rest, since the match doc is
// the single source of truth there.
export default function RaceApp({ onClose }) {
  const { uid, loading: authLoading } = useAuthUser();
  const { status: usernameStatus, username, setUsername } = useUsername(uid);
  const [pairId, setPairId] = useState(null);
  const [matchId, setMatchId] = useState(null);
  const [showLeaderboard, setShowLeaderboard] = useState(false);
  const [moveError, setMoveError] = useState(null);
  const [moving, setMoving] = useState(false);
  const [pair, setPair] = useState(null);
  const { match, phase } = useMatch(matchId);

  // The curated pair's precomputed distances-to-target (see race_pairs and
  // the plan's HUD section) — fetched once per pair, not subscribed.
  useEffect(() => {
    if (!pairId) {
      setPair(null);
      return;
    }
    let cancelled = false;
    getRacePair(pairId).then((p) => !cancelled && setPair(p));
    return () => {
      cancelled = true;
    };
  }, [pairId]);

  function resetToPicker() {
    setPairId(null);
    setMatchId(null);
    setShowLeaderboard(false);
    setMoveError(null);
  }

  async function handleMove(toEntityId) {
    if (!matchId || moving) return;
    setMoving(true);
    setMoveError(null);
    try {
      await submitMove(matchId, toEntityId);
    } catch (err) {
      setMoveError(err?.message || "Movimento inválido.");
    } finally {
      setMoving(false);
    }
  }

  let body;
  if (showLeaderboard) {
    body = <Leaderboard onBack={() => setShowLeaderboard(false)} />;
  } else if (authLoading || usernameStatus === "loading") {
    body = <div className="state-msg">Conectando…</div>;
  } else if (usernameStatus === "unknown") {
    body = <UsernamePrompt onDone={setUsername} />;
  } else if (!pairId) {
    body = <PairPicker onPick={setPairId} />;
  } else if (!matchId) {
    body = <WaitingRoom pairId={pairId} onMatched={setMatchId} />;
  } else if (phase === "countdown") {
    body = <RaceCountdown match={match} />;
  } else if (phase === "finished" && match) {
    body = <RaceResult match={match} myUid={uid} onPlayAgain={resetToPicker} onShowLeaderboard={() => setShowLeaderboard(true)} />;
  } else if (match) {
    const me = match.players?.[uid];
    body = (
      <div className="race-active">
        <RaceHud match={match} myUid={uid} distances={pair?.distances} />
        <RaceGraph
          currentEntityId={me?.currentEntityId}
          targetEntityId={match.targetEntityId}
          onMove={handleMove}
          disabled={moving}
        />
        {moveError && <div className="race-error race-move-error">{moveError}</div>}
      </div>
    );
  } else {
    body = <div className="state-msg">Carregando corrida…</div>;
  }

  return (
    <div className="race-overlay">
      <button className="race-close" onClick={onClose} aria-label="Fechar corrida">
        ×
      </button>
      {body}
    </div>
  );
}
