// Read-only data access over the knowledge graph written directly by
// `ingestion/app/persistence/repositories.py`. Every function here is a
// plain read — nothing in the frontend ever writes to Firestore (see the
// root README and the security rules: public read, admin-only write).

import {
  collection,
  doc,
  documentId,
  getDoc,
  getDocs,
  limit as fsLimit,
  or,
  orderBy,
  query,
  where,
} from "firebase/firestore";
import { db } from "./firebase";

// Firestore's `in` / `documentId() in [...]` operator caps at 30 values per
// clause — batch anything larger than that instead of failing silently.
const IN_CLAUSE_LIMIT = 30;

function chunk(items, size) {
  const out = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

function withId(snap) {
  return { id: snap.id, ...snap.data() };
}

/** A single entity by id, or null if it hasn't been exported (yet). */
export async function getEntity(id) {
  const snap = await getDoc(doc(db, "entities", id));
  return snap.exists() ? withId(snap) : null;
}

/** Entities of one type (e.g. "civilization", "person"), newest-created first. */
export async function listEntitiesByType(entityType, { limitTo = 50 } = {}) {
  const q = query(
    collection(db, "entities"),
    where("entity_type", "==", entityType),
    fsLimit(limitTo)
  );
  const snap = await getDocs(q);
  return snap.docs.map(withId);
}

/** Entities matching several types at once (Firestore `in` caps at 30 values,
 * which is never a concern for the 6-7 entity-type tags we actually use). */
export async function listEntitiesByTypes(entityTypes, { limitTo = 200 } = {}) {
  const q = query(
    collection(db, "entities"),
    where("entity_type", "in", entityTypes),
    fsLimit(limitTo)
  );
  const snap = await getDocs(q);
  return snap.docs.map(withId);
}

/** Batched id -> document lookup (chunks the `in` clause at 30 ids). */
export async function getEntitiesByIds(ids) {
  const uniqueIds = [...new Set(ids)].filter(Boolean);
  if (uniqueIds.length === 0) return [];
  const batches = await Promise.all(
    chunk(uniqueIds, IN_CLAUSE_LIMIT).map((batchIds) =>
      getDocs(query(collection(db, "entities"), where(documentId(), "in", batchIds)))
    )
  );
  return batches.flatMap((snap) => snap.docs.map(withId));
}

/** 1-hop neighbors of an entity, using the `neighbor_ids` array the export
 * denormalizes onto every entity document — a single extra read, no query. */
export async function getNeighbors(entityId) {
  const entity = await getEntity(entityId);
  if (!entity?.neighbor_ids?.length) return [];
  return getEntitiesByIds(entity.neighbor_ids);
}

/** Relationships touching an entity on either side — two queries merged
 * client-side (Firestore doesn't join `source_entity_id`/`target_entity_id`
 * in one query without a composite `or()` index; this keeps it simple). */
export async function getRelationshipsFor(entityId) {
  const [asSource, asTarget] = await Promise.all([
    getDocs(query(collection(db, "relationships"), where("source_entity_id", "==", entityId))),
    getDocs(query(collection(db, "relationships"), where("target_entity_id", "==", entityId))),
  ]);
  const seen = new Map();
  for (const s of [...asSource.docs, ...asTarget.docs]) seen.set(s.id, withId(s));
  return [...seen.values()];
}

/** Claims (subject or object) about an entity — never displayed as fact,
 * only as unverified/LLM-generated claims (see domain model). */
export async function getClaimsFor(entityId) {
  const q = query(
    collection(db, "claims"),
    or(where("subject_id", "==", entityId), where("object_id", "==", entityId)),
    fsLimit(20)
  );
  const snap = await getDocs(q);
  return snap.docs.map(withId);
}

/** Chunks linked to an entity (source text extracted during ingestion). */
export async function getChunksFor(entityId, { limitTo = 12 } = {}) {
  const q = query(
    collection(db, "chunks"),
    where("entity_ids", "array-contains", entityId),
    fsLimit(limitTo)
  );
  const snap = await getDocs(q);
  return snap.docs.map(withId);
}

/** Every event that mentions an entity (as person/place/polity). */
export async function getEventsFor(entityId) {
  const [asPerson, asPlace, asPolity] = await Promise.all([
    getDocs(query(collection(db, "events"), where("people", "array-contains", entityId))),
    getDocs(query(collection(db, "events"), where("places", "array-contains", entityId))),
    getDocs(query(collection(db, "events"), where("polities", "array-contains", entityId))),
  ]);
  const seen = new Map();
  for (const s of [...asPerson.docs, ...asPlace.docs, ...asPolity.docs]) seen.set(s.id, withId(s));
  return [...seen.values()];
}

/** Lightweight name search: fetches a page of entities and filters client
 * side. Fine at this dataset's size (low hundreds); swap for a proper
 * prefix/vector search once the graph is much larger. */
export async function searchEntitiesByName(term, { limitTo = 300 } = {}) {
  const needle = term.trim().toLowerCase();
  if (!needle) return [];
  const snap = await getDocs(query(collection(db, "entities"), fsLimit(limitTo)));
  return snap.docs
    .map(withId)
    .filter((e) => {
      const haystack = [e.canonical_name, ...(e.aliases || [])].join(" ").toLowerCase();
      return haystack.includes(needle);
    })
    .slice(0, 20);
}

/** All ingestion runs, most recent first — used for the "last exported" hint. */
export async function listIngestionRuns({ limitTo = 10 } = {}) {
  const q = query(collection(db, "ingestion_runs"), orderBy("started_at", "desc"), fsLimit(limitTo));
  const snap = await getDocs(q);
  return snap.docs.map(withId);
}
