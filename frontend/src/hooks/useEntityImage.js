import { useEffect, useState } from "react";
import { requestEntityImage } from "../lib/functions";

/** Resolves one entity's portrait.
 *
 * If the entity doc already carries `image_url` (a previous generation,
 * read straight from Firestore like everything else), that's used
 * directly — no network call at all. Otherwise this asks the
 * `generateEntityImage` Cloud Function to generate + cache one.
 *
 * The `cancelled` flag (same pattern as useEntityDetail.js) makes a
 * request whose entity changed before it resolved a no-op — including
 * React StrictMode's dev-only double-invoke, where the first of the two
 * effect runs gets cancelled and only the second one's result is applied.
 * A real double-generate is still prevented server-side either way: the
 * Cloud Function claims the entity with a Firestore transaction before
 * calling OpenAI (see functions/index.js).
 *
 * status: "idle" | "loading" | "ready" | "unavailable" | "error"
 * "unavailable" covers ineligible types, an in-flight generation from
 * another visitor, or the daily budget cap — all non-error, non-image
 * outcomes the caller should just render the plain placeholder for. */
export default function useEntityImage(entity) {
  const [state, setState] = useState({ status: "idle", url: null });

  useEffect(() => {
    if (!entity?.id) {
      setState({ status: "idle", url: null });
      return;
    }

    if (entity.image_url) {
      setState({ status: "ready", url: entity.image_url });
      return;
    }

    let cancelled = false;
    setState({ status: "loading", url: null });

    requestEntityImage(entity.id)
      .then((result) => {
        if (cancelled) return;
        if (result?.url) {
          setState({ status: "ready", url: result.url });
        } else {
          setState({ status: "unavailable", url: null });
        }
      })
      .catch((err) => {
        console.error(`[useEntityImage] generateEntityImage(${entity.id}) failed:`, err);
        if (!cancelled) setState({ status: "error", url: null });
      });

    return () => {
      cancelled = true;
    };
  }, [entity?.id, entity?.image_url]);

  return state;
}
