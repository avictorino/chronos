// Maps the 6 persisted entity subtypes (see ingestion/app/domain/models.py)
// down to the 7 legend colors used across the design canvas. `entity_type` on
// a document is the finer-grained enum (e.g. "kingdom"), so this normalizes
// it to the coarser tag the color legend is drawn at.
const TYPE_TO_COLOR_VAR = {
  civilization: "--c-civ",
  person: "--c-person",
  place: "--c-place",
  city: "--c-place",
  region: "--c-place",
  polity: "--c-polity",
  empire: "--c-polity",
  kingdom: "--c-polity",
  dynasty: "--c-polity",
  document: "--c-doc",
  text: "--c-doc",
  inscription: "--c-doc",
  religion: "--c-concept",
  deity: "--c-concept",
  culture: "--c-concept",
  language: "--c-concept",
  concept: "--c-concept",
};

export function colorVarForType(entityType) {
  return TYPE_TO_COLOR_VAR[entityType] ?? "--c-doc";
}

export function confidenceColorVar(confidence) {
  if (confidence == null) return "--text-faint";
  if (confidence >= 0.75) return "--conf-high";
  if (confidence >= 0.5) return "--conf-med";
  return "--conf-low";
}

export function formatYearRange(startYear, endYear) {
  if (startYear == null && endYear == null) return null;
  const fmt = (y) => (y < 0 ? `${Math.abs(y)} BCE` : `${y} CE`);
  if (startYear != null && endYear != null) return `${fmt(startYear)} – ${fmt(endYear)}`;
  return fmt(startYear ?? endYear);
}
