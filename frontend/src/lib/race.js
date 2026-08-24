// Client-side surface for race mode — mirrors the split in lib/functions.js
// (write path) and lib/firestore.js (read path). Every write goes through a
// callable Cloud Function (functions/index.js); reads/subscriptions talk to
// Firestore directly, same as the rest of the app.

import { httpsCallable } from "firebase/functions";
import { collection, doc, getDoc, getDocs, limit as fsLimit, onSnapshot, orderBy, query } from "firebase/firestore";
import { db, functions } from "./firebase";

// Must match COUNTDOWN_MS in functions/index.js — both sides derive
// raceStartAt from the same countdownStartAt without either one owning a
// live clock.
export const COUNTDOWN_MS = 3000;

const USERNAME_STORAGE_KEY = "chronos_race_username";

/** Cached so the username prompt only ever shows once per browser (the
 * server-side users/{uid} doc is the source of truth; this is purely a
 * "don't ask again" convenience, safe to lose). */
export function getCachedUsername() {
  try {
    return localStorage.getItem(USERNAME_STORAGE_KEY);
  } catch {
    return null; // localStorage unavailable (private mode, etc.) — just re-prompt
  }
}

function setCachedUsername(username) {
  try {
    localStorage.setItem(USERNAME_STORAGE_KEY, username);
  } catch {
    // non-fatal — see getCachedUsername
  }
}

const _claimUsername = httpsCallable(functions, "claimUsername");
const _joinLobby = httpsCallable(functions, "joinLobby");
const _createAiMatch = httpsCallable(functions, "createAiMatch");
const _submitMove = httpsCallable(functions, "submitMove");

/** Sets/renames the caller's username, creating users/{uid} on first call.
 * Returns { uid, username }. */
export async function claimUsername(username) {
  const { data } = await _claimUsername({ username });
  setCachedUsername(data.username);
  return data;
}

/** Joins (or creates) the wait for `pairId`. Returns
 * { status: "waiting" } | { status: "matched", matchId }. */
export async function joinLobby(pairId) {
  const { data } = await _joinLobby({ pairId });
  return data;
}

/** Called after ~5s of waiting with no human opponent. No-ops into
 * { status: "already_matched", matchId } if a human paired in the
 * meantime instead. */
export async function createAiMatch(pairId) {
  const { data } = await _createAiMatch({ pairId });
  return data;
}

/** Attempts to move to `toEntityId`. Throws (HttpsError) if it isn't a
 * real neighbor of the caller's current position, the match isn't active,
 * or the caller isn't a player in it. */
export async function submitMove(matchId, toEntityId) {
  const { data } = await _submitMove({ matchId, toEntityId });
  return data;
}

/** Reads users/{uid} directly — the source of truth for "does this player
 * already have a username", since localStorage (getCachedUsername) can be
 * cleared independently of the Firebase Auth session. */
export async function getUser(uid) {
  const snap = await getDoc(doc(db, "users", uid));
  return snap.exists() ? { id: snap.id, ...snap.data() } : null;
}

/** All active curated pairs, for the picker screen. */
export async function listRacePairs() {
  const snap = await getDocs(query(collection(db, "race_pairs"), fsLimit(50)));
  return snap.docs.map((d) => ({ id: d.id, ...d.data() })).filter((p) => p.active !== false);
}

/** One curated pair's full doc (includes the precomputed `distances` map
 * the HUD looks up from — see the root plan doc). Fetched once per race,
 * not subscribed. */
export async function getRacePair(pairId) {
  const snap = await getDoc(doc(db, "race_pairs", pairId));
  return snap.exists() ? { id: snap.id, ...snap.data() } : null;
}

/** Live updates to the shared wait-slot for a pair — used only by the
 * player who's still waiting, to learn matchId once a second player (human
 * or, after the 5s timeout, an AI) joins. */
export function subscribeToLobbySlot(pairId, callback) {
  return onSnapshot(doc(db, "lobby_slots", pairId), (snap) => {
    callback(snap.exists() ? { id: snap.id, ...snap.data() } : null);
  });
}

/** Live updates to a match doc — countdown/active/finished state, both
 * players' positions and click counts, and (if applicable) the AI's
 * precomputed move schedule. */
export function subscribeToMatch(matchId, callback) {
  return onSnapshot(doc(db, "matches", matchId), (snap) => {
    callback(snap.exists() ? { id: snap.id, ...snap.data() } : null);
  });
}

/** The AI opponent's current node, derived purely from the clock — see the
 * plan's "IA humanizada" section. `match.players.ai.currentEntityId` is
 * NOT live (nothing ticks it after match creation); this is what the HUD
 * should read instead for an AI opponent's visual position. Returns null
 * if `match` has no aiSchedule (i.e. the opponent is human). */
export function getAiCurrentEntityId(match) {
  const schedule = match?.aiSchedule;
  const startMs = match?.countdownStartAt?.toMillis?.();
  if (!schedule?.length || !startMs) return null;

  const raceStartAt = startMs + COUNTDOWN_MS;
  const elapsedMs = Date.now() - raceStartAt;

  let current = schedule[0].entityId;
  for (const step of schedule) {
    if (step.atMs > elapsedMs) break;
    current = step.entityId;
  }
  return current;
}

/** Top players by wins, ties broken by fewest average extra clicks (see
 * users/{uid}.avgExtraClicks, maintained server-side by submitMove). */
export async function listLeaderboard(limitTo = 50) {
  const snap = await getDocs(query(collection(db, "users"), orderBy("wins", "desc"), fsLimit(limitTo)));
  return snap.docs.map((d) => ({ id: d.id, ...d.data() }));
}
