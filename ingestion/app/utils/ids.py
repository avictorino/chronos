"""Stable, deterministic IDs — never use a raw name as an id.

slug + uuid5 means the same logical entity always produces the same id, which
is what makes `MERGE`-based persistence idempotent (see spec/02-domain-model-spec.md).
"""

from __future__ import annotations

import re
import unicodedata
import uuid

from app.domain.enums import EntityType, EventType

NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "chronos.ingestion")


def slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().strip()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    return normalized.strip("-")


def stable_entity_id(entity_type: EntityType, canonical_name: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{entity_type.value}:{slugify(canonical_name)}"))


def stable_event_id(event_type: EventType, canonical_name: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"EVENT:{event_type.value}:{slugify(canonical_name)}"))


def stable_relationship_id(source_id: str, relationship_type: str, target_id: str) -> str:
    # Deliberately order-sensitive (not commutative): source->KING_OF->target is
    # a different relationship id from target->KING_OF->source.
    return str(uuid.uuid5(NAMESPACE, f"{source_id}:{relationship_type}:{target_id}"))


def stable_claim_id(
    subject_id: str | None, predicate: str, object_id: str | None, statement: str
) -> str:
    # Includes the full statement text (not just the subject/predicate/object
    # triple) so distinct/conflicting claims about the same pair don't collapse
    # into one id. Trade-off: a rerun where the LLM rephrases the same claim can
    # accumulate near-duplicates — see spec/06-acceptance-tests-spec.md.
    return str(uuid.uuid5(NAMESPACE, f"{subject_id}:{predicate}:{object_id}:{statement}"))


def stable_chunk_id(entity_ids: list[str], chunk_type: str, text: str) -> str:
    key = ",".join(sorted(entity_ids)) + f":{chunk_type}:{text}"
    return str(uuid.uuid5(NAMESPACE, key))


def new_run_id() -> str:
    return str(uuid.uuid4())
