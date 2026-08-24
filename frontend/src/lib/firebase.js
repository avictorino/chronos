// Firebase app initialization for the Chronos frontend.
//
// This is the public web config for the `chronos-29b82` project (safe to
// ship in client-side code — it identifies the project, it isn't a secret;
// the real access control lives in Firestore's security rules, not here).
//
// Firestore holds the knowledge graph written directly by the ingestion
// pipeline (`ingestion/app/persistence/repositories.py`) — this app reads it
// directly (graph navigation + vector similarity search), no backend server
// in between. See the root README and `ingestion/README.md` for the full
// design.

import { initializeApp } from "firebase/app";
import { getAnalytics, isSupported as isAnalyticsSupported } from "firebase/analytics";
import { connectFirestoreEmulator, getFirestore } from "firebase/firestore";
import { connectFunctionsEmulator, getFunctions } from "firebase/functions";
import { connectAuthEmulator, getAuth } from "firebase/auth";

const firebaseConfig = {
  apiKey: "AIzaSyBf6NlV4P7whWepKW0BOJKDelpGLa1zEPA",
  authDomain: "chronos-29b82.firebaseapp.com",
  projectId: "chronos-29b82",
  storageBucket: "chronos-29b82.firebasestorage.app",
  messagingSenderId: "704029639944",
  appId: "1:704029639944:web:5a955110103d9dd6d558bd",
  measurementId: "G-86GR16CH5C",
};

export const app = initializeApp(firebaseConfig);

// Used for every read described in the root README / ingestion export docs:
// entities/events/relationships/claims/chunks collections, neighbor_ids-based
// graph traversal, and `find_nearest` vector similarity search on chunks.
export const db = getFirestore(app);

// Used for the on-demand entity-portrait generator (see
// src/lib/functions.js and functions/index.js) and the race-mode callables
// (see src/lib/race.js and functions/index.js) — the only write paths in
// this app, and they never run on the client: they're callable Cloud
// Functions, secrets/admin access live server-side only.
export const functions = getFunctions(app);

// Anonymous identity for race mode (see src/hooks/useAuthUser.js) — no
// login UI, just a stable per-browser uid used to own a `users/{uid}` doc
// and to authorize `submitMove`/etc. calls server-side.
export const auth = getAuth(app);

// Opt-in (VITE_USE_EMULATORS=true), not automatic on every `npm run dev`:
// the existing app is read-only against the real chronos-29b82 project and
// that keeps working with zero setup. Race mode is the first feature with
// real writes exposed to strangers on the internet, so *while building it*
// point at the local Firebase Emulator Suite instead — run
// `firebase emulators:start` from this directory, then
// `VITE_USE_EMULATORS=true npm run dev` — rather than exercising matchmaking
// races against production.
if (import.meta.env.DEV && import.meta.env.VITE_USE_EMULATORS === "true") {
  connectFirestoreEmulator(db, "127.0.0.1", 8080);
  connectFunctionsEmulator(functions, "127.0.0.1", 5001);
  connectAuthEmulator(auth, "http://127.0.0.1:9099", { disableWarnings: true });
}

// Analytics only works in a browser (no-op under SSR/build) and isn't
// supported in every environment — guard it instead of calling
// getAnalytics(app) unconditionally at import time.
export const analyticsReady = typeof window !== "undefined" ? isAnalyticsSupported().then((ok) => (ok ? getAnalytics(app) : null)) : Promise.resolve(null);
