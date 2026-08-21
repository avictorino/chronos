from __future__ import annotations

from pathlib import Path

import yaml

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
