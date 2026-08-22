# Chronos

Chronos é uma plataforma para explorar milhares de anos de história mundial como um grafo de conhecimento navegável — civilizações, impérios, reinos, pessoas, eventos, lugares, religiões, documentos e as relações (causais, temporais, geográficas) entre eles. A visão de longo prazo é algo como **"Google Maps + Wikipedia + Knowledge Graph da História"**.

Este é um monorepo com dois projetos independentes:

| Projeto | Status | O que é |
|---|---|---|
| [`ingestion/`](ingestion/README.md) | ✅ implementado | Pipeline Python que usa um LLM local (ou OpenAI) via LangGraph para gerar, validar, deduplicar e persistir conhecimento histórico em Postgres + pgvector. |
| [`frontend/`](frontend/README.md) | 🚧 planejado, não implementado | App Firebase para navegar/visualizar o grafo de conhecimento. |

## Grafo modelado em Postgres, não num banco de grafo nativo

A história não é uma lista de fatos isolados — é uma rede densa de relações temporais, geográficas e causais entre entidades de tipos muito diferentes (uma pessoa pode ser governante de uma polity, participar de um evento, ser mencionada em um documento, ser adorada como uma divindade em outra cultura). Um banco de grafo nativo (Neo4j) modelaria isso mais diretamente, mas o projeto usa **Postgres + [pgvector](https://github.com/pgvector/pgvector)** — a entidade/evento vira uma linha com um blob `JSONB`, a relação vira uma linha `(source_id, relationship_type, target_id)`, e travessias multi-hop usam `WITH RECURSIVE`. Trade-off consciente: menos otimizado que adjacência nativa de grafo para travessias profundas, mas evita rodar uma segunda tecnologia de banco quando já se tem Postgres+pgvector disponível — aceitável no volume desta etapa. Ver [`ingestion/spec/04-postgres-schema-spec.md`](ingestion/spec/04-postgres-schema-spec.md) para o desenho completo.

## Filosofia

- Simplicidade antes de abstração: um processo Python bem organizado, sem microservices/Kafka/Celery/Redis/Kubernetes.
- Todo conhecimento gerado por LLM nasce marcado como `origin=llm_generated` / `verification_status=unverified` — nunca é tratado como fato verificado. Um pipeline futuro de ingestão de fontes primárias (textos, inscrições, artigos acadêmicos) poderá confirmar ou contestar esse conhecimento.
- Determinístico e controlável: nada de agente autônomo solto — o pipeline de ingestão é um grafo de estados explícito (LangGraph), com limites de profundidade/quantidade, checkpoint e retomada, e idempotência via `INSERT ... ON CONFLICT`.

## Infraestrutura compartilhada

`docker-compose.yml` nesta raiz sobe um Postgres com `pgvector` para quem não já tiver um local — usado pelo `ingestion/` hoje e, futuramente, por qualquer camada de consulta/API que sirva o `frontend/`:

```bash
docker compose up -d
```

Se você já tem Postgres+pgvector rodando localmente, não precisa disso — só aponte `POSTGRES_DSN` (em `ingestion/.env`) para a sua instância.

Veja [`ingestion/README.md`](ingestion/README.md) para instruções completas de setup e execução do pipeline de ingestão.

## Roadmap

1. ✅ `ingestion/` — gera o grafo de conhecimento a partir de uma LLM local.
2. 🔜 Pipeline de ingestão de fontes primárias (textos históricos, inscrições, artigos) que cria `SourceClaim`s para confirmar/contestar o conhecimento gerado por LLM.
3. 🔜 Camada de consulta (GraphRAG: busca vetorial `pgvector` + travessia `WITH RECURSIVE`) sobre o Postgres.
4. 🔜 `frontend/` — exploração visual do grafo (Firebase).
