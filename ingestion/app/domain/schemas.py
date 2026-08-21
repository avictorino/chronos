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


class PeriodSummary(BaseModel):
    name: str
    description: str
    start_year: int | None = None
    end_year: int | None = None


class CivilizationProfile(BaseModel):
    canonical_name: str
    alternative_names: list[str] = Field(default_factory=list)
    summary: str
    start_year: int | None = None
    end_year: int | None = None
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
    confidence: float = 0.5


class RelationshipCandidate(BaseModel):
    source_name: str
    # Typed directly as the controlled vocabulary enum so structured output
    # constrains the LLM to it (rather than validating a free string after the
    # fact) — see spec/02-domain-model-spec.md.
    relationship_type: RelationshipType
    target_name: str
    description: str | None = None
    start_year: int | None = None
    end_year: int | None = None
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
