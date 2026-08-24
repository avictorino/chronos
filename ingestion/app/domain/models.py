"""Persistent domain models — stable, used across the whole app (not just one prompt).

Ephemeral LLM input/output contracts live in schemas.py instead and get mapped
into these classes only after validation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator, Field, Tag, model_validator

from app.domain.enums import DatePrecision, EntityType, EventType, RelationshipType


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HistoricalDate(BaseModel):
    """Ancient dates carry uncertainty — never just a bare `year: int`.

    Negative years are BCE (701 BCE = -701, 70 CE = 70).
    """

    earliest_year: int | None = None
    latest_year: int | None = None
    estimated_year: int | None = None
    precision: DatePrecision
    confidence: float | None = None

    @model_validator(mode="after")
    def _normalize_range(self) -> "HistoricalDate":
        # Self-healing, not rejecting: LLMs reliably get earliest/latest
        # backwards for BCE ranges (more negative = earlier is unintuitive),
        # and self-correction retry doesn't fix it reliably either — swapping
        # preserves the intended range instead of burning a retry / erroring
        # the whole item out over an ordering slip.
        if self.earliest_year is not None and self.latest_year is not None:
            if self.earliest_year > self.latest_year:
                self.earliest_year, self.latest_year = self.latest_year, self.earliest_year
        return self


# --- HistoricalEntity: base + 6 concrete subclasses ------------------------
#
# A single generic entity with every field optional would lose type safety;
# one subclass per EntityType value (23 of them) would be over-engineering,
# since e.g. KINGDOM/EMPIRE/DYNASTY have no structural differences between
# each other. These 6 subclasses cover all the real structural variation.
# See spec/02-domain-model-spec.md.


class HistoricalEntity(BaseModel):
    id: str
    entity_type: EntityType
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    summary: str | None = None

    origin: str = "llm_generated"
    verification_status: str = "unverified"
    generated_by_model: str | None = None
    confidence: float | None = None

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    ingestion_run_id: str | None = None
    # Which civilization ingestion run(s) touched this document — an entity
    # can legitimately be created/enriched by more than one civilization's
    # run (cross-civilization dedup, see app/services/entity_resolution.py).
    # Repositories merge this via Firestore ArrayUnion rather than
    # overwriting (see app/persistence/repositories.py). Lets
    # app/services/civilization_reset.py safely delete "civilization X's
    # data" without touching documents another civilization still needs.
    source_civilizations: list[str] = Field(default_factory=list)


class Civilization(HistoricalEntity):
    entity_type: Literal[EntityType.CIVILIZATION] = EntityType.CIVILIZATION
    start_year: int | None = None
    end_year: int | None = None


class Person(HistoricalEntity):
    entity_type: Literal[EntityType.PERSON] = EntityType.PERSON
    birth_date: HistoricalDate | None = None
    death_date: HistoricalDate | None = None
    titles: list[str] = Field(default_factory=list)


class Place(HistoricalEntity):
    entity_type: Literal[EntityType.PLACE, EntityType.CITY, EntityType.REGION] = EntityType.PLACE
    latitude: float | None = None
    longitude: float | None = None
    modern_country: str | None = None
    ancient_region: str | None = None
    # "llm_generated" when the LLM guessed lat/long — flagged for future validation.
    coordinate_origin: str | None = None


class Polity(HistoricalEntity):
    entity_type: Literal[
        EntityType.POLITY, EntityType.EMPIRE, EntityType.KINGDOM, EntityType.DYNASTY
    ] = EntityType.POLITY
    start_year: int | None = None
    end_year: int | None = None


class Document(HistoricalEntity):
    entity_type: Literal[EntityType.DOCUMENT, EntityType.TEXT, EntityType.INSCRIPTION] = (
        EntityType.DOCUMENT
    )


class Concept(HistoricalEntity):
    entity_type: Literal[
        EntityType.RELIGION,
        EntityType.DEITY,
        EntityType.CULTURE,
        EntityType.LANGUAGE,
        EntityType.CONCEPT,
    ] = EntityType.CONCEPT


# Polity maps 4 EntityType values onto 1 class (many-to-one), so the plain
# field-discriminator (which assumes a 1:1 tag<->type mapping) doesn't fit —
# we use a callable Discriminator instead.
_ENTITY_TYPE_TO_TAG: dict[EntityType, str] = {
    EntityType.CIVILIZATION: "civilization",
    EntityType.PERSON: "person",
    EntityType.PLACE: "place",
    EntityType.CITY: "place",
    EntityType.REGION: "place",
    EntityType.POLITY: "polity",
    EntityType.EMPIRE: "polity",
    EntityType.KINGDOM: "polity",
    EntityType.DYNASTY: "polity",
    EntityType.DOCUMENT: "document",
    EntityType.TEXT: "document",
    EntityType.INSCRIPTION: "document",
    EntityType.RELIGION: "concept",
    EntityType.DEITY: "concept",
    EntityType.CULTURE: "concept",
    EntityType.LANGUAGE: "concept",
    EntityType.CONCEPT: "concept",
}


def entity_type_discriminator(value: object) -> str:
    if isinstance(value, dict):
        raw = value.get("entity_type")
    else:
        raw = getattr(value, "entity_type", None)
    entity_type = raw if isinstance(raw, EntityType) else EntityType(raw)
    return _ENTITY_TYPE_TO_TAG[entity_type]


AnyEntity = Annotated[
    (
        Annotated[Civilization, Tag("civilization")]
        | Annotated[Person, Tag("person")]
        | Annotated[Place, Tag("place")]
        | Annotated[Polity, Tag("polity")]
        | Annotated[Document, Tag("document")]
        | Annotated[Concept, Tag("concept")]
    ),
    Discriminator(entity_type_discriminator),
]


class HistoricalEvent(BaseModel):
    id: str
    name: str
    event_type: EventType
    description: str
    date: HistoricalDate

    people: list[str] = Field(default_factory=list)
    places: list[str] = Field(default_factory=list)
    polities: list[str] = Field(default_factory=list)

    causes: list[str] = Field(default_factory=list)
    consequences: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)

    confidence: float

    origin: str = "llm_generated"
    verification_status: str = "unverified"
    generated_by_model: str | None = None

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    ingestion_run_id: str | None = None
    source_civilizations: list[str] = Field(default_factory=list)


class HistoricalRelationship(BaseModel):
    id: str
    source_entity_id: str
    target_entity_id: str
    relationship_type: RelationshipType
    description: str | None = None

    start_year: int | None = None
    end_year: int | None = None

    confidence: float
    origin: str = "llm_generated"
    verification_status: str = "unverified"
    generated_by_model: str | None = None

    created_at: datetime = Field(default_factory=utcnow)
    ingestion_run_id: str | None = None
    source_civilizations: list[str] = Field(default_factory=list)


class HistoricalClaim(BaseModel):
    """A *claim*, never a "fact" — see spec/01-product-spec.md glossary."""

    id: str
    subject_id: str | None
    predicate: str
    object_id: str | None
    statement: str
    estimated_date: HistoricalDate | None = None
    confidence: float

    origin: str = "llm_generated"
    verification_status: str = "unverified"
    generated_by_model: str

    created_at: datetime = Field(default_factory=utcnow)
    ingestion_run_id: str | None = None
    source_civilizations: list[str] = Field(default_factory=list)


class KnowledgeChunk(BaseModel):
    id: str
    entity_ids: list[str]
    text: str
    chunk_type: str
    embedding: list[float] | None = None

    origin: str = "llm_generated"
    generated_by_model: str

    created_at: datetime = Field(default_factory=utcnow)
    ingestion_run_id: str | None = None
    source_civilizations: list[str] = Field(default_factory=list)


class IngestionError(BaseModel):
    node: str
    item: str
    message: str
    occurred_at: datetime = Field(default_factory=utcnow)


class IngestionRun(BaseModel):
    id: str
    civilization_id: str
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    status: str = "running"
    model: str | None = None
    entities_created: int = 0
    entities_updated: int = 0
    errors: list[IngestionError] = Field(default_factory=list)


class EntityResolutionResult(BaseModel):
    action: Literal["create", "merge", "review"]
    existing_entity_id: str | None = None
    confidence: float = 0.0
    reason: str = ""
