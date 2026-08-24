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
const { onSchedule } = require("firebase-functions/v2/scheduler");
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

// Every EntityType (see ingestion/app/domain/enums.py) gets a portrait —
// deliberately not restricted to a handful of "obviously visual" types.
// v1 only covered PERSON/PLACE/CITY/REGION/DOCUMENT/TEXT/INSCRIPTION, which
// silently refused entities like "Ziggurat" (classified CONCEPT, but very
// much a physical, paintable structure) with no feedback in the UI —
// confusing from a click. Cost stays bounded either way: each entity is
// still generated at most once, ever (see the cache check above).
const ELIGIBLE_TYPES = new Set([
  "PERSON",
  "PLACE",
  "CITY",
  "REGION",
  "CIVILIZATION",
  "POLITY",
  "EMPIRE",
  "KINGDOM",
  "DYNASTY",
  "DOCUMENT",
  "TEXT",
  "INSCRIPTION",
  "RELIGION",
  "DEITY",
  "CULTURE",
  "LANGUAGE",
  "CONCEPT",
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

  if (["CIVILIZATION", "POLITY", "EMPIRE", "KINGDOM", "DYNASTY"].includes(type)) {
    return (
      `Symbolic emblem-style illustration representing the ancient ` +
      `${type.toLowerCase()} of ${name}.${summary} Banner or crest ` +
      `composition, painterly historical illustration, no text or watermarks.`
    );
  }

  if (type === "DOCUMENT" || type === "TEXT" || type === "INSCRIPTION") {
    return (
      `Museum-photography-style image of an ancient artifact: ${name}.` +
      `${summary} Weathered, period-accurate materials and texture, neutral ` +
      `studio background, no text or watermarks.`
    );
  }

  if (type === "DEITY" || type === "RELIGION") {
    return (
      `Ancient religious iconography depicting ${name}.${summary} Statue or ` +
      `temple-relief style, historically plausible imagery from the period, ` +
      `painterly illustration, no text or watermarks.`
    );
  }

  // CULTURE / LANGUAGE / CONCEPT / anything else — a generic but still
  // grounded-in-the-summary historical illustration, not a blank fallback.
  return (
    `Symbolic historical illustration representing the concept of ${name} ` +
    `in the ancient world.${summary} Painterly, evocative, no text or ` +
    `watermarks.`
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

/**
 * Chronos — race mode (multiplayer graph race, see the root plan doc).
 *
 * Same posture as generateEntityImage above: firestore.rules stays
 * `allow write: if false` for every collection, including the new
 * `race_pairs`/`lobby_slots`/`matches`/`users` ones — every mutation for
 * race mode goes through one of the callables below (Admin SDK, ignores
 * rules), which is also where all anti-cheat validation lives, since the
 * whole point of this mode is pairing with strangers on the internet.
 *
 * COUNTDOWN_MS must match the constant of the same name the frontend uses
 * to derive `raceStartAt = countdownStartAt + COUNTDOWN_MS` — it's not
 * read from the match doc, both sides just need to agree on it.
 */
const COUNTDOWN_MS = 3000;

exports.claimUsername = onCall({}, async (request) => {
  const uid = request.auth?.uid;
  if (!uid) throw new HttpsError("unauthenticated", "Sign in first.");

  const username = String(request.data?.username || "").trim();
  if (username.length < 2 || username.length > 20) {
    throw new HttpsError("invalid-argument", "Username must be 2-20 characters.");
  }

  const ref = db().collection("users").doc(uid);
  await db().runTransaction(async (tx) => {
    const snap = await tx.get(ref);
    if (snap.exists) {
      tx.set(ref, { username, updatedAt: FieldValue.serverTimestamp() }, { merge: true });
    } else {
      tx.set(ref, {
        username,
        wins: 0,
        races: 0,
        totalExtraClicks: 0,
        avgExtraClicks: 0,
        createdAt: FieldValue.serverTimestamp(),
        updatedAt: FieldValue.serverTimestamp(),
      });
    }
  });

  return { uid, username };
});

// Synthetic key for the AI opponent inside a match's `players` map — not a
// real Firebase Auth uid (the AI never signs in, never gets a users/{uid}
// doc), just a stable id distinct from any real uid.
const AI_UID = "ai";

function newPlayerState(username, isAI, startEntityId) {
  return {
    username,
    isAI,
    currentEntityId: startEntityId,
    clicks: 0,
    path: [{ entityId: startEntityId, atMs: 0 }],
    finishedAtMs: null,
    extraClicks: null,
  };
}

async function requireUsername(uid) {
  const snap = await db().collection("users").doc(uid).get();
  if (!snap.exists || !snap.data().username) {
    throw new HttpsError("failed-precondition", "Claim a username first (see claimUsername).");
  }
  return snap.data().username;
}

async function requireActiveRacePair(pairId) {
  const snap = await db().collection("race_pairs").doc(pairId).get();
  if (!snap.exists || snap.data().active === false) {
    throw new HttpsError("not-found", `race_pairs/${pairId} does not exist or is inactive.`);
  }
  return { id: snap.id, ...snap.data() };
}

exports.joinLobby = onCall({}, async (request) => {
  const uid = request.auth?.uid;
  if (!uid) throw new HttpsError("unauthenticated", "Sign in first.");

  const pairId = String(request.data?.pairId || "");
  if (!pairId) throw new HttpsError("invalid-argument", "pairId is required.");

  const username = await requireUsername(uid);
  const pair = await requireActiveRacePair(pairId);

  const slotRef = db().collection("lobby_slots").doc(pairId);
  const matchesRef = db().collection("matches");

  return db().runTransaction(async (tx) => {
    const slotSnap = await tx.get(slotRef);
    const slot = slotSnap.exists ? slotSnap.data() : null;

    if (!slot || slot.state !== "waiting") {
      // Slot is free (nobody waiting, or left over from a previous match) —
      // claim it and wait. The other branch below is what a second player
      // sees when they call joinLobby while this is still true.
      tx.set(slotRef, {
        state: "waiting",
        waitingUid: uid,
        waitingUsername: username,
        joinedAt: FieldValue.serverTimestamp(),
        matchedMatchId: null,
        matchedUids: null,
      });
      return { status: "waiting" };
    }

    if (slot.waitingUid === uid) {
      // Idempotent retry (e.g. a network retry of the original call) —
      // no-op, same response.
      return { status: "waiting" };
    }

    // Someone else is already waiting for this pair — pair up.
    const matchRef = matchesRef.doc();
    tx.set(matchRef, {
      pairId,
      startEntityId: pair.startEntityId,
      targetEntityId: pair.targetEntityId,
      status: "countdown",
      countdownStartAt: FieldValue.serverTimestamp(),
      winnerUid: null,
      aiSchedule: null,
      players: {
        [slot.waitingUid]: newPlayerState(slot.waitingUsername, false, pair.startEntityId),
        [uid]: newPlayerState(username, false, pair.startEntityId),
      },
      createdAt: FieldValue.serverTimestamp(),
    });
    tx.set(
      slotRef,
      { state: "matched", matchedMatchId: matchRef.id, matchedUids: [slot.waitingUid, uid] },
      { merge: true }
    );
    return { status: "matched", matchId: matchRef.id };
  });
});

/** Deterministic-ish AI move generator (see the root plan's "IA
 * humanizada" section): walks the precomputed `distances` map from
 * race_pairs, occasionally stepping to a neighbor that doesn't reduce
 * distance-to-target (a "mistake"), with human-plausible thinking delays
 * between clicks. Always converges — from any node in `distances` other
 * than the target, at least one neighbor has distance-1 by construction of
 * BFS, so the greedy "closer" step is never unavailable. Runs once, at
 * match-creation time; the resulting schedule (plus the final
 * finishedAtMs it computes) is written straight into the match doc — no
 * process stays alive to "play" it. */
async function buildAiSchedule(pair) {
  const distances = pair.distances || {};
  const maxMistakes = Math.max(0, Math.min(3, Math.floor((pair.optimalHops || 0) / 2)));
  const maxSteps = (pair.optimalHops || 0) * 3 + 6;

  let current = pair.startEntityId;
  let t = 0;
  let mistakes = 0;
  let justMadeMistake = false;
  const schedule = [{ entityId: current, atMs: 0 }];

  for (let step = 0; step < maxSteps && current !== pair.targetEntityId; step++) {
    const entitySnap = await db().collection("entities").doc(current).get();
    const neighborIds = (entitySnap.exists && entitySnap.data().neighbor_ids) || [];
    const currentDist = distances[current];

    const closer = [];
    const notCloser = [];
    for (const neighborId of neighborIds) {
      const d = distances[neighborId];
      if (d === undefined) continue; // outside the precomputed reachable set — never wander there
      if (typeof currentDist === "number" && d === currentDist - 1) closer.push(neighborId);
      else notCloser.push(neighborId);
    }

    const canMistake = step > 0 && typeof currentDist === "number" && currentDist > 1 && mistakes < maxMistakes && notCloser.length > 0;
    const makeMistake = canMistake && Math.random() < 0.15;

    let next;
    if (makeMistake) {
      next = notCloser[Math.floor(Math.random() * notCloser.length)];
      mistakes += 1;
    } else if (closer.length > 0) {
      next = closer[Math.floor(Math.random() * closer.length)];
    } else if (notCloser.length > 0) {
      next = notCloser[Math.floor(Math.random() * notCloser.length)]; // defensive; shouldn't happen — see docstring
    } else {
      break; // isolated node — bail, schedule just ends short
    }

    let delay = gaussianClamped(4500, 1500, 1800, 12000);
    delay += Math.max(0, neighborIds.length - 3) * 150; // more options to read = a bit longer
    if (justMadeMistake) delay += 2500 + Math.random() * 1500; // "wait, that's not right" beat

    t += Math.round(delay);
    schedule.push({ entityId: next, atMs: t });
    justMadeMistake = makeMistake;
    current = next;
  }

  return { schedule, finishedAtMs: current === pair.targetEntityId ? t : null };
}

function gaussianClamped(mean, sd, min, max) {
  let u = 0;
  let v = 0;
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  const value = mean + sd * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  return Math.max(min, Math.min(max, value));
}

exports.createAiMatch = onCall({ timeoutSeconds: 30 }, async (request) => {
  const uid = request.auth?.uid;
  if (!uid) throw new HttpsError("unauthenticated", "Sign in first.");

  const pairId = String(request.data?.pairId || "");
  if (!pairId) throw new HttpsError("invalid-argument", "pairId is required.");

  const username = await requireUsername(uid);
  const pair = await requireActiveRacePair(pairId);
  const slotRef = db().collection("lobby_slots").doc(pairId);

  // Read-modify-write, but the actual claim check happens in the
  // transaction below — this pre-check just avoids generating an AI
  // schedule (several Firestore reads) for the common case where the
  // human already got paired with someone else in the meantime.
  const preSnap = await slotRef.get();
  const preSlot = preSnap.exists ? preSnap.data() : null;
  if (preSlot && preSlot.state === "matched" && (preSlot.matchedUids || []).includes(uid)) {
    return { status: "already_matched", matchId: preSlot.matchedMatchId };
  }

  const { schedule, finishedAtMs } = await buildAiSchedule(pair);
  const aiClicks = Math.max(0, schedule.length - 1);
  const optimalHops = pair.optimalHops || 0;

  const matchesRef = db().collection("matches");

  return db().runTransaction(async (tx) => {
    const slotSnap = await tx.get(slotRef);
    const slot = slotSnap.exists ? slotSnap.data() : null;

    if (!slot || slot.state !== "waiting" || slot.waitingUid !== uid) {
      // A human paired with us in the window between the pre-check above
      // and this transaction — never create a redundant AI match.
      if (slot && slot.state === "matched" && (slot.matchedUids || []).includes(uid)) {
        return { status: "already_matched", matchId: slot.matchedMatchId };
      }
      throw new HttpsError("failed-precondition", "Not currently waiting in this pair's lobby.");
    }

    const matchRef = matchesRef.doc();
    const aiPlayer = newPlayerState("IA", true, pair.startEntityId);
    aiPlayer.clicks = aiClicks;
    aiPlayer.finishedAtMs = finishedAtMs;
    aiPlayer.extraClicks = finishedAtMs !== null ? aiClicks - optimalHops : null;

    tx.set(matchRef, {
      pairId,
      startEntityId: pair.startEntityId,
      targetEntityId: pair.targetEntityId,
      status: "countdown",
      countdownStartAt: FieldValue.serverTimestamp(),
      winnerUid: null,
      aiSchedule: schedule,
      players: {
        [uid]: newPlayerState(username, false, pair.startEntityId),
        [AI_UID]: aiPlayer,
      },
      createdAt: FieldValue.serverTimestamp(),
    });
    tx.set(slotRef, { state: "matched", matchedMatchId: matchRef.id, matchedUids: [uid] }, { merge: true });
    return { status: "matched", matchId: matchRef.id };
  });
});

/** Every move goes through here — never a direct client write to
 * matches/{id} (see firestore.rules / the plan doc's "Decisão central de
 * segurança"). Both the legality check (is `toEntityId` really a neighbor
 * of the caller's current node?) and the caller's own position live only
 * server-side, so a client can't fabricate either. */
exports.submitMove = onCall({}, async (request) => {
  const uid = request.auth?.uid;
  if (!uid) throw new HttpsError("unauthenticated", "Sign in first.");

  const matchId = String(request.data?.matchId || "");
  const toEntityId = String(request.data?.toEntityId || "");
  if (!matchId || !toEntityId) throw new HttpsError("invalid-argument", "matchId and toEntityId are required.");

  const matchRef = db().collection("matches").doc(matchId);

  const result = await db().runTransaction(async (tx) => {
    const matchSnap = await tx.get(matchRef);
    if (!matchSnap.exists) throw new HttpsError("not-found", `matches/${matchId} does not exist.`);
    const match = matchSnap.data();

    const me = match.players?.[uid];
    if (!me) throw new HttpsError("permission-denied", "You are not a player in this match.");
    if (match.status === "finished") throw new HttpsError("failed-precondition", "This match already finished.");
    if (me.finishedAtMs !== null) throw new HttpsError("failed-precondition", "You already finished this race.");

    const countdownStartMs = match.countdownStartAt?.toMillis?.() ?? 0;
    const nowMs = Date.now();
    const elapsedMs = nowMs - countdownStartMs;
    if (elapsedMs < COUNTDOWN_MS) {
      throw new HttpsError("failed-precondition", "The countdown hasn't finished yet.");
    }

    // The legality check: toEntityId must be a real neighbor_ids entry of
    // the *server-recorded* current position — never trust a position sent
    // by the client.
    const currentSnap = await tx.get(db().collection("entities").doc(me.currentEntityId));
    const neighborIds = (currentSnap.exists && currentSnap.data().neighbor_ids) || [];
    if (!neighborIds.includes(toEntityId)) {
      throw new HttpsError("failed-precondition", `${toEntityId} is not a neighbor of your current position.`);
    }

    const clicks = me.clicks + 1;
    const path = [...me.path, { entityId: toEntityId, atMs: elapsedMs }];
    const reachedTarget = toEntityId === match.targetEntityId;

    const updatedMe = {
      ...me,
      currentEntityId: toEntityId,
      clicks,
      path,
      finishedAtMs: reachedTarget ? elapsedMs : null,
      extraClicks: null,
    };

    const updates = {
      status: match.status === "countdown" ? "active" : match.status,
      [`players.${uid}`]: updatedMe,
    };

    let outcome = { ok: true, currentEntityId: toEntityId, clicks, finished: false };

    if (reachedTarget) {
      const pairSnap = await tx.get(db().collection("race_pairs").doc(match.pairId));
      const optimalHops = pairSnap.exists ? pairSnap.data().optimalHops || 0 : 0;
      const extraClicks = Math.max(0, clicks - optimalHops);
      updatedMe.extraClicks = extraClicks;
      updates[`players.${uid}`] = updatedMe;

      const opponentUid = Object.keys(match.players).find((id) => id !== uid);
      const opponent = opponentUid ? match.players[opponentUid] : null;
      const opponentFinishedAtMs = opponent ? opponent.finishedAtMs : null;

      // First to reach the target wins — match.winnerUid is set exactly
      // once (whoever's transaction gets here first while it's still
      // null), so when the *second* human later finishes this same branch
      // correctly leaves them a loser instead of overwriting the winner.
      const won = match.winnerUid == null && (opponentFinishedAtMs === null || elapsedMs < opponentFinishedAtMs);
      if (won) updates.winnerUid = uid;

      // Close the match once neither player can still change the outcome:
      // an AI opponent's result is fully known the instant it's created
      // (buildAiSchedule already ran), and a human opponent is "done" once
      // *their own* submitMove set their finishedAtMs.
      const opponentDone = !opponent || opponent.isAI || opponentFinishedAtMs !== null;
      if (opponentDone) updates.status = "finished";

      outcome = { ok: true, currentEntityId: toEntityId, clicks, finished: true, extraClicks, won };
    }

    tx.update(matchRef, updates);

    return { outcome, statsUpdate: reachedTarget ? { won: outcome.won, extraClicks: outcome.extraClicks } : null };
  });

  if (result.statsUpdate) {
    const { won, extraClicks } = result.statsUpdate;
    const userRef = db().collection("users").doc(uid);
    await db().runTransaction(async (tx) => {
      const snap = await tx.get(userRef);
      const data = snap.exists ? snap.data() : { wins: 0, races: 0, totalExtraClicks: 0 };
      const races = (data.races || 0) + 1;
      const totalExtraClicks = (data.totalExtraClicks || 0) + extraClicks;
      tx.set(
        userRef,
        {
          wins: (data.wins || 0) + (won ? 1 : 0),
          races,
          totalExtraClicks,
          avgExtraClicks: totalExtraClicks / races,
          updatedAt: FieldValue.serverTimestamp(),
        },
        { merge: true }
      );
    });
  }

  return result.outcome;
});

/** Nothing in the request path ever deletes a `lobby_slots` or `matches`
 * doc — a slot can get stuck in "waiting" if the waiting player closes the
 * tab before the 5s AI-fallback timer fires (WaitingRoom.jsx's cleanup
 * cancels that timer on unmount, by design — see its comments), and
 * finished matches just accumulate forever otherwise. Needs the composite
 * indexes declared in firestore.indexes.json (lobby_slots: state+joinedAt,
 * matches: status+createdAt). */
exports.cleanupRaceMode = onSchedule("every 24 hours", async () => {
  const staleLobbyCutoff = new Date(Date.now() - 10 * 60 * 1000); // 10 min
  const staleMatchCutoff = new Date(Date.now() - 24 * 60 * 60 * 1000); // 24h

  const [staleLobbies, staleMatches] = await Promise.all([
    db().collection("lobby_slots").where("state", "==", "waiting").where("joinedAt", "<", staleLobbyCutoff).get(),
    db().collection("matches").where("status", "==", "finished").where("createdAt", "<", staleMatchCutoff).get(),
  ]);

  const batch = db().batch();
  for (const doc of staleLobbies.docs) batch.delete(doc.ref);
  for (const doc of staleMatches.docs) batch.delete(doc.ref);
  if (staleLobbies.size + staleMatches.size > 0) await batch.commit();

  console.log(
    `cleanupRaceMode: removed ${staleLobbies.size} stale lobby slot(s), ${staleMatches.size} old finished match(es).`
  );
});
