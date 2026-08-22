# 06 — Acceptance Tests Spec

## Critério de aceite final

- `ingestion/` existe e está organizado conforme `03-architecture-spec.md`.
- As specs existem e são a fonte da verdade (inconsistência código↔spec: corrige-se a spec primeiro).
- `uv run pytest` passa, sem exigir Ollama/Postgres reais para os testes unitários.
- O provider LLM é trocável por `.env` (`LLM_PROVIDER=ollama|openai`), Ollama é o default.
- Toda resposta relevante de LLM é Structured Output validado por Pydantic.
- É possível processar uma civilização ponta a ponta (`ingest --civilization sumer`).
- Entidades são deduplicadas (mesmo cross-civilização); eventos, pessoas, lugares, relações, claims, chunks e embeddings são persistidos.
- Existe uma coluna vetorial (`pgvector`) sobre `chunks.embedding`, dimensionada e indexada (HNSW) automaticamente.
- Reexecutar a mesma ingestão não duplica o grafo (idempotência via `INSERT ... ON CONFLICT (id) DO UPDATE` com IDs estáveis).
- Falhas por item são registradas (`state.errors` → `IngestionRun.errors`) sem abortar o run.
- `--dry-run` chama a LLM e mostra o resultado estruturado sem escrever no Postgres.
- `--resume <run_id>` retoma um run interrompido a partir do último checkpoint.
- Nenhum frontend, chatbot ou RAG de consulta é implementado nesta etapa.

## Matriz teste → requisito

| Teste | Requisito coberto |
|---|---|
| `test_models.py::test_historical_date_*` | Anos negativos = BCE, invariante `earliest<=latest`, precisão/confiança |
| `test_models.py::test_any_entity_discriminated_union` | `entity_type` → subclasse correta (inclui `Polity` cobrindo 4 valores) |
| `test_models.py::test_relationship_type_enum` | `relationship_type` restrito ao vocabulário controlado |
| `test_models.py::test_claim_defaults` | `origin`/`verification_status` default corretos, nunca "fact" |
| `test_models.py::test_stable_ids_deterministic` | IDs estáveis: mesmo input → mesmo id; relationship id não-comutativo |
| `test_entity_resolution.py::test_alexander_aliases_merge` | "Alexander the Great" / "Alexander III of Macedon" / "Alexander III" → mesmo candidato |
| `test_entity_resolution.py::test_canonicalization` | Acentos/honoríficos normalizados antes do match |
| `test_entity_resolution.py::test_nebuchadnezzar_known_limitation` | Caso feliz (aliases populados) funciona; caso sem aliases é uma limitação documentada, não um bug |
| `test_workflow.py::test_full_graph_with_fake_llm` | Grafo completo roda com `FakeLLMClient`, respeita `MAX_*`, popula `state` |
| `test_workflow.py::test_item_error_does_not_abort_run` | Erro em 1 item vira `state.errors`, loop continua |
| `test_workflow.py::test_entity_upsert_is_idempotent` (`@pytest.mark.integration`) | Rodar o mesmo upsert 2x contra Postgres real não muda a contagem de linhas |
| `test_workflow.py::test_relationship_traversal_with_recursive_cte` (`@pytest.mark.integration`) | `WITH RECURSIVE` encontra corretamente vizinhos a 1 e 2 hops, respeitando `max_hops` |

## Definição precisa de `--dry-run`

Chama o `LLMClient` real (Ollama ou OpenAI, conforme `.env`) e imprime o resultado estruturado (profile, eventos, pessoas, lugares, relações, claims, chunks) formatado. **Nunca** chama nenhum método de escrita dos repositórios — nem `IngestionRun` é criado no Postgres. Útil para desenvolvimento/depuração de prompts sem sujar o grafo.

## Cenário de idempotência (validação manual, seção "Primeiro teste real")

1. `ingest --civilization sumer --max-events 5 --max-people 10 --max-places 10`
2. `SELECT count(*) FROM entities;` (e o mesmo para `events`, `relationships`, `claims`, `chunks`).
3. Rodar o mesmo comando de novo.
4. Contagens devem ser iguais (a menos que a segunda chamada de LLM descubra itens genuinamente novos, o que não é esperado com o mesmo prompt/seed e `temperature=0`).

## Segundo teste real: cross-civilização

1. Ingerir `sumer`.
2. Ingerir `akkadian_empire`.
3. Verificar que cidades/entidades mencionadas em ambas (ex. Ur) não foram duplicadas — `resolve_entity` deve ter encontrado a linha já existente no Postgres.

## Limitações conhecidas do V1 (não são bugs, são escopo)

- Fuzzy matching (`rapidfuzz`) cobre variação ortográfica (Nebuchadnezzar/Nebuchadrezzar), não transliteração entre idiomas com edit-distance alto (Nabucodonosor), a menos que o LLM já tenha populado `aliases` com a variante.
- `HistoricalClaim.id` inclui o texto da `statement` — reruns com frase reformulada podem acumular quase-duplicatas.
- Trocar `OLLAMA_EMBEDDING_MODEL`/`OPENAI_EMBEDDING_MODEL` depois de dados já ingeridos invalida a coluna vetorial existente sem migração automática (procedimento manual: `ALTER TABLE`, re-embed).
- `RelationshipRepository.find_connected` (`WITH RECURSIVE`) é deliberadamente não otimizado — re-percorre `relationships` a cada hop, sem tuning de query plan. Aceitável no volume desta etapa; revisar se/quando a camada de consulta virar produto real.
- Sem testes de GraphRAG/retrieval de ponta-a-ponta e sem testes de source ingestion — só confirmação de que o schema (colunas/índices) é compatível com essas extensões futuras.
- Bug real encontrado em validação manual (corrigido): um exact-match apenas entre *aliases* (nenhum dos dois lados sendo o nome canônico) podia forçar merge imediato mesmo entre eventos genuinamente diferentes — dois eventos distintos da conquista acadiana colapsaram em uma única linha em `events` durante o teste real com Sumer→Akkadian Empire. Corrigido em `app/services/entity_resolution.py::resolve_entity`: um exact-match só é aceito como merge automático quando pelo menos um dos lados é o nome canônico (não apenas um alias); um match alias-a-alias vira sinal forte (0.80) que ainda passa pela verificação de embedding, não um merge automático. `HistoricalDate` também passou a normalizar (trocar) `earliest_year`/`latest_year` invertidos em vez de rejeitar — LLMs erram a ordem com frequência em datas BCE.
