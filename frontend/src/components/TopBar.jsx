import React, { useEffect, useRef, useState } from "react";
import { IconColumns, IconSearch } from "./icons";
import { searchEntitiesByName } from "../lib/firestore";

export default function TopBar({ onSelectEntity }) {
  const [term, setTerm] = useState("");
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef(null);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!term.trim()) {
      setResults([]);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      try {
        setResults(await searchEntitiesByName(term));
        setOpen(true);
      } catch {
        // Firestore not reachable yet (no export run, or rules not set) —
        // fail quietly here, the panels below surface the real state.
        setResults([]);
      }
    }, 250);
    return () => clearTimeout(debounceRef.current);
  }, [term]);

  return (
    <header className="topbar">
      <div className="brand">
        <IconColumns size={26} />
        <div className="brand-text">
          <span className="brand-name">Chronos</span>
          <span className="brand-sub">Explore Ancient History</span>
        </div>
      </div>

      <label className="search">
        <IconSearch />
        <input
          type="text"
          placeholder="Search people, places, events, documents..."
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          onFocus={() => term && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
        />
        {open && results.length > 0 && (
          <div className="search-results">
            {results.map((r) => (
              <div
                key={r.id}
                className="search-result"
                onMouseDown={() => {
                  onSelectEntity(r.id);
                  setTerm(r.canonical_name);
                  setOpen(false);
                }}
              >
                <span>{r.canonical_name}</span>
                <span className="search-result-type">{r.entity_type?.toLowerCase()}</span>
              </div>
            ))}
          </div>
        )}
      </label>

      <div className="avatar" />
    </header>
  );
}
