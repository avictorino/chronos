// Maps the 6 persisted entity subtypes (see ingestion/app/domain/models.py)
// down to the 7 legend colors used across the design canvas. `entity_type` on
// a document is the finer-grained enum (e.g. "kingdom"), so this normalizes
// it to the coarser tag the color legend is drawn at.
// Matches ingestion/app/domain/enums.py::EntityType (values are uppercase).
const TYPE_TO_COLOR_VAR = {
  CIVILIZATION: "--c-civ",
  PERSON: "--c-person",
  PLACE: "--c-place",
  CITY: "--c-place",
  REGION: "--c-place",
  POLITY: "--c-polity",
  EMPIRE: "--c-polity",
  KINGDOM: "--c-polity",
  DYNASTY: "--c-polity",
  DOCUMENT: "--c-doc",
  TEXT: "--c-doc",
  INSCRIPTION: "--c-doc",
  RELIGION: "--c-concept",
  DEITY: "--c-concept",
  CULTURE: "--c-concept",
  LANGUAGE: "--c-concept",
  CONCEPT: "--c-concept",
};

export function colorVarForType(entityType) {
  return TYPE_TO_COLOR_VAR[entityType?.toUpperCase()] ?? "--c-doc";
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
