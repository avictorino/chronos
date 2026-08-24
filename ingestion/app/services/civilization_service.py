from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from app.config import Settings
from app.domain.schemas import CivilizationSeed

DEFAULT_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "civilizations.yaml"


def load_civilizations(path: Path = DEFAULT_DATA_PATH) -> list[CivilizationSeed]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [CivilizationSeed(**item) for item in data["civilizations"]]


def get_civilization(civilization_id: str, path: Path = DEFAULT_DATA_PATH) -> CivilizationSeed:
    for seed in load_civilizations(path):
        if seed.id == civilization_id:
            return seed
    raise ValueError(f"Unknown civilization id: {civilization_id!r} (check data/civilizations.yaml)")


@dataclass
class ScaledBudgets:
    max_events: int
    max_people: int
    max_places: int
    max_polities: int
    max_depth: int


# Floors: what a score=0 civilization still gets — small but non-trivial, so
# even a minor/less-documented civilization ends up with a real (if modest)
# graph rather than nothing. Ceilings come from Settings.max_*_per_civilization
# (score=10 gets exactly those, unscaled — e.g. Rome/Greece/Egypt).
_EVENTS_FLOOR = 5
_PEOPLE_FLOOR = 10
_PLACES_FLOOR = 10
_POLITIES_FLOOR = 2
_DEPTH_FLOOR = 1

# Deliberately superlinear (score/10) ** _SCALE_EXPONENT, not a straight
# line: a real-world timing test showed that with the ceiling budgets
# (100/200/200/20, depth=3) even one civilization can take many hours on a
# local model, because `max_expansion_depth` compounds recursive fan-out and
# large discovery budgets mean long individual LLM calls. A linear scale from
# a score of, say, 8 would still land close to the ceiling (not meaningfully
# "simplified"); this curve keeps the full budget reserved for genuinely
# top-tier scores (9-10) and drops off steeply below that — e.g. score 8 lands
# around half the ceiling with depth trimmed to 2 (the single biggest time
# lever), score 6 lands close to the floor. Tune this constant, not the
# floors/ceilings, to change how aggressive the drop-off is.
_SCALE_EXPONENT = 3.5


def _scale(score: int, floor: int, ceiling: int) -> int:
    if ceiling <= floor:
        return ceiling
    ratio = (score / 10) ** _SCALE_EXPONENT
    return round(floor + (ceiling - floor) * ratio)


def scaled_budgets(importance_score: int, settings: Settings) -> ScaledBudgets:
    """Derives per-civilization ingestion budgets from a 0-10 importance
    score (see CivilizationSeed.importance_score) by linear interpolation
    between a fixed floor and the configured MAX_*_PER_CIVILIZATION ceiling.
    Score 10 (Rome, Greece, Egypt, ...) gets the full ceiling, unscaled;
    lower-scored civilizations get a proportionally smaller — but never
    empty — budget. CLI flags (--max-events etc.) still take precedence over
    this when explicitly passed — see app/services/ingestion_service.py::run_ingestion."""
    score = max(0, min(10, importance_score))
    return ScaledBudgets(
        max_events=_scale(score, _EVENTS_FLOOR, settings.max_events_per_civilization),
        max_people=_scale(score, _PEOPLE_FLOOR, settings.max_people_per_civilization),
        max_places=_scale(score, _PLACES_FLOOR, settings.max_places_per_civilization),
        max_polities=_scale(score, _POLITIES_FLOOR, settings.max_polities_per_civilization),
        max_depth=_scale(score, _DEPTH_FLOOR, settings.max_expansion_depth),
    )
