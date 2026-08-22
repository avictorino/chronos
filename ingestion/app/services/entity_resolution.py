"""Entity resolution V1: canonicalization -> exact match -> fuzzy match ->
embedding similarity -> optional LLM tiebreaker. See spec/02-domain-model-spec.md.

Deliberately simple: not implementing anything more elaborate than this for V1.
`resolve_entity` always compares against candidates already fetched from
Postgres (via EntityRepository/EventRepository.find_candidates) — resolving only
against the current run's in-memory state would silently break cross-
civilization dedup (e.g. Judah/Babylon mentioned by Assyria in a later run).
"""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz

from app.domain.models import EntityResolutionResult
from app.domain.schemas import EntitySameAs
from app.llm import EmbeddingClient, LLMClient, build_entity_same_as_prompt
from app.utils.logging import get_logger

log = get_logger("entity_resolution")

_HONORIFICS = ("the great", "the elder", "the younger", "the wise")

_FUZZY_MERGE_THRESHOLD = 0.90
_FUZZY_BORDERLINE_THRESHOLD = 0.75
_EMBEDDING_MERGE_THRESHOLD = 0.85
_EMBEDDING_REVIEW_THRESHOLD = 0.70


def canonicalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().strip()
    normalized = re.sub(r"[^\w\s]", "", normalized)
    for honorific in _HONORIFICS:
        normalized = normalized.replace(honorific, "")
    return re.sub(r"\s+", " ", normalized).strip()


def _name_pool(name: str, aliases: list[str]) -> list[str]:
    return [canonicalize(n) for n in [name, *aliases] if n]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def resolve_entity(
    candidate_name: str,
    candidate_aliases: list[str],
    existing: list[dict],
    embedding_client: EmbeddingClient | None = None,
    llm_client: LLMClient | None = None,
    use_llm_tiebreaker: bool = False,
    require_embedding_confirmation: bool = False,
) -> EntityResolutionResult:
    """`require_embedding_confirmation=True` (used for events, see
    event_service.py) skips the instant fuzzy-score merge (step 4) entirely —
    real bug found in manual validation: `rapidfuzz.fuzz.WRatio` reliably
    scores >=0.90 between *different* event names/aliases that just share a
    lot of vocabulary ("Conquest of Sumerian City-States" vs "Conquest by
    Sargon of Akkad" vs "Fall to Gutian Invasion" all collapsed into one row).
    Event titles are full descriptive phrases, not proper names, so lexical
    overlap is a much weaker same-thing signal than it is for people/places —
    any fuzzy hit still needs embedding-level (semantic) confirmation."""
    candidate_pool = _name_pool(candidate_name, candidate_aliases)
    candidate_canonical = candidate_pool[0] if candidate_pool else ""

    # 1-3: canonicalization + exact match (over name AND every alias, both sides)
    best_score = 0.0
    best_match: dict | None = None
    for entity in existing:
        existing_pool = _name_pool(entity["canonical_name"], entity.get("aliases") or [])
        existing_canonical = existing_pool[0] if existing_pool else ""
        for c in candidate_pool:
            for e in existing_pool:
                if c and c == e:
                    if c == candidate_canonical or e == existing_canonical:
                        # At least one side of the match is that side's own
                        # canonical name, not merely one of its aliases —
                        # trustworthy enough to merge immediately.
                        return EntityResolutionResult(
                            action="merge",
                            existing_entity_id=entity["id"],
                            confidence=1.0,
                            reason=f"exact match on canonicalized name '{c}'",
                        )
                    # Alias-to-alias-only exact match: LLM-generated aliases
                    # (especially for events) can coincidentally overlap
                    # between genuinely different things — treat as a strong
                    # signal that still needs embedding verification, not an
                    # automatic merge (see spec/06, "false event merge").
                    score = max(0.80, fuzz.WRatio(c, e) / 100)
                else:
                    score = fuzz.WRatio(c, e) / 100
                if score > best_score:
                    best_score, best_match = score, entity

    # 4: fuzzy match (skipped for events — see require_embedding_confirmation above)
    if not require_embedding_confirmation and best_match is not None and best_score >= _FUZZY_MERGE_THRESHOLD:
        return EntityResolutionResult(
            action="merge",
            existing_entity_id=best_match["id"],
            confidence=best_score,
            reason=f"fuzzy match score={best_score:.2f}",
        )

    # 5-6: embedding similarity (+ optional LLM tiebreaker), only for the
    # borderline band — keeps V1 cheap (few candidates ever reach this).
    if best_match is not None and best_score >= _FUZZY_BORDERLINE_THRESHOLD:
        if embedding_client is not None:
            candidate_text = f"{candidate_name} {' '.join(candidate_aliases)}".strip()
            existing_text = (
                f"{best_match['canonical_name']} {' '.join(best_match.get('aliases') or [])}".strip()
            )
            cand_vec, exist_vec = await embedding_client.embed([candidate_text, existing_text])
            similarity = _cosine_similarity(cand_vec, exist_vec)

            if similarity >= _EMBEDDING_MERGE_THRESHOLD:
                return EntityResolutionResult(
                    action="merge",
                    existing_entity_id=best_match["id"],
                    confidence=similarity,
                    reason=f"embedding similarity={similarity:.2f}",
                )

            if similarity >= _EMBEDDING_REVIEW_THRESHOLD:
                if use_llm_tiebreaker and llm_client is not None:
                    prompt = build_entity_same_as_prompt(
                        candidate_name, best_match["canonical_name"], best_match.get("summary") or ""
                    )
                    verdict = await llm_client.generate_structured(prompt, EntitySameAs)
                    if verdict.same and verdict.confidence >= 0.7:
                        return EntityResolutionResult(
                            action="merge",
                            existing_entity_id=best_match["id"],
                            confidence=verdict.confidence,
                            reason=f"LLM tiebreaker: {verdict.reasoning}",
                        )
                return EntityResolutionResult(
                    action="review",
                    existing_entity_id=best_match["id"],
                    confidence=similarity,
                    reason="borderline embedding similarity, needs human review",
                )

    return EntityResolutionResult(action="create", confidence=0.0, reason="no sufficiently similar existing entity")
