import React, { useEffect, useState } from "react";
import { listRacePairs } from "../../lib/race";

/** Curated-pairs picker (see the plan doc: pairs are hand-curated via
 * ingestion/scripts/curate_race_pairs.py, not generated on the fly, since
 * the graph isn't globally connected yet). `onPick(pairId)` moves on to
 * the waiting room. */
export default function PairPicker({ onPick }) {
  const [state, setState] = useState({ status: "loading", pairs: [] });

  useEffect(() => {
    let cancelled = false;
    listRacePairs()
      .then((pairs) => !cancelled && setState({ status: "ready", pairs }))
      .catch(() => !cancelled && setState({ status: "error", pairs: [] }));
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.status === "loading") {
    return <div className="state-msg">Carregando corridas disponíveis…</div>;
  }
  if (state.status === "error") {
    return <div className="state-msg">Não deu pra carregar as corridas — tenta de novo.</div>;
  }
  if (state.pairs.length === 0) {
    return (
      <div className="state-msg">
        Nenhuma corrida disponível ainda — o grafo ingerido até agora não tem pares curados. Volte em breve.
      </div>
    );
  }

  return (
    <div className="race-panel panel">
      <div className="panel-title">Escolha uma corrida</div>
      <div className="race-pair-list">
        {state.pairs.map((pair) => (
          <button key={pair.id} type="button" className="race-pair-option" onClick={() => onPick(pair.id)}>
            <span className="race-pair-label">{pair.label}</span>
            <span className="race-pair-hops">{pair.optimalHops} cliques no ótimo</span>
          </button>
        ))}
      </div>
    </div>
  );
}
