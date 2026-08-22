# 01 — Product Spec

## Visão

Chronos `ingestion` transforma o conhecimento paramétrico de um LLM (local via Ollama, ou hospedado via OpenAI) em um grafo de conhecimento histórico estruturado, auditável e navegável, persistido em Postgres + pgvector (travessia via `WITH RECURSIVE`, busca semântica via `pgvector`). É o primeiro módulo de uma plataforma maior que pretende funcionar como "Google Maps + Wikipedia + Knowledge Graph da História".

## Escopo desta etapa

**Implementado:**
- Pipeline determinístico (LangGraph) que parte de uma lista seed de civilizações e produz: perfil da civilização, eventos, pessoas, lugares, polities, relações, claims e chunks semânticos com embeddings.
- Deduplicação/entity resolution simples, cross-civilização.
- Persistência incremental e idempotente em Postgres (tabelas normalizadas + coluna `pgvector`).
- CLI para rodar uma civilização, todas, com `--dry-run`, ou retomar (`--resume`) um run interrompido.

**Explicitamente fora de escopo agora** (mas o modelo de dados já é compatível com essas extensões futuras):
- Frontend/visualização (`../frontend`, placeholder).
- Chatbot ou qualquer resposta em linguagem natural (GraphRAG de consulta: busca `pgvector` combinada com travessia `WITH RECURSIVE`/Text2SQL).
- Pipeline de ingestão de **fontes primárias** (Bíblia, ORACC, Perseus, inscrições, artigos acadêmicos) que produziria `SourceClaim`s capazes de confirmar ou contestar os `HistoricalClaim`s gerados por LLM.

## Glossário

| Termo | Definição |
|---|---|
| **Entity** | Nó persistente que representa algo que existiu/existe fora do fluxo de um evento específico: civilização, pessoa, lugar, polity, documento, conceito/religião/cultura. |
| **Event** | Algo que aconteceu em um momento/intervalo: batalha, guerra, migração, tratado, conquista, fundação, destruição. |
| **Claim** | Uma *afirmação* textual sobre entidades/eventos — proveniência de conhecimento, não fato verificado. Nunca chamado de "fact". |
| **Relationship** | Uma aresta tipada de vocabulário controlado entre duas entidades/eventos (ex. `KING_OF`, `PARTICIPATED_IN`). |
| **Chunk** | Um pedaço de texto curto e semanticamente coerente sobre uma ou mais entidades, com embedding — unidade de recuperação vetorial futura. |
| **Source** (futuro) | Um documento/texto primário real (não gerado por LLM) usado para sustentar ou contestar Claims. Não implementado nesta etapa. |

## Persona / modo de uso

Operador único, rodando a CLI localmente (`python -m app.main ...` via `uv run`). Sem multiusuário, sem API HTTP nesta etapa.

## Filosofia de engenharia

1. Simplicidade antes de abstração.
2. Legibilidade.
3. Execução real (vertical slice funcional, não scaffolding vazio).
4. Idempotência (rodar duas vezes não duplica o grafo).
5. Dados estruturados em todos os limites (Pydantic), nunca parse de texto livre.
6. Observabilidade (logs legíveis, `IngestionRun` rastreável no grafo).
7. Extensibilidade (o schema já prevê o que vem depois: GraphRAG, source ingestion).

Evitado deliberadamente: microservices, Kafka, Celery, Redis, Kubernetes, event sourcing, CQRS. Um processo Python bem organizado é suficiente para o volume de dados desta etapa.

## Regra central: conhecimento ≠ evidência

Todo registro produzido por este pipeline nasce com:

```
origin = "llm_generated"
verification_status = "unverified"
```

Isso não muda nesta etapa. A verificação (contra fontes primárias) é um pipeline futuro e separado.
