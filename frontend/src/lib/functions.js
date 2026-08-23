// Calls into the `functions/` Cloud Functions app — currently just the
// on-demand entity-portrait generator (functions/index.js). Everything
// here is a thin wrapper around httpsCallable; the actual OpenAI call and
// Storage upload happen server-side, so the API key never reaches the
// browser and this file never writes to Firestore/Storage directly.

import { httpsCallable } from "firebase/functions";
import { functions } from "./firebase";

const _generateEntityImage = httpsCallable(functions, "generateEntityImage");

/** Ask the backend for this entity's portrait. Cache hits (the entity
 * already has an image) come back immediately with no OpenAI call.
 *
 * Returns { outcome: "cached"|"generated"|"ineligible"|"in_progress"|
 * "budget_exceeded", url? } — see functions/index.js for exact semantics. */
export async function requestEntityImage(entityId) {
  const { data } = await _generateEntityImage({ entityId });
  return data;
}
