"""Unit tests for the date-coverage/coherence prompt & schema changes (see
approved plan, Parte B) — pure functions, no LLM/network needed.
"""

from __future__ import annotations

from app.domain.schemas import CivilizationProfile, PolityProfile, RelationshipCandidate
from app.llm import build_civilization_profile_prompt, build_relationship_extraction_prompt


def test_civilization_profile_prompt_demands_start_end_year():
    seed = _seed()
    prompt = build_civilization_profile_prompt(seed)
    assert "start_year" in prompt
    assert "end_year" in prompt
    assert "BCE" in prompt


def test_civilization_profile_year_fields_carry_a_schema_description():
    # This description ends up in the JSON schema sent to the LLM as
    # `format=` (Ollama) / `response_format=` (OpenAI) — see
    # app/llm.py::OllamaLLMClient._chat_once — so it's the most reliable way
    # to nudge structured output, not just prose in the prompt text.
    schema = CivilizationProfile.model_json_schema()
    for field in ("start_year", "end_year"):
        description = schema["properties"][field].get("description", "")
        assert "BCE" in description
        assert "best estimate" in description.lower()


def test_polity_profile_year_fields_carry_a_schema_description():
    schema = PolityProfile.model_json_schema()
    for field in ("start_year", "end_year"):
        description = schema["properties"][field].get("description", "")
        assert "BCE" in description


def test_relationship_candidate_start_year_field_mentions_coherence():
    schema = RelationshipCandidate.model_json_schema()
    description = schema["properties"]["start_year"].get("description", "")
    assert "consistent" in description.lower()


def test_relationship_extraction_prompt_includes_subject_dates_when_given():
    prompt = build_relationship_extraction_prompt(
        "Ashurbanipal", "King of Assyria.", subject_dates="born -685, died -631"
    )
    assert "Known timeframe: born -685, died -631" in prompt
    assert "chronologically consistent" in prompt


def test_relationship_extraction_prompt_omits_dates_line_when_none():
    prompt = build_relationship_extraction_prompt("Ashurbanipal", "King of Assyria.", subject_dates=None)
    assert "Known timeframe" not in prompt


def _seed():
    from app.domain.schemas import CivilizationSeed

    return CivilizationSeed(id="assyria", name="Assyria", approximate_start_year=-2500, approximate_end_year=-609)
