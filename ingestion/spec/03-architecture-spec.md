# 03 — Architecture Spec

## Componentes

```
CLI (app/main.py)
   │
   ▼
IngestionService (app/services/ingestion_service.py)
   │  builds initial IngestionState, resolves thread_id, invokes the graph
   ▼
LangGraph workflow (app/graph/workflow.py + nodes.py + state.py)
   │
   ├──▶ LLMClient / EmbeddingClient (app/llm.py)        — Ollama or OpenAI
   ├──▶ entity_resolution.resolve_entity (app/services/entity_resolution.py)
   └──▶ Repositories (app/persistence/repositories.py) ──▶ Postgres + pgvector
```

## Stack e versões-alvo

| Pacote | Papel |
|---|---|
| `langgraph` (>=1.0) | StateGraph, `Command`, checkpointing |
| `langgraph-checkpoint-sqlite` | `AsyncSqliteSaver` |
| `pydantic` (>=2.9) | Modelos de domínio e contratos de LLM |
| `pydantic-settings` | `Settings` a partir de `.env` |
| `asyncpg` (>=0.30) | Driver Postgres assíncrono |
| `ollama` | Cliente oficial para o provider local |
| `openai` | Cliente oficial para o provider hospedado |
| `tenacity` | Retry com backoff |
| `rapidfuzz` | Fuzzy matching na entity resolution |
| `pyyaml` | Leitura de `data/civilizations.yaml` |
| `pytest` / `pytest-asyncio` | Testes |

Gerenciado via `uv` (`uv sync`, `uv run ...`). Postgres precisa ter a extensão `vector` instalável (`CREATE EXTENSION IF NOT EXISTS vector` — `init-schema` faz isso; a imagem `pgvector/pgvector:pg16` do `docker-compose.yml` já vem com a extensão compilada).

## Variáveis de `.env`

Ver `.env.example` na raiz de `ingestion/` — cobre `LLM_PROVIDER`, `OLLAMA_*`, `OPENAI_*`, `LLM_CONCURRENCY`, `POSTGRES_DSN`, `EMBEDDING_DIMENSIONS`, `MAX_*`, `ENTITY_RESOLUTION_USE_LLM`, `INGESTION_CHECKPOINT_DB_PATH`, `LOG_LEVEL`. Nunca hardcodar credenciais no código.

## Camada LLM: `app/llm.py` (arquivo único, multi-provider)

Por decisão explícita do projeto, a camada LLM não é um subpacote (`llm/client.py` + `llm/prompts.py` + `llm/structured_output.py`) — tudo vive em `app/llm.py`: os `Protocol`s, as duas implementações (Ollama/OpenAI), as funções de prompt (uma por contrato) e a factory de seleção por `LLM_PROVIDER`. Trade-off aceito: um arquivo mais longo, mas sem indireção entre módulos para um volume de código que continua pequeno.

```python
class LLMClient(Protocol):
    async def generate_structured(self, prompt: str, schema: type[BaseModel]) -> BaseModel: ...

class EmbeddingClient(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

- `OllamaLLMClient` / `OllamaEmbeddingClient`: usam `ollama.AsyncClient`. `chat(..., format=Model.model_json_schema())` para structured output (JSON Schema, suportado desde dez/2024); `embed(model=..., input=...)` (endpoint `/api/embed`, não o legado `/api/embeddings`).
- `OpenAILLMClient` / `OpenAIEmbeddingClient`: usam o SDK oficial `openai`. `client.chat.completions.parse(model=..., messages=..., response_format=Model)` retorna `ParsedChatCompletion[T]` com `.choices[0].message.parsed` já validado; `client.embeddings.create(model=..., input=...)`.
- `build_llm_client(settings)` / `build_embedding_client(settings)`: factories que leem `settings.llm_provider` e retornam a implementação certa.
- Toda chamada passa por um decorator `tenacity` genérico: retry em erro de conexão/timeout e em `429`/rate-limit (backoff exponencial) e em `pydantic.ValidationError` (reenviando o prompt com o erro anexado — "self-correction", não apenas repetição cega).
- Convenção de contrato: todo schema que representa uma lista usa um wrapper de objeto (`class EventCandidateList(BaseModel): items: list[EventCandidate]`) — structured output (Ollama e OpenAI) exige um JSON Schema de objeto no topo, nunca uma lista crua.

## Concorrência: `LLM_CONCURRENCY`

Dentro de cada execução de um nó de expansão (`expand_events`, `expand_people`, `expand_places`, `extract_relationships`, `generate_claims`), até `LLM_CONCURRENCY` chamadas de LLM rodam em paralelo via `asyncio.gather` (I/O-bound — concorrência assíncrona, não threads OS). A resolução de entidade e a persistência que seguem cada resultado são **sempre sequenciais**, na ordem original do lote — nunca em paralelo, porque `resolve_entity` faz um read seguido de um write não-atômico contra o Postgres; paralelizar essa parte poderia fazer duas chamadas concorrentes criarem duas linhas para a mesma entidade. `LLM_CONCURRENCY=1` (default, provider Ollama) reproduz o comportamento inteiramente sequencial; valores maiores (4-8) fazem sentido com `LLM_PROVIDER=openai`.

## Checkpoint e resume

- `AsyncSqliteSaver` (arquivo local em `INGESTION_CHECKPOINT_DB_PATH`, default `.data/checkpoints.db`).
- `thread_id = f"{civilization_id}:{ingestion_run_id}"`.
- Run novo: gera `ingestion_run_id = uuid4()`, invoca `graph.ainvoke(initial_state, config={"configurable": {"thread_id": ..., ...}, "recursion_limit": 2000})`.
- `--resume <run_id>`: reconstrói o mesmo `thread_id`, invoca `graph.ainvoke(None, config=...)` — passar `None` como input é o sinal idiomático do LangGraph para continuar do último checkpoint salvo desse `thread_id`.
- **`recursion_limit` precisa ser explícito e generoso** (ex. 2000). O default do LangGraph é 25 steps; com os self-loops de expansão, mesmo os limites pequenos do V1 ultrapassam isso facilmente — sem o override, o workflow quebra com `GraphRecursionError` mesmo estando correto.

## Tratamento de erro

Cada nó de loop envolve o processamento de 1 item em `try/except`. Uma exceção nunca propaga para fora do nó: é registrada em `state["errors"]` (com o item, o nó e a mensagem) e o loop continua para o próximo item. O `IngestionRun` final agrega a contagem de erros — o processo nunca aborta por causa de um item.

## Idempotência

Toda escrita no Postgres usa `INSERT ... ON CONFLICT (id) DO UPDATE SET ...` sobre o `id` estável (nunca o nome cru) — o equivalente direto do `MERGE` por id do Neo4j. Como o `id` de um relacionamento já é derivado do triplo `(source_id, relationship_type, target_id)` (`stable_relationship_id`), conflito por `id` sozinho já garante que o mesmo relacionamento lógico nunca duplica.

## Travessia de grafo: `WITH RECURSIVE`

Sem adjacência nativa de grafo, travessias multi-hop (ex. "como a Assíria se conecta com a Grécia") usam `WITH RECURSIVE` sobre a tabela `relationships` — ver `RelationshipRepository.find_connected` e `spec/04-postgres-schema-spec.md`. Deliberadamente não otimizado (re-percorre a tabela a cada passo da recursão) por decisão explícita do projeto — o volume de arestas em V1 não justifica tuning de query plan. Não está conectado ao pipeline de ingestão ainda; é o bloco de construção para a futura camada de consulta (`spec/01`).
