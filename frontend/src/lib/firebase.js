// Firebase app initialization for the Chronos frontend.
//
// This is the public web config for the `chronos-29b82` project (safe to
// ship in client-side code — it identifies the project, it isn't a secret;
// the real access control lives in Firestore's security rules, not here).
//
// Firestore holds a read-only mirror of the knowledge graph exported from
// Postgres by `ingestion/app/export/firestore_export.py` — this app reads it
// directly (graph navigation + vector similarity search), no backend server
// in between. See the root README and the ingestion export module for the
// full design.

import { initializeApp } from "firebase/app";
import { getAnalytics, isSupported as isAnalyticsSupported } from "firebase/analytics";
import { getFirestore } from "firebase/firestore";

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

// Analytics only works in a browser (no-op under SSR/build) and isn't
// supported in every environment — guard it instead of calling
// getAnalytics(app) unconditionally at import time.
export const analyticsReady = typeof window !== "undefined" ? isAnalyticsSupported().then((ok) => (ok ? getAnalytics(app) : null)) : Promise.resolve(null);
