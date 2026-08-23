import React, { useEffect, useState } from "react";

// The loading animation shown while generateEntityImage() is working: a
// hand-drawn stonemason chiseling a portrait, in the same "no UI kit, hand
// rolled" spirit as the rest of the app (see RightPanel.jsx's SVG graph).
const CAPTIONS = [
  "Consultando os escribas…",
  "Esculpindo o retrato…",
  "Misturando os pigmentos…",
  "Revelando a imagem…",
];

export default function AncientLoader({ compact = false }) {
  const [captionIndex, setCaptionIndex] = useState(0);

  useEffect(() => {
    const id = setInterval(() => {
      setCaptionIndex((i) => (i + 1) % CAPTIONS.length);
    }, 1800);
    return () => clearInterval(id);
  }, []);

  // Tiny contexts (graph nodes, ~20-36px) can't fit the illustrated scene
  // legibly — a simple pulsing dot reads better at that size than a
  // squeezed-down version of the full animation.
  if (compact) {
    return (
      <div className="ancient-loader compact">
        <span className="al-pulse-dot" />
      </div>
    );
  }

  return (
    <div className="ancient-loader">
      <svg viewBox="0 0 200 140" className="ancient-loader-svg" aria-hidden="true">
        {/* stone block being worked */}
        <rect x="120" y="58" width="50" height="38" rx="3" fill="var(--panel-2)" stroke="var(--border)" />
        <rect x="128" y="66" width="34" height="22" rx="2" fill="var(--bg-raised)" />

        {/* seated sculptor silhouette */}
        <path d="M38 132 C38 92 54 70 78 70 C102 70 118 92 118 132 Z" fill="var(--c-doc)" />
        <circle cx="78" cy="50" r="15" fill="var(--c-doc)" />

        {/* chiseling arm, pivots at the shoulder */}
        <g className="al-arm">
          <rect x="92" y="82" width="44" height="7" rx="3.5" fill="var(--accent)" />
        </g>

        {/* chip sparks off the stone */}
        <g className="al-sparks">
          <circle cx="150" cy="76" r="2" fill="var(--accent)" />
          <circle cx="157" cy="82" r="1.5" fill="var(--accent)" />
          <circle cx="147" cy="86" r="1.3" fill="var(--accent)" />
        </g>
      </svg>
      <div className="ancient-loader-caption">{CAPTIONS[captionIndex]}</div>
    </div>
  );
}
