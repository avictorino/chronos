"""Generic, multi-provider LLM layer.

Deliberately a single file (not a `llm/` subpackage): Protocols, both provider
implementations, every prompt-builder function, and the provider factory all
live here. See spec/03-architecture-spec.md and spec/05-llm-integration-spec.md.
"""

from __future__ import annotations

from typing import Protocol, TypeVar

import httpx
import ollama
import openai
from pydantic import BaseModel, ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import Settings
from app.domain.enums import EventType
from app.domain.schemas import CivilizationProfile, CivilizationSeed
from app.utils.logging import get_logger

log = get_logger("llm")

SchemaT = TypeVar("SchemaT", bound=BaseModel)

_MAX_SELF_CORRECTION_ATTEMPTS = 2  # extra attempts *after* the first, on ValidationError


# --- Protocols ---------------------------------------------------------------


class LLMClient(Protocol):
    async def generate_structured(self, prompt: str, schema: type[SchemaT]) -> SchemaT: ...


class EmbeddingClient(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def _network_retry(*exception_types: type[Exception]):
    return retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        retry=retry_if_exception_type(exception_types),
    )


# --- Ollama (default, fully local) -------------------------------------------


class OllamaLLMClient:
    def __init__(self, settings: Settings) -> None:
        self._client = ollama.AsyncClient(host=settings.ollama_base_url)
        self._model = settings.ollama_model

    @_network_retry(httpx.ConnectError, httpx.TimeoutException, ollama.ResponseError)
    async def _chat_once(self, messages: list[dict[str, str]], schema: type[BaseModel]) -> str:
        response = await self._client.chat(
            model=self._model,
            messages=messages,
            format=schema.model_json_schema(),
            options={"temperature": 0},
            # Structured extraction wants fast, direct JSON, not chain-of-thought —
            # on hybrid-reasoning models (e.g. the Qwen3 family) leaving this unset
            # lets "thinking" default on and makes every call dramatically slower
            # for no accuracy benefit here. Ignored by models that don't support it.
            think=False,
        )
        return response.message.content or ""

    async def generate_structured(self, prompt: str, schema: type[SchemaT]) -> SchemaT:
        messages = [{"role": "user", "content": prompt}]
        last_error: ValidationError | None = None
        for attempt in range(1 + _MAX_SELF_CORRECTION_ATTEMPTS):
            if attempt > 0:
                log.debug("LLM", "Re-prompting after validation error", attempt=attempt)
                messages = [
                    {"role": "user", "content": prompt},
                    {
                        "role": "user",
                        "content": (
                            "Your previous response did not match the required schema. "
                            f"Validation error: {last_error}\n"
                            "Return ONLY corrected JSON matching the schema."
                        ),
                    },
                ]
            raw = await self._chat_once(messages, schema)
            try:
                return schema.model_validate_json(raw)
            except ValidationError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error


