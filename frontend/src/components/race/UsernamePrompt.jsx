import React, { useState } from "react";
import { claimUsername } from "../../lib/race";

// A "simple list" per the spec — flavor-appropriate quick picks rather than
// a blank form, so joining a race never stalls on typing. Free text still
// works via the input above them.
const SUGGESTIONS = [
  "Escriba de Nínive",
  "Arauto Babilônio",
  "Cronista do Tigre",
  "Mensageiro de Uruk",
  "Guardião de Assur",
  "Viajante do Eufrates",
  "Selo de Argila",
  "Zigurate Errante",
];

/** Shown once per browser before a player's first race (see
 * lib/race.js::getCachedUsername) — picks a name and claims users/{uid}
 * via the claimUsername callable. `onDone(username)` fires after the
 * server confirms it. */
export default function UsernamePrompt({ onDone }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function submit(name) {
    const trimmed = name.trim();
    if (trimmed.length < 2 || trimmed.length > 20) {
      setError("Escolha um nome entre 2 e 20 caracteres.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { username } = await claimUsername(trimmed);
      onDone(username);
    } catch {
      setError("Não deu pra salvar o nome — tenta de novo.");
      setBusy(false);
    }
  }

  return (
    <div className="race-panel panel">
      <div className="panel-title">Escolha seu nome de corredor</div>
      <form
        className="race-username-form"
        onSubmit={(e) => {
          e.preventDefault();
          submit(value);
        }}
      >
        <input
          className="race-username-input"
          type="text"
          placeholder="Seu nome..."
          value={value}
          maxLength={20}
          onChange={(e) => setValue(e.target.value)}
          disabled={busy}
          autoFocus
        />
        <button type="submit" className="race-btn-primary" disabled={busy || !value.trim()}>
          {busy ? "Salvando…" : "Confirmar"}
        </button>
      </form>
      {error && <div className="race-error">{error}</div>}
      <div className="race-username-suggestions">
        {SUGGESTIONS.map((name) => (
          <button
            key={name}
            type="button"
            className="race-suggestion-chip"
            onClick={() => submit(name)}
            disabled={busy}
          >
            {name}
          </button>
        ))}
      </div>
    </div>
  );
}
