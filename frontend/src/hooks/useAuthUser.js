import { useEffect, useState } from "react";
import { onAuthStateChanged, signInAnonymously } from "firebase/auth";
import { auth } from "../lib/firebase";

/** Race mode's identity: a stable per-browser anonymous uid, no login UI
 * (see the root README's "Decisão central de segurança" — everything that
 * writes as this uid goes through callable Cloud Functions, never a direct
 * Firestore write). Firebase Auth persists the anonymous session in
 * IndexedDB by default, so the same uid comes back across reloads/tabs on
 * this browser — that's the whole "identity", nothing else to manage here.
 *
 * Returns `{ uid, loading, error }`. `uid` stays null until sign-in
 * resolves; callers that need a uid (joining a race, claiming a username)
 * should wait for `loading === false && uid` before calling anything in
 * src/lib/race.js. */
export default function useAuthUser() {
  const [state, setState] = useState({ uid: auth.currentUser?.uid ?? null, loading: true, error: null });

  useEffect(() => {
    let cancelled = false;

    const unsubscribe = onAuthStateChanged(auth, (user) => {
      if (cancelled) return;
      if (user) {
        setState({ uid: user.uid, loading: false, error: null });
        return;
      }
      // No session yet (first visit, or storage was cleared) — create one.
      // onAuthStateChanged fires again once this resolves, with a user.
      signInAnonymously(auth).catch((err) => {
        if (!cancelled) setState({ uid: null, loading: false, error: err });
      });
    });

    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);

  return state;
}