class OllamaEmbeddingClient:
    def __init__(self, settings: Settings) -> None:
        self._client = ollama.AsyncClient(host=settings.ollama_base_url)
        self._model = settings.ollama_embedding_model

    @_network_retry(httpx.ConnectError, httpx.TimeoutException, ollama.ResponseError)
    async def embed(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.embed(model=self._model, input=texts)
        return [list(vector) for vector in response.embeddings]


# --- OpenAI (hosted, enables higher LLM_CONCURRENCY) -------------------------


class OpenAILLMClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        self._client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_model

    @_network_retry(
        openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError
    )
    async def generate_structured(self, prompt: str, schema: type[SchemaT]) -> SchemaT:
        completion = await self._client.chat.completions.parse(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            response_format=schema,
            temperature=0,
        )
        message = completion.choices[0].message
        if message.refusal:
            raise RuntimeError(f"OpenAI refused the structured output request: {message.refusal}")
        assert message.parsed is not None
        return message.parsed


class OpenAIEmbeddingClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        self._client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_embedding_model

    @_network_retry(
        openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError
    )
    async def embed(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.embeddings.create(model=self._model, input=texts)
        return [item.embedding for item in response.data]


# --- Factories -----------------------------------------------------------------


def build_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "openai":
        return OpenAILLMClient(settings)
    return OllamaLLMClient(settings)


def build_embedding_client(settings: Settings) -> EmbeddingClient:
    if settings.llm_provider == "openai":
        return OpenAIEmbeddingClient(settings)
    return OllamaEmbeddingClient(settings)


# --- Prompt builders (one per input->output contract, spec/05) ----------------
#
# Every prompt reminds the model that its output is "LLM-derived candidate
# knowledge, not verified historical fact" (spec/01) and that uncertain
# chronology must be represented as ranges, never invented exact dates.

_CANDIDATE_KNOWLEDGE_NOTICE = (
    "This output represents LLM-derived candidate knowledge, not verified "
    "historical fact. Do not invent exact dates when uncertain — represent "
    "uncertain chronology as ranges. Separate widely accepted information from "
    "disputed interpretation. Return ONLY data compatible with the supplied JSON schema."
)


def build_civilization_profile_prompt(seed: CivilizationSeed) -> str:
    return f"""Create a structured historical overview of: {seed.name}

Time range (seed only, not authoritative): {seed.approximate_start_year} to {seed.approximate_end_year}

Identify: canonical name, alternative names, dates, geographic regions, capitals,
important cities, predecessor/successor civilizations, major historical periods,
major rulers, important people (by name only — they get expanded individually
later), major event names (by name only — they get expanded individually later),
religious systems, important deities, languages, important documents, cultural
developments, technologies, interactions with neighboring civilizations.

{_CANDIDATE_KNOWLEDGE_NOTICE}"""


def build_event_discovery_prompt(profile: CivilizationProfile, max_events: int) -> str:
    return f"""Given this civilization profile:

{profile.model_dump_json(indent=2)}

List up to {max_events} of the most historically significant events (battles, wars,
migrations, treaties, conquests, foundations, destructions) for this civilization.
For each, give only a name, an event_type, and a one-sentence description — they
get expanded individually later.

{_CANDIDATE_KNOWLEDGE_NOTICE}"""


def build_event_expansion_prompt(candidate_name: str, event_type: EventType, context: str) -> str:
    return f"""Expand this historical event candidate into full detail:

Name: {candidate_name}
Event type: {event_type.value}
Civilization context: {context}

Provide: full description, a HistoricalDate (use ranges/precision honestly if
uncertain), the people/places/polities involved (by name), causes, consequences,
and any known aliases/alternative names for this event.

{_CANDIDATE_KNOWLEDGE_NOTICE}"""


def build_person_discovery_prompt(profile: CivilizationProfile, event_names: list[str], max_people: int) -> str:
    return f"""Given this civilization profile and its major events:

Civilization: {profile.canonical_name}
Major rulers/people already named: {profile.major_rulers + profile.important_people}
Major events: {event_names}

List up to {max_people} historically significant people for this civilization who
are not already fully covered above. For each, give only a name and a one-sentence
description — they get expanded individually later.

{_CANDIDATE_KNOWLEDGE_NOTICE}"""


def build_person_expansion_prompt(candidate_name: str, context: str) -> str:
    return f"""Expand this historical person candidate into full detail:

Name: {candidate_name}
Civilization context: {context}

Provide: canonical name, a summary, titles held, birth/death HistoricalDate
(use ranges/precision honestly if uncertain), and — importantly — populate
`aliases` generously with every known spelling variant and transliteration of
this person's name in other languages/scripts (this is what lets entity
resolution avoid creating duplicate people for the same person cited under a
different spelling).

{_CANDIDATE_KNOWLEDGE_NOTICE}"""


def build_place_discovery_prompt(
    profile: CivilizationProfile, event_names: list[str], person_names: list[str], max_places: int
) -> str:
    return f"""Given this civilization profile, its major events and people:

Civilization: {profile.canonical_name}
Capitals/important cities already named: {profile.capitals + profile.important_cities}
Major events: {event_names}
Major people: {person_names}

List up to {max_places} historically significant places (cities, regions) for this
civilization not already fully covered above. For each, give only a name and a
one-sentence description — they get expanded individually later.

{_CANDIDATE_KNOWLEDGE_NOTICE}"""


def build_place_expansion_prompt(candidate_name: str, context: str) -> str:
    return f"""Expand this historical place candidate into full detail:

Name: {candidate_name}
Civilization context: {context}

Provide: canonical name, aliases (variant spellings/transliterations), a
summary, whether it is best classified as a PLACE/CITY/REGION, an approximate
latitude/longitude if reasonably known (mark as a best guess, not authoritative),
the modern country, and the ancient region/province it belonged to.

{_CANDIDATE_KNOWLEDGE_NOTICE}"""


def build_relationship_extraction_prompt(subject_name: str, subject_context: str) -> str:
    return f"""Given this historical subject:

{subject_name}
Context: {subject_context}

Extract relationships between this subject and other entities/events already
mentioned in its context, using ONLY these relationship types: KING_OF, RULED,
MEMBER_OF_DYNASTY, FATHER_OF, MOTHER_OF, CHILD_OF, MARRIED_TO, ALLY_OF, ENEMY_OF,
CONQUERED, ATTACKED, BESIEGED, DEFEATED, PARTICIPATED_IN, COMMANDER_IN, FOUNDED,
DESTROYED, LOCATED_IN, OCCURRED_AT, PRECEDED_BY, SUCCEEDED_BY, CONTEMPORARY_OF,
MENTIONED_IN, DESCRIBED_BY, INFLUENCED, RELATED_TO. Refer to the other side of
each relationship by name (source_name/target_name), not by id.

{_CANDIDATE_KNOWLEDGE_NOTICE}"""


def build_claim_generation_prompt(subject_name: str, subject_context: str) -> str:
    return f"""Given this historical subject:

{subject_name}
Context: {subject_context}

Generate specific, checkable claims (statements) about this subject — the kind
of sentence a historian could later confirm or dispute against a primary source.
Example: "Sennacherib campaigned against Judah around 701 BCE." Each claim needs
a predicate (short verb phrase), an optional subject/object entity name, the full
statement text, an estimated date if applicable, and a confidence score.

{_CANDIDATE_KNOWLEDGE_NOTICE}"""


def build_chunk_generation_prompt(entity_name: str, entity_kind: str, summary: str) -> str:
    return f"""Given this {entity_kind}:

Name: {entity_name}
Summary: {summary}

Write 1-3 short, semantically coherent knowledge chunks (a few sentences each,
self-contained, suitable for semantic search) describing this {entity_kind}.
Pick the most fitting chunk_type(s) from: civilization_overview, person_overview,
event_overview, battle_overview, political_relationship, religious_context,
cultural_development.

{_CANDIDATE_KNOWLEDGE_NOTICE}"""


def build_orphan_entity_type_prompt(name: str) -> str:
    return f"""Classify this historical name into the single best-fitting entity type.

Name: {name}

Choose the entity_type that best matches what this name most likely refers to:
CIVILIZATION, POLITY, EMPIRE, KINGDOM, DYNASTY, PERSON, PLACE, CITY, REGION,
DOCUMENT, TEXT, INSCRIPTION, RELIGION, DEITY, CULTURE, LANGUAGE, CONCEPT.

If genuinely ambiguous, prefer PERSON only if it plausibly could be a person's
name; otherwise prefer CONCEPT as a general fallback.

{_CANDIDATE_KNOWLEDGE_NOTICE}"""


def build_entity_same_as_prompt(candidate_name: str, existing_name: str, context: str) -> str:
    return f"""Are these two names referring to the SAME historical entity?

Candidate: {candidate_name}
Existing (already in the knowledge graph): {existing_name}
Context: {context}

Answer with same (bool), a confidence score, and a short reasoning."""
