# Chronos

Chronos é uma plataforma para explorar milhares de anos de história mundial como um grafo de conhecimento navegável — civilizações, impérios, reinos, pessoas, eventos, lugares, religiões, documentos e as relações (causais, temporais, geográficas) entre eles. A visão de longo prazo é algo como **"Google Maps + Wikipedia + Knowledge Graph da História"**.

Este é um monorepo com dois projetos independentes:

| Projeto | Status | O que é |
|---|---|---|
| [`ingestion/`](ingestion/README.md) | ✅ implementado | Pipeline Python que usa um LLM local (ou OpenAI) via LangGraph para gerar, validar, deduplicar e persistir conhecimento histórico em um grafo Neo4j. |
| [`frontend/`](frontend/README.md) | 🚧 planejado, não implementado | App Firebase para navegar/visualizar o grafo de conhecimento. |

## Por que um grafo, e não um banco relacional

A história não é uma lista de fatos isolados — é uma rede densa de relações temporais, geográficas e causais entre entidades de tipos muito diferentes (uma pessoa pode ser governante de uma polity, participar de um evento, ser mencionada em um documento, ser adorada como uma divindade em outra cultura). Um grafo de propriedades (Neo4j) modela isso diretamente como nós e arestas tipadas, em vez de forçar tudo em tabelas com joins.

## Filosofia

- Simplicidade antes de abstração: um processo Python bem organizado, sem microservices/Kafka/Celery/Redis/Kubernetes.
- Todo conhecimento gerado por LLM nasce marcado como `origin=llm_generated` / `verification_status=unverified` — nunca é tratado como fato verificado. Um pipeline futuro de ingestão de fontes primárias (textos, inscrições, artigos acadêmicos) poderá confirmar ou contestar esse conhecimento.
- Determinístico e controlável: nada de agente autônomo solto — o pipeline de ingestão é um grafo de estados explícito (LangGraph), com limites de profundidade/quantidade, checkpoint e retomada, e idempotência via `MERGE`.

## Infraestrutura compartilhada

`docker-compose.yml` nesta raiz sobe o Neo4j usado pelo `ingestion/` hoje e, futuramente, por qualquer camada de consulta/API que sirva o `frontend/`:

```bash
docker compose up -d
```

Veja [`ingestion/README.md`](ingestion/README.md) para instruções completas de setup e execução do pipeline de ingestão.

## Roadmap

1. ✅ `ingestion/` — gera o grafo de conhecimento a partir de uma LLM local.
2. 🔜 Pipeline de ingestão de fontes primárias (textos históricos, inscrições, artigos) que cria `SourceClaim`s para confirmar/contestar o conhecimento gerado por LLM.
3. 🔜 Camada de consulta (GraphRAG: busca vetorial + travessia de grafo) sobre o Neo4j.
4. 🔜 `frontend/` — exploração visual do grafo (Firebase).
