// Small set of inline stroke icons (24x24 viewBox, currentColor) reused
// across the app — matches the icon style drawn in the design canvas.
import React from "react";

const base = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.7,
  strokeLinecap: "round",
  strokeLinejoin: "round",
};

export function IconColumns({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
      <path d="M4 21h16" />
      <path d="M6 21V9M10 21V9M14 21V9M18 21V9" />
      <path d="M4 9l8-5 8 5" />
    </svg>
  );
}

export function IconSearch({ size = 15 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-4.3-4.3" />
    </svg>
  );
}

export function IconWarning({ size = 13 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
      <path d="M12 3 2 20h20L12 3Z" />
      <path d="M12 10v4M12 17.2v.1" />
    </svg>
  );
}

export function IconCheck({ size = 12 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...base} strokeWidth={2}>
      <path d="M5 12.5 9.5 17 19 7" />
    </svg>
  );
}

export function IconLink({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
      <circle cx="6" cy="6" r="2.4" fill="none" />
      <circle cx="18" cy="19" r="2.4" fill="none" />
      <circle cx="18" cy="5" r="2.4" fill="none" />
      <path d="m8.1 10.9 7.8-4.4M6 8v8M8.1 13.1l7.8 4.4" />
    </svg>
  );
}

export function IconBook({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
      <path d="M5 4h9l5 5v11H5Z" />
      <path d="M14 4v5h5" />
    </svg>
  );
}
