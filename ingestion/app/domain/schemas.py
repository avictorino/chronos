"""Ephemeral LLM input/output contracts.

These are never persisted directly — nodes map them into domain/models.py
classes after Pydantic validation. Every list-shaped contract is wrapped in an
object (`class XList(BaseModel): items: list[X]`) because Ollama/OpenAI
structured output require an object schema at the top level, never a bare list.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.domain.enums import DatePrecision, EntityType, EventType, RelationshipType
from app.domain.models import HistoricalDate


class CivilizationSeed(BaseModel):
    id: str
    name: str
    approximate_start_year: int | None = None
    approximate_end_year: int | None = None
    # 0-10 subjective importance/prominence score, used to scale how much of
    # this civilization gets ingested (see
    # app/services/civilization_service.py::scaled_budgets) — 10 = full
    # MAX_*_PER_CIVILIZATION budgets (e.g. Rome, Greece, Egypt), 0 = the
    # smallest budget floor. Defaults to 5 (mid-scale) for any civilization
    # that doesn't set one explicitly in data/civilizations.yaml.
    importance_score: int = Field(default=5, ge=0, le=10)


class PeriodSummary(BaseModel):
    name: str
    description: str
    start_year: int | None = None
    end_year: int | None = None


_YEAR_FIELD_DESCRIPTION = (
    "Astronomical year numbering: negative = BCE (e.g. -2334 for 2334 BCE), "
    "positive = CE. Always give your own best estimate, even if only "
    "approximate or disputed (use date_precision/confidence to flag "
    "uncertainty) — leave null only if you genuinely have no basis to guess."
)


class CivilizationProfile(BaseModel):
    canonical_name: str
    alternative_names: list[str] = Field(default_factory=list)
    summary: str
    start_year: int | None = Field(default=None, description=_YEAR_FIELD_DESCRIPTION)
    end_year: int | None = Field(default=None, description=_YEAR_FIELD_DESCRIPTION)
    date_precision: DatePrecision = DatePrecision.APPROXIMATE

    regions: list[str] = Field(default_factory=list)
    capitals: list[str] = Field(default_factory=list)
    important_cities: list[str] = Field(default_factory=list)

    predecessor_civilizations: list[str] = Field(default_factory=list)
    successor_civilizations: list[str] = Field(default_factory=list)

    periods: list[PeriodSummary] = Field(default_factory=list)

    major_rulers: list[str] = Field(default_factory=list)
    important_people: list[str] = Field(default_factory=list)

    major_event_names: list[str] = Field(default_factory=list)

    religious_systems: list[str] = Field(default_factory=list)
    important_deities: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    important_documents: list[str] = Field(default_factory=list)

    cultural_developments: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    neighboring_interactions: list[str] = Field(default_factory=list)


class EventCandidate(BaseModel):
    name: str
    event_type: EventType
    short_description: str


class EventCandidateList(BaseModel):
    items: list[EventCandidate] = Field(default_factory=list)


class EventExpansion(BaseModel):
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

    confidence: float = 0.5


class PersonCandidate(BaseModel):
    name: str
    short_description: str


class PersonCandidateList(BaseModel):
    items: list[PersonCandidate] = Field(default_factory=list)


class PersonProfile(BaseModel):
    canonical_name: str
    # Spelling/transliteration variants (e.g. Nebuchadnezzar/Nebuchadrezzar) —
    # populate generously, entity resolution leans on this more than on the
    # fuzzy-matching algorithm itself. See spec/05-llm-integration-spec.md.
    aliases: list[str] = Field(default_factory=list)
    summary: str
    titles: list[str] = Field(default_factory=list)
    birth_date: HistoricalDate | None = None
    death_date: HistoricalDate | None = None
    # By-name-only mentions — feed recursive expansion (see
    # graph/nodes.py::_enqueue_mentions), not expanded here.
    notable_events: list[str] = Field(default_factory=list)
    associated_places: list[str] = Field(default_factory=list)
    confidence: float = 0.5


class PlaceCandidate(BaseModel):
    name: str
    short_description: str


class PlaceCandidateList(BaseModel):
    items: list[PlaceCandidate] = Field(default_factory=list)


class PlaceProfile(BaseModel):
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    summary: str
    place_kind: Literal[EntityType.PLACE, EntityType.CITY, EntityType.REGION] = EntityType.PLACE
    latitude: float | None = None
    longitude: float | None = None
    modern_country: str | None = None
    ancient_region: str | None = None
    # By-name-only mentions — feed recursive expansion (see
    # graph/nodes.py::_enqueue_mentions), not expanded here.
    notable_events: list[str] = Field(default_factory=list)
    notable_people: list[str] = Field(default_factory=list)
    confidence: float = 0.5


class PolityCandidate(BaseModel):
    name: str
    short_description: str


class PolityCandidateList(BaseModel):
    items: list[PolityCandidate] = Field(default_factory=list)


class PolityProfile(BaseModel):
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    summary: str
    entity_type: Literal[
        EntityType.POLITY, EntityType.EMPIRE, EntityType.KINGDOM, EntityType.DYNASTY
    ] = EntityType.POLITY
    start_year: int | None = Field(default=None, description=_YEAR_FIELD_DESCRIPTION)
    end_year: int | None = Field(default=None, description=_YEAR_FIELD_DESCRIPTION)
    # By-name-only mentions — feed recursive expansion (see
    # graph/nodes.py::_enqueue_mentions), not expanded here.
    notable_rulers: list[str] = Field(default_factory=list)
    notable_events: list[str] = Field(default_factory=list)
    notable_people: list[str] = Field(default_factory=list)
    confidence: float = 0.5


class RelationshipCandidate(BaseModel):
    source_name: str
    # Typed directly as the controlled vocabulary enum so structured output
    # constrains the LLM to it (rather than validating a free string after the
    # fact) — see spec/02-domain-model-spec.md.
    relationship_type: RelationshipType
    target_name: str
    description: str | None = None
    start_year: int | None = Field(
        default=None,
        description=(
            "Populate when this relationship type has its own timeframe "
            "(e.g. KING_OF, RULED, MEMBER_OF_DYNASTY, CONQUERED, ATTACKED, "
            "BESIEGED, DEFEATED, ALLY_OF, ENEMY_OF, FOUNDED, DESTROYED). "
            + _YEAR_FIELD_DESCRIPTION
            + " Must stay chronologically consistent with the subject's own "
            "known timeframe given in the prompt — never invent a "
            "relationship that would require the two sides to be "
            "contemporaries when their known dates make that impossible."
        ),
    )
    end_year: int | None = Field(default=None, description=_YEAR_FIELD_DESCRIPTION)
    confidence: float = 0.5


class RelationshipCandidateList(BaseModel):
    items: list[RelationshipCandidate] = Field(default_factory=list)


class ClaimCandidate(BaseModel):
    subject_name: str | None = None
    predicate: str
    object_name: str | None = None
    statement: str
    estimated_date: HistoricalDate | None = None
    confidence: float = 0.5


class ClaimCandidateList(BaseModel):
    items: list[ClaimCandidate] = Field(default_factory=list)


class ChunkDraft(BaseModel):
    chunk_type: str
    text: str


class ChunkDraftList(BaseModel):
    items: list[ChunkDraft] = Field(default_factory=list)


class EntitySameAs(BaseModel):
    """Optional LLM tiebreaker for ambiguous (borderline-score) entity resolution matches."""

    same: bool
    confidence: float
    reasoning: str


class OrphanEntityGuess(BaseModel):
    """Classifies a bare name mentioned in a relationship/claim that didn't
    resolve to any known entity/event, so the final entity_resolution sweep
    can create a stub of the *right* type instead of always defaulting to
    Person (a stub labeled Person for e.g. "Akkadian Empire" would be a
    visibly wrong node in the graph)."""

    entity_type: EntityType
