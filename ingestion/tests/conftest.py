"""Shared test doubles — no test in this suite requires a real Ollama/OpenAI
or Neo4j instance (see spec/06-acceptance-tests-spec.md)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import pytest
from pydantic import BaseModel

from app.domain.enums import EntityType
from app.domain.schemas import CivilizationSeed


class FakeLLMClient:
    """Implements the `LLMClient` Protocol with a FIFO queue of canned
    responses *per schema class* — lets a self-loop get a different response
    on each iteration. Queue an `Exception` instance to simulate a failed call."""

    def __init__(self, responses: dict[type[BaseModel], list[Any]] | None = None) -> None:
        self._queues: dict[type[BaseModel], list[Any]] = defaultdict(list)
        for schema, values in (responses or {}).items():
            self._queues[schema] = list(values)

    def queue(self, schema: type[BaseModel], value: Any) -> None:
        self._queues[schema].append(value)

    async def generate_structured(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        queue = self._queues.get(schema)
        if not queue:
            raise AssertionError(f"FakeLLMClient: no response queued for {schema.__name__}")
        value = queue.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class FakeEmbeddingClient:
    """Deterministic pseudo-embeddings — same text always yields the same
    vector, different text yields a different one, fixed dimension."""

    def __init__(self, dimension: int = 8) -> None:
        self.dimension = dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        seed = sum(ord(c) for c in text) or 1
        return [((seed * (i + 1)) % 97) / 97 for i in range(self.dimension)]


class InMemoryEntityRepo:
    def __init__(self) -> None:
        self.by_id: dict[str, dict] = {}

    async def upsert(self, entity: Any) -> None:
        self.by_id[entity.id] = entity.model_dump(mode="json")

    async def find_candidates(self, entity_type: EntityType) -> list[dict]:
        return [
            {
                "id": e["id"],
                "canonical_name": e["canonical_name"],
                "aliases": e.get("aliases", []),
                "summary": e.get("summary"),
            }
            for e in self.by_id.values()
            if e.get("entity_type") == entity_type.value
        ]

    async def get(self, entity_id: str) -> dict | None:
        return self.by_id.get(entity_id)


class InMemoryEventRepo:
    def __init__(self) -> None:
        self.by_id: dict[str, dict] = {}

    async def upsert(self, event: Any) -> None:
        self.by_id[event.id] = event.model_dump(mode="json")

    async def find_candidates(self) -> list[dict]:
        return [
            {
                "id": e["id"],
                "canonical_name": e["name"],
                "aliases": e.get("aliases", []),
                "summary": e.get("description"),
            }
            for e in self.by_id.values()
        ]


class InMemoryUpsertRepo:
    """Generic in-memory repo for relationships/claims/chunks/runs — they only
    need `upsert`/`save` for these tests (no find_candidates consumer)."""

    def __init__(self) -> None:
        self.by_id: dict[str, dict] = {}

    async def upsert(self, item: Any) -> None:
        self.by_id[item.id] = item.model_dump(mode="json")

    async def save(self, item: Any) -> None:
        self.by_id[item.id] = item.model_dump(mode="json")


@pytest.fixture
def sample_civilization_seed() -> CivilizationSeed:
    return CivilizationSeed(id="sumer", name="Sumer", approximate_start_year=-4500, approximate_end_year=-1900)
