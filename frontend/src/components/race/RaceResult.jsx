import React from "react";

export default function RaceResult({ match, myUid, onPlayAgain, onShowLeaderboard }) {
  const players = match.players || {};
  const me = players[myUid];
  const opponentUid = Object.keys(players).find((id) => id !== myUid);
  const opponent = opponentUid ? players[opponentUid] : null;
  const won = match.winnerUid === myUid;

  return (
    <div className="race-panel panel">
      <div className="panel-title">{won ? "Você venceu! 🏆" : "Você perdeu"}</div>

      <div className="race-result-row">
        <span>Você</span>
        <strong>
          {me?.clicks ?? "—"} cliques
          {me?.extraClicks != null && me.extraClicks > 0 && ` (+${me.extraClicks} do ótimo)`}
        </strong>
      </div>
      <div className="race-result-row">
        <span>{opponent?.username || "Oponente"}</span>
        <strong>
          {opponent?.clicks ?? "—"} cliques
          {opponent?.extraClicks != null && opponent.extraClicks > 0 && ` (+${opponent.extraClicks})`}
        </strong>
      </div>

      <div className="race-result-actions">
        <button className="race-btn-primary" onClick={onPlayAgain}>
          Correr de novo
        </button>
        <button className="race-btn-secondary" onClick={onShowLeaderboard}>
          Ver ranking
        </button>
      </div>
    </div>
  );
}
