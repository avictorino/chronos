import React, { useEffect, useState } from "react";
import { listLeaderboard } from "../../lib/race";

/** Ranked by wins (primary) — ties aren't broken client-side by
 * avgExtraClicks in the sort itself (that would need a composite index for
 * a query this simple query doesn't have), it's just shown alongside as
 * the efficiency signal per the plan's ranking decision. */
export default function Leaderboard({ onBack }) {
  const [state, setState] = useState({ status: "loading", players: [] });

  useEffect(() => {
    let cancelled = false;
    listLeaderboard()
      .then((players) => !cancelled && setState({ status: "ready", players }))
      .catch(() => !cancelled && setState({ status: "error", players: [] }));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="race-panel panel race-leaderboard-panel">
      <div className="panel-title">Melhores jogadores</div>

      {state.status === "loading" && <div className="state-msg">Carregando…</div>}
      {state.status === "error" && <div className="state-msg">Não deu pra carregar o ranking — tenta de novo.</div>}
      {state.status === "ready" && state.players.length === 0 && (
        <div className="state-msg">Ninguém correu ainda — seja o primeiro.</div>
      )}

      {state.status === "ready" && state.players.length > 0 && (
        <ol className="race-leaderboard-list">
          {state.players.map((p, i) => (
            <li key={p.id} className="race-leaderboard-row">
              <span className="race-leaderboard-rank">{i + 1}</span>
              <span className="race-leaderboard-name">{p.username}</span>
              <span className="race-leaderboard-wins">{p.wins} vitórias</span>
              <span className="race-leaderboard-extra">+{Number(p.avgExtraClicks || 0).toFixed(1)} cliques (méd.)</span>
            </li>
          ))}
        </ol>
      )}

      {onBack && (
        <button className="race-btn-secondary race-leaderboard-back" onClick={onBack}>
          Voltar
        </button>
      )}
    </div>
  );
}
