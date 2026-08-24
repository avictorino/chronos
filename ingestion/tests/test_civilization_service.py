from __future__ import annotations

from app.config import Settings
from app.services.civilization_service import scaled_budgets


def _settings() -> Settings:
    return Settings(_env_file=None)


def test_score_10_gets_the_full_ceiling_unscaled():
    budgets = scaled_budgets(10, _settings())
    settings = _settings()
    assert budgets.max_events == settings.max_events_per_civilization
    assert budgets.max_people == settings.max_people_per_civilization
    assert budgets.max_places == settings.max_places_per_civilization
    assert budgets.max_polities == settings.max_polities_per_civilization
    assert budgets.max_depth == settings.max_expansion_depth


def test_score_0_gets_only_the_floor():
    budgets = scaled_budgets(0, _settings())
    assert budgets.max_events == 5
    assert budgets.max_people == 10
    assert budgets.max_places == 10
    assert budgets.max_polities == 2
    assert budgets.max_depth == 1


def test_budgets_increase_monotonically_with_score():
    settings = _settings()
    previous = scaled_budgets(0, settings)
    for score in range(1, 11):
        current = scaled_budgets(score, settings)
        assert current.max_events >= previous.max_events
        assert current.max_people >= previous.max_people
        assert current.max_places >= previous.max_places
        assert current.max_polities >= previous.max_polities
        assert current.max_depth >= previous.max_depth
        previous = current


def test_mid_score_is_meaningfully_simplified_relative_to_ceiling():
    """The scale is deliberately superlinear (see civilization_service.py) —
    a "moderately important" civilization should land well below half the
    ceiling and lose a full depth level, not just barely dip below score 10."""
    budgets = scaled_budgets(6, _settings())
    settings = _settings()
    assert budgets.max_events < settings.max_events_per_civilization / 2
    assert budgets.max_depth < settings.max_expansion_depth


def test_out_of_range_scores_are_clamped():
    settings = _settings()
    assert scaled_budgets(-5, settings) == scaled_budgets(0, settings)
    assert scaled_budgets(99, settings) == scaled_budgets(10, settings)
