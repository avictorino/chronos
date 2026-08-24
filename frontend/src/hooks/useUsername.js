import { useEffect, useState } from "react";
import { getCachedUsername, getUser } from "../lib/race";

/** Resolves whether `uid` already has a username — checks the fast local
 * cache first, falls back to the server (users/{uid}, the source of
 * truth) so clearing localStorage without clearing the Auth session just
 * costs one extra read instead of forcing a re-prompt. `status` is
 * "loading" | "known" | "unknown" (needs UsernamePrompt.jsx). */
export default function useUsername(uid) {
  const [state, setState] = useState({ status: "loading", username: null });

  useEffect(() => {
    if (!uid) return;
    let cancelled = false;

    const cached = getCachedUsername();
    if (cached) {
      setState({ status: "known", username: cached });
      return;
    }

    getUser(uid)
      .then((user) => {
        if (cancelled) return;
        setState(user?.username ? { status: "known", username: user.username } : { status: "unknown", username: null });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "unknown", username: null });
      });

    return () => {
      cancelled = true;
    };
  }, [uid]);

  function setUsername(username) {
    setState({ status: "known", username });
  }

  return { ...state, setUsername };
}
