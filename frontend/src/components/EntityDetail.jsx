import React, { useState } from "react";
import { IconWarning } from "./icons";
import { colorVarForType, formatYearRange } from "../lib/entityStyle";
import useEntityImage from "../hooks/useEntityImage";
import AncientLoader from "./AncientLoader";

/** Copies the current permalink (App.jsx keeps `?entity=<id>` in the URL
 * bar in sync with the selection) so this entity is shareable as-is. */
function CopyLinkButton() {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch (err) {
      console.error("[CopyLinkButton] clipboard write failed:", err);
    }
  }

  return (
    <button type="button" className="copy-link-btn" onClick={handleCopy}>
      {copied ? "Link copiado!" : "Copiar link"}
    </button>
  );
}

/** The portrait slot at the top of the profile card: the cached image once
 * generateEntityImage() has one, the chiseling animation while it's being
 * generated, or the same colored-dot placeholder EntityDetail always used
 * for entity types that don't get a generated portrait. */
function Portrait({ entity }) {
  const { status, url } = useEntityImage(entity);

  return (
    <div className="portrait">
      {status === "ready" && url ? (
        <img src={url} alt={entity.canonical_name} loading="lazy" />
      ) : status === "loading" ? (
        <AncientLoader />
      ) : (
        <div className="portrait-placeholder">
          <span className="dot" style={{ background: `var(${colorVarForType(entity.entity_type)})` }} />
        </div>
      )}
    </div>
  );
}

function roleFor(entity) {
  if (entity.entity_type === "PERSON") return entity.titles?.[0] ?? "Person";
  const range = formatYearRange(entity.start_year, entity.end_year);
  return [entity.entity_type?.toLowerCase(), range].filter(Boolean).join(" · ");
}

export default function EntityDetail({ entityId, status, entity, neighbors, claims, onSelectEntity }) {
  if (!entityId) {
    return (
      <aside className="detail">
        <div className="empty-note">
          Pick an entity from the timeline, or search above, to see its profile,
          confidence score, and connections here.
        </div>
      </aside>
    );
  }

  if (status === "loading" || status === "idle") {
    return (
      <aside className="detail">
        <div className="empty-note">Loading…</div>
      </aside>
    );
  }

  if (status === "not-found") {
    return (
      <aside className="detail">
        <div className="empty-note">
          This entity id isn't in Firestore yet. Run{" "}
          <code>python -m app.main export-firestore</code> after ingestion to refresh
          the mirror.
        </div>
      </aside>
    );
  }

  if (status === "error" || !entity) {
    return (
      <aside className="detail">
        <div className="empty-note">
          Couldn't reach Firestore. Check the Firebase config in{" "}
          <code>src/lib/firebase.js</code> and the security rules.
        </div>
      </aside>
    );
  }

  const confidencePct = entity.confidence != null ? Math.round(entity.confidence * 100) : null;

  return (
    <aside className="detail">
      <Portrait entity={entity} />
      <div className="entity-name-row">
        <h1 className="entity-name">{entity.canonical_name}</h1>
        <CopyLinkButton />
      </div>
      <div className="entity-role">{roleFor(entity)}</div>
      {entity.aliases?.length > 0 && (
        <div className="entity-dates">aka {entity.aliases.join(", ")}</div>
      )}

      <div className="verify-row">
        {entity.verification_status !== "verified" && (
          <div className="badge-unverified">
            <IconWarning />
            {entity.verification_status === "unverified"
              ? "Unverified · AI-generated"
              : entity.verification_status}
          </div>
        )}
        {confidencePct != null && (
          <div className="conf-row">
            <span className="conf-label">Confidence</span>
            <div className="conf-track">
              <div
                className="conf-fill"
                style={{ width: `${confidencePct}%`, background: "var(--conf-high)" }}
              />
            </div>
            <span className="conf-val">{entity.confidence.toFixed(2)}</span>
          </div>
        )}
      </div>

      {entity.summary && <p className="summary">{entity.summary}</p>}

      {claims?.length > 0 && (
        <>
          <div className="section-title">Claims ({claims.length})</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {claims.slice(0, 4).map((c) => (
              <div key={c.id} className="summary" style={{ marginTop: 0 }}>
                {c.statement}
              </div>
            ))}
          </div>
        </>
      )}

      {neighbors?.length > 0 && (
        <>
          <div className="section-title">Connections ({neighbors.length})</div>
          <div className="rel-list">
            {neighbors.map(({ relationship, entity: neighbor }) => (
              <div key={relationship.id} className="rel-item" onClick={() => onSelectEntity(neighbor.id)}>
                <span
                  className="rel-dot"
                  style={{ background: `var(${colorVarForType(neighbor.entity_type)})` }}
                />
                <div className="rel-body">
                  <div className="rel-name">{neighbor.canonical_name}</div>
                  <div className="rel-type">{relationship.relationship_type}</div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </aside>
  );
}
