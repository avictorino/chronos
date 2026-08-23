/**
 * Chronos — on-demand entity portrait generation.
 *
 * Called by the frontend (httpsCallable, see frontend/src/lib/functions.js)
 * when it renders an entity that has no `image_url` yet. Generates exactly
 * once per entity and caches the result forever after:
 *
 *   1. Read the entity doc. If `image_url` is already set, return it —
 *      no OpenAI call, ever, for an entity that's already been generated.
 *      This is the cache: repeat visits never "ping" OpenAI again.
 *   2. If the entity type isn't eligible (people / places / artifacts —
 *      see ELIGIBLE_TYPES), return { outcome: "ineligible" } and stop.
 *   3. Claim the entity with a Firestore transaction (`image_status:
 *      "generating"`) so two visitors opening the same never-generated
 *      entity at the same moment don't both pay for a generation.
 *   4. Call the OpenAI Images API (gpt-image-1, quality "low" — the
 *      cheapest tier it offers) with a prompt built from the entity's own
 *      data.
 *   5. Upload the result to Firebase Storage and write the URL (plus
 *      model/version metadata) back onto the entity doc.
 *
 * The ingestion pipeline (ingestion/app/export/firestore_export.py) never
 * writes these fields, and its batch export now writes with merge:true
 * specifically so it never clobbers what this function generates.
 */

const { onCall, HttpsError } = require("firebase-functions/v2/https");
const { defineSecret } = require("firebase-functions/params");
const { setGlobalOptions } = require("firebase-functions/v2");
const { initializeApp } = require("firebase-admin/app");
const { getFirestore, FieldValue } = require("firebase-admin/firestore");
const { getStorage } = require("firebase-admin/storage");
const { OpenAI } = require("openai");

initializeApp();
setGlobalOptions({ region: "us-central1", maxInstances: 10 });

const OPENAI_API_KEY = defineSecret("OPENAI_API_KEY");

// Lazy, not module-top-level: `firebase deploy`'s discovery step imports
// this file in a sandbox to enumerate exports without ever invoking the
// handler, and eagerly resolving getStorage().bucket() there (which needs
// to resolve the project's default bucket name) reliably blew past that
// step's timeout ("Cannot determine backend specification"). Calling these
// inside the handler instead means the first real invocation pays the
// (cheap, synchronous) cost, not the deploy-time analysis.
//
// Note: firebase-admin v13+ dropped the old `admin.firestore()` /
// `admin.storage()` namespace API in favor of these modular imports.
function db() {
  return getFirestore();
}
function bucket() {
  return getStorage().bucket();
}

// Only these get generated automatically — "pessoas, cidades e outros
// artefatos" from the product ask. Everything else (CIVILIZATION, POLITY,
// RELIGION, CONCEPT, ...) falls back to the frontend's plain color-dot
// placeholder for now; add types here later if that changes.
const ELIGIBLE_TYPES = new Set([
  "PERSON",
  "PLACE",
  "CITY",
  "REGION",
  "DOCUMENT",
  "TEXT",
  "INSCRIPTION",
]);

const PROMPT_VERSION = "v1";
const IMAGE_MODEL = "gpt-image-1";
const IMAGE_QUALITY = "low"; // cheapest tier gpt-image-1 offers
const IMAGE_SIZE = "1024x1024"; // smallest size gpt-image-1 supports

// Soft daily cap on *actual generations* (cache hits never count against
// this) — cheap insurance against a burst of abuse running up the OpenAI
// bill while this is a public callable. Raise it once you trust traffic,
// or move to a per-user/App-Check-based limit later.
const DAILY_GENERATION_BUDGET = 200;

/** Builds an entity-type-appropriate prompt from real Firestore data — never
 * a hand-placed generic prompt, same "real data, not illustration" spirit
 * as the rest of the frontend (see RightPanel.jsx). */
function promptFor(entity) {
  const name = entity.canonical_name || "an unnamed figure from antiquity";
  const summary = entity.summary ? ` Context: ${entity.summary}` : "";
  const type = entity.entity_type;

  if (type === "PERSON") {
    const titles = Array.isArray(entity.titles) && entity.titles.length
      ? ` (${entity.titles.join(", ")})`
      : "";
    return (
      `Portrait illustration of ${name}${titles}, a figure from ancient history.` +
      `${summary} Historically plausible, painterly digital illustration, ` +
      `dramatic lighting, museum-quality historical art, no text or watermarks.`
    );
  }

  if (type === "PLACE" || type === "CITY" || type === "REGION") {
    return (
      `Wide illustrated landscape view of the ancient place of ${name}.` +
      `${summary} Historical illustration style, painterly, no modern ` +
      `elements, no text or watermarks.`
    );
  }

  // DOCUMENT / TEXT / INSCRIPTION
  return (
    `Museum-photography-style image of an ancient artifact: ${name}.` +
    `${summary} Weathered, period-accurate materials and texture, neutral ` +
    `studio background, no text or watermarks.`
  );
}

