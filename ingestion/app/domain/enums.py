"""All enums for the domain model. No logic here — see models.py / schemas.py."""

from __future__ import annotations

from enum import Enum


class EntityType(str, Enum):
    """Persistent 'entity' node types — things that exist outside the flow of a
    single event. Event-shaped types (BATTLE, WAR, ...) live in EventType instead;
    keeping them here would contradict the Entity vs Event distinction (see
    spec/01-product-spec.md)."""

    CIVILIZATION = "CIVILIZATION"
    POLITY = "POLITY"
    EMPIRE = "EMPIRE"
    KINGDOM = "KINGDOM"
    DYNASTY = "DYNASTY"
    PERSON = "PERSON"
    PLACE = "PLACE"
    CITY = "CITY"
    REGION = "REGION"
    DOCUMENT = "DOCUMENT"
    TEXT = "TEXT"
    INSCRIPTION = "INSCRIPTION"
    RELIGION = "RELIGION"
    DEITY = "DEITY"
    CULTURE = "CULTURE"
    LANGUAGE = "LANGUAGE"
    CONCEPT = "CONCEPT"


class EventType(str, Enum):
    GENERIC = "GENERIC"
    BATTLE = "BATTLE"
    WAR = "WAR"
    MIGRATION = "MIGRATION"
    TREATY = "TREATY"
    CONQUEST = "CONQUEST"
    FOUNDATION = "FOUNDATION"
    DESTRUCTION = "DESTRUCTION"


class DatePrecision(str, Enum):
    EXACT = "exact"
    APPROXIMATE = "approximate"
    RANGE = "range"
    BEFORE = "before"
    AFTER = "after"
    UNKNOWN = "unknown"
    DISPUTED = "disputed"


class RelationshipType(str, Enum):
    KING_OF = "KING_OF"
    RULED = "RULED"
    MEMBER_OF_DYNASTY = "MEMBER_OF_DYNASTY"

    FATHER_OF = "FATHER_OF"
    MOTHER_OF = "MOTHER_OF"
    CHILD_OF = "CHILD_OF"
    MARRIED_TO = "MARRIED_TO"

    ALLY_OF = "ALLY_OF"
    ENEMY_OF = "ENEMY_OF"

    CONQUERED = "CONQUERED"
    ATTACKED = "ATTACKED"
    BESIEGED = "BESIEGED"
    DEFEATED = "DEFEATED"

    PARTICIPATED_IN = "PARTICIPATED_IN"
    COMMANDER_IN = "COMMANDER_IN"

    FOUNDED = "FOUNDED"
    DESTROYED = "DESTROYED"

    LOCATED_IN = "LOCATED_IN"
    OCCURRED_AT = "OCCURRED_AT"

    PRECEDED_BY = "PRECEDED_BY"
    SUCCEEDED_BY = "SUCCEEDED_BY"
    CONTEMPORARY_OF = "CONTEMPORARY_OF"

    MENTIONED_IN = "MENTIONED_IN"
    DESCRIBED_BY = "DESCRIBED_BY"

    INFLUENCED = "INFLUENCED"
    RELATED_TO = "RELATED_TO"


class ChunkType(str, Enum):
    CIVILIZATION_OVERVIEW = "civilization_overview"
    PERSON_OVERVIEW = "person_overview"
    EVENT_OVERVIEW = "event_overview"
    BATTLE_OVERVIEW = "battle_overview"
    POLITICAL_RELATIONSHIP = "political_relationship"
    RELIGIOUS_CONTEXT = "religious_context"
    CULTURAL_DEVELOPMENT = "cultural_development"


class ResolutionAction(str, Enum):
    CREATE = "create"
    MERGE = "merge"
    REVIEW = "review"


class IngestionRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
