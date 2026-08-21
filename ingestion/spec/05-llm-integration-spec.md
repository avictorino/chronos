# 05 — LLM Integration Spec

## Contrato

```python
class LLMClient(Protocol):
    async def generate_structured(self, prompt: str, schema: type[BaseModel]) -> BaseModel: ...

class EmbeddingClient(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

`LLM_PROVIDER` → classe concreta:

| `LLM_PROVIDER` | `LLMClient` | `EmbeddingClient` |
|---|---|---|
| `ollama` (default) | `OllamaLLMClient` | `OllamaEmbeddingClient` |
| `openai` | `OpenAILLMClient` | `OpenAIEmbeddingClient` |

Nenhuma função de negócio depende de parse de texto livre — todo boundary usa Pydantic.

## Contratos input → output, em ordem de uso no workflow

| Nó | Input | Output |
|---|---|---|
| `extract_civilization_profile` | `CivilizationSeed` | `CivilizationProfile` |
| `discover_events` | `CivilizationProfile` | `EventCandidateList` |
| `expand_events` | `EventCandidate` | `EventExpansion` |
| `discover_people` | `CivilizationProfile` + eventos processados | `PersonCandidateList` |
| `expand_people` | `PersonCandidate` | `PersonProfile` |
| `discover_places` | `CivilizationProfile` + eventos/pessoas processados | `PlaceCandidateList` |
| `expand_places` | `PlaceCandidate` | `PlaceProfile` |
| `extract_relationships` | um sujeito processado (evento/pessoa/lugar) | `RelationshipCandidateList` |
| `generate_claims` | um sujeito processado | `ClaimCandidateList` |
| `entity_resolution` (tiebreaker opcional) | par de entidades ambíguas | `EntitySameAs` |
| `generate_chunks` | uma entidade/evento processado + `ChunkType` aplicável | `ChunkDraftList` |

Toda lista é retornada como um wrapper de objeto (`class EventCandidateList(BaseModel): items: list[EventCandidate]`) — structured output exige um schema de objeto no topo.

## Prompt da civilização (contrato inicial)

```
Create a structured historical overview of:
{civilization_name}

Time range (seed only, not authoritative): {start_year} to {end_year}

Identify: canonical name, alternative names, dates, geographic regions, capitals,
important cities, predecessor/successor civilizations, political entities, major
historical periods, major rulers, important people, major events, wars, battles,
migrations, treaties, religious systems, important deities, languages, important
documents, cultural developments, technologies, interactions with neighboring
civilizations.

Return ONLY data compatible with the supplied JSON schema.
Do not invent exact dates when uncertain — represent uncertain chronology as ranges.
Separate widely accepted information from disputed interpretation.
This output represents LLM-derived candidate knowledge, not verified historical fact.
```

A primeira chamada retorna só `CivilizationProfile` (nomes/resumos, não os objetos completos) — o workflow expande cada evento/pessoa/lugar individualmente depois, para obter profundidade sem estourar um único prompt.

## Prompts de expansão (aliases explícitos para entity resolution)

Os prompts de `PersonProfile`/`PlaceProfile` instruem explicitamente a LLM a popular `aliases` com variantes de grafia e transliterações conhecidas (ex. "Nebuchadnezzar" / "Nebuchadrezzar" / "Nabu-kudurri-usur") — a robustez da entity resolution (`06`) depende mais da qualidade dessa instrução do que do algoritmo de matching em si.

## Retry e self-correction

Decorator `tenacity` genérico (aplicado no nível do Protocol, não duplicado por provider) cobre três casos:

1. Erro de conexão/timeout → retry com backoff.
2. `429` / rate-limit (mais provável com `LLM_CONCURRENCY > 1` contra a OpenAI) → retry com backoff exponencial.
3. `pydantic.ValidationError` → **não** repete a mesma chamada; reenvia o prompt original com o erro de validação anexado, pedindo correção ("self-correction retry"). Modelos locais pequenos (ex. `qwen3.5:9b`) são menos confiáveis que modelos hospedados para aderir a um JSON Schema estrito, especialmente em schemas aninhados.

## Parâmetros

`temperature=0` (ou o mais próximo que o provider permitir) em toda chamada estruturada, para maximizar determinismo.

## Mock para testes

`tests/conftest.py::FakeLLMClient` implementa o `Protocol LLMClient` com uma fila de respostas por `schema` (permite respostas diferentes a cada iteração de um self-loop). Nenhum teste unitário depende de Ollama ou OpenAI reais.