function storagePathFor(entity) {
  const type = (entity.entity_type || "unknown").toLowerCase();
  return `entity-images/${type}/${entity.id}.webp`;
}

async function callOpenAI(apiKey, prompt) {
  const client = new OpenAI({ apiKey });
  const result = await client.images.generate({
    model: IMAGE_MODEL,
    prompt,
    quality: IMAGE_QUALITY,
    size: IMAGE_SIZE,
    output_format: "webp",
    n: 1,
  });
  const b64 = result.data?.[0]?.b64_json;
  if (!b64) throw new Error("OpenAI Images API returned no image data");
  return Buffer.from(b64, "base64");
}

/** Uploads the generated bytes and returns a URL the frontend can hot-link
 * directly. Deliberately NOT bucket.file().publicUrl() / a public ACL —
 * the default Storage bucket has Uniform Bucket-Level Access, which
 * rejects legacy per-object ACLs. Public read instead comes from
 * storage.rules (`allow read: if true`, mirroring firestore.rules), and
 * this is the URL shape that actually goes through those rules. */
async function uploadImage(path, bytes) {
  const bkt = bucket();
  const file = bkt.file(path);
  await file.save(bytes, {
    contentType: "image/webp",
    metadata: { cacheControl: "public, max-age=31536000, immutable" },
  });
  return `https://firebasestorage.googleapis.com/v0/b/${bkt.name}/o/${encodeURIComponent(path)}?alt=media`;
}

async function withinBudget() {
  const today = new Date().toISOString().slice(0, 10);
  const ref = db().collection("system").doc("imageGenerationBudget");
  return db().runTransaction(async (tx) => {
    const snap = await tx.get(ref);
    const data = snap.exists ? snap.data() : {};
    const count = data.date === today ? data.count || 0 : 0;
    if (count >= DAILY_GENERATION_BUDGET) return false;
    tx.set(ref, { date: today, count: count + 1 }, { merge: true });
    return true;
  });
}

exports.generateEntityImage = onCall(
  { secrets: [OPENAI_API_KEY], timeoutSeconds: 60, memory: "512MiB" },
  async (request) => {
    const entityId = request.data?.entityId;
    if (!entityId || typeof entityId !== "string") {
      throw new HttpsError("invalid-argument", "entityId is required");
    }

    const entityRef = db().collection("entities").doc(entityId);

    // Claim the entity (or short-circuit on cache hit / ineligible type /
    // an in-flight generation from another request) inside one transaction
    // so concurrent requests for the same never-generated entity can't
    // both slip past the check and both call OpenAI.
    const claim = await db().runTransaction(async (tx) => {
      const snap = await tx.get(entityRef);
      if (!snap.exists) {
        throw new HttpsError("not-found", `Entity ${entityId} not found`);
      }
      const entity = { id: snap.id, ...snap.data() };

      if (entity.image_url) {
        return { outcome: "cached", url: entity.image_url };
      }
      if (!ELIGIBLE_TYPES.has(entity.entity_type)) {
        return { outcome: "ineligible" };
      }
      if (entity.image_status === "generating") {
        return { outcome: "in_progress" };
      }

      tx.set(entityRef, { image_status: "generating" }, { merge: true });
      return { outcome: "claimed", entity };
    });

    if (claim.outcome !== "claimed") {
      return claim;
    }

    try {
      if (!(await withinBudget())) {
        await entityRef.set({ image_status: null }, { merge: true });
        return { outcome: "budget_exceeded" };
      }

      const prompt = promptFor(claim.entity);
      const bytes = await callOpenAI(OPENAI_API_KEY.value(), prompt);
      const path = storagePathFor(claim.entity);
      const imageUrl = await uploadImage(path, bytes);

      await entityRef.set(
        {
          image_url: imageUrl,
          image_generated_at: FieldValue.serverTimestamp(),
          image_model: IMAGE_MODEL,
          image_prompt_version: PROMPT_VERSION,
          image_status: null,
        },
        { merge: true }
      );

      return { outcome: "generated", url: imageUrl };
    } catch (err) {
      // Release the claim so a later request retries instead of getting
      // stuck behind a permanently "generating" entity.
      await entityRef.set({ image_status: null }, { merge: true }).catch(() => {});
      console.error(`generateEntityImage(${entityId}) failed:`, err);
      throw new HttpsError("internal", "Image generation failed");
    }
  }
);
