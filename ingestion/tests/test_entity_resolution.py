from __future__ import annotations

import pytest

from app.services.entity_resolution import canonicalize, resolve_entity


# --- canonicalization ---------------------------------------------------------


def test_canonicalize_strips_honorifics_and_accents():
    assert canonicalize("Nabûcodonosor") == canonicalize("Nabucodonosor")
    assert "the great" not in canonicalize("Alexander the Great")


# --- requisito 14: Alexander aliases must be candidates for the same person --


@pytest.mark.asyncio
async def test_alexander_aliases_merge_via_exact_alias_match():
    existing = [
        {
            "id": "person_alexander",
            "canonical_name": "Alexander III of Macedon",
            "aliases": ["Alexander the Great", "Alexander III"],
        }
    ]

    result = await resolve_entity("Alexander the Great", [], existing)
    assert result.action == "merge"
    assert result.existing_entity_id == "person_alexander"

    result = await resolve_entity("Alexander III", [], existing)
    assert result.action == "merge"
    assert result.existing_entity_id == "person_alexander"


@pytest.mark.asyncio
async def test_unrelated_candidate_creates_new_entity():
    existing = [{"id": "person_alexander", "canonical_name": "Alexander III of Macedon", "aliases": []}]
    result = await resolve_entity("Hezekiah of Judah", [], existing)
    assert result.action == "create"


@pytest.mark.asyncio
async def test_fuzzy_spelling_variant_merges():
    """Nebuchadnezzar / Nebuchadrezzar — English spelling variants, edit
    distance is low enough for fuzzy matching alone to catch it."""
    existing = [{"id": "person_nebuchadnezzar", "canonical_name": "Nebuchadnezzar II", "aliases": []}]
    result = await resolve_entity("Nebuchadrezzar II", [], existing)
    assert result.action == "merge"
    assert result.existing_entity_id == "person_nebuchadnezzar"


@pytest.mark.asyncio
async def test_nebuchadnezzar_transliteration_known_limitation():
    """Known V1 limitation (documented in spec/06-acceptance-tests-spec.md):
    a transliteration with high edit-distance (Nabucodonosor, Portuguese) is
    NOT resolved by fuzzy matching alone when it isn't already listed as an
    alias — mitigation is prompting the LLM to populate `aliases` generously,
    not the matching algorithm. This test documents the gap rather than
    asserting a false capability."""
    existing = [{"id": "person_nebuchadnezzar", "canonical_name": "Nebuchadnezzar II", "aliases": []}]
    result = await resolve_entity("Nabucodonosor II", [], existing)
    assert result.action != "merge"  # documents the known gap, not a desired outcome

    # ...but it resolves correctly once the LLM has populated the alias, which
    # is the actual mitigation this project relies on:
    existing_with_alias = [
        {
            "id": "person_nebuchadnezzar",
            "canonical_name": "Nebuchadnezzar II",
            "aliases": ["Nabucodonosor II", "Nabu-kudurri-usur"],
        }
    ]
    result = await resolve_entity("Nabucodonosor II", [], existing_with_alias)
    assert result.action == "merge"


# --- require_embedding_confirmation (events) ----------------------------------


@pytest.mark.asyncio
async def test_event_fuzzy_false_positive_without_embedding_confirmation():
    """Real bug found in manual validation (spec/06): rapidfuzz.fuzz.WRatio
    reliably scores >=0.90 between event titles that are just token-reordered
    variants of each other, even when they describe genuinely different
    events (e.g. the *rise* of an empire vs its *fall*). Without
    `require_embedding_confirmation`, that alone triggers an instant merge —
    this documents the failure mode that flag exists to close."""
    existing = [{"id": "event_fall", "canonical_name": "Fall of the Akkadian Empire", "aliases": []}]
    result = await resolve_entity("The Akkadian Empire Fall", [], existing)
    assert result.action == "merge"  # the bug, reproduced


@pytest.mark.asyncio
async def test_event_resolution_requires_embedding_confirmation():
    """Same token-reordered pair as above, but with require_embedding_confirmation
    (what event_service.py actually uses) — no embedding client available means
    no semantic second opinion, so it correctly refuses to auto-merge instead
    of trusting the inflated fuzzy score."""
    existing = [{"id": "event_fall", "canonical_name": "Fall of the Akkadian Empire", "aliases": []}]
    result = await resolve_entity(
        "The Akkadian Empire Fall", [], existing, require_embedding_confirmation=True
    )
    assert result.action == "create"
