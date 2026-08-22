from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from app.domain.enums import DatePrecision, EntityType
from app.domain.models import (
    AnyEntity,
    HistoricalClaim,
    HistoricalDate,
    HistoricalRelationship,
    Person,
    Place,
    Polity,
)
from app.utils.ids import stable_claim_id, stable_entity_id, stable_relationship_id


# --- HistoricalDate ----------------------------------------------------------


def test_historical_date_negative_year_is_bce():
    date = HistoricalDate(estimated_year=-701, precision=DatePrecision.APPROXIMATE)
    assert date.estimated_year == -701


def test_historical_date_valid_range():
    date = HistoricalDate(earliest_year=-350, latest_year=-320, precision=DatePrecision.RANGE)
    assert date.earliest_year <= date.latest_year


def test_historical_date_reversed_range_is_swapped_not_rejected():
    """LLMs reliably get earliest/latest backwards for BCE ranges — self-heal
    by swapping instead of rejecting the whole item over an ordering slip."""
    date = HistoricalDate(earliest_year=-320, latest_year=-350, precision=DatePrecision.RANGE)
    assert date.earliest_year == -350
    assert date.latest_year == -320


# --- AnyEntity discriminated union -------------------------------------------


def test_any_entity_person_discriminates_to_person_class():
    adapter = TypeAdapter(AnyEntity)
    entity = adapter.validate_python(
        {
            "id": "person_1",
            "entity_type": "PERSON",
            "canonical_name": "Sennacherib",
        }
    )
    assert isinstance(entity, Person)


def test_any_entity_empire_discriminates_to_polity_class():
    """Polity maps 4 EntityType values (POLITY/EMPIRE/KINGDOM/DYNASTY) onto one
    class — this is the many-to-one case the callable Discriminator exists for."""
    adapter = TypeAdapter(AnyEntity)
    entity = adapter.validate_python(
        {
            "id": "polity_1",
            "entity_type": "EMPIRE",
            "canonical_name": "Neo-Assyrian Empire",
        }
    )
    assert isinstance(entity, Polity)
    assert entity.entity_type == EntityType.EMPIRE


def test_any_entity_place_discriminates_to_place_class():
    adapter = TypeAdapter(AnyEntity)
    entity = adapter.validate_python(
        {
            "id": "place_1",
            "entity_type": "CITY",
            "canonical_name": "Ur",
        }
    )
    assert isinstance(entity, Place)


# --- HistoricalRelationship ---------------------------------------------------


def test_relationship_type_restricted_to_controlled_vocabulary():
    with pytest.raises(ValidationError):
        HistoricalRelationship(
            id="rel_1",
            source_entity_id="a",
            target_entity_id="b",
            relationship_type="MADE_UP_TYPE",
            confidence=0.5,
        )


def test_relationship_type_accepts_known_value():
    rel = HistoricalRelationship(
        id="rel_1",
        source_entity_id="a",
        target_entity_id="b",
        relationship_type="KING_OF",
        confidence=0.9,
    )
    assert rel.relationship_type.value == "KING_OF"


# --- HistoricalClaim -----------------------------------------------------------


def test_claim_defaults_are_unverified_llm_generated():
    claim = HistoricalClaim(
        id="claim_1",
        subject_id="person_1",
        predicate="campaigned_against",
        object_id="place_1",
        statement="Sennacherib campaigned against Judah around 701 BCE.",
        confidence=0.7,
        generated_by_model="qwen3.5:9b",
    )
    assert claim.origin == "llm_generated"
    assert claim.verification_status == "unverified"


# --- Stable IDs ----------------------------------------------------------------


def test_stable_entity_id_deterministic():
    id_a = stable_entity_id(EntityType.PERSON, "Sennacherib")
    id_b = stable_entity_id(EntityType.PERSON, "Sennacherib")
    assert id_a == id_b


def test_stable_entity_id_differs_by_name():
    id_a = stable_entity_id(EntityType.PERSON, "Sennacherib")
    id_b = stable_entity_id(EntityType.PERSON, "Hezekiah")
    assert id_a != id_b


def test_stable_relationship_id_not_commutative():
    forward = stable_relationship_id("person_1", "KING_OF", "polity_1")
    backward = stable_relationship_id("polity_1", "KING_OF", "person_1")
    assert forward != backward


def test_stable_claim_id_sensitive_to_statement_text():
    id_a = stable_claim_id("person_1", "campaigned_against", "place_1", "Statement A.")
    id_b = stable_claim_id("person_1", "campaigned_against", "place_1", "Statement B.")
    assert id_a != id_b
