# 04 — Neo4j Schema Spec

## Labels

`:Civilization` `:Person` `:Place` `:Polity` `:Document` `:Concept` `:Event` `:Claim` `:Chunk` `:IngestionRun`

## Constraints (unicidade por `id`)

```cypher
CREATE CONSTRAINT civilization_id_unique IF NOT EXISTS FOR (n:Civilization) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT person_id_unique       IF NOT EXISTS FOR (n:Person) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT place_id_unique        IF NOT EXISTS FOR (n:Place) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT polity_id_unique       IF NOT EXISTS FOR (n:Polity) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT document_id_unique     IF NOT EXISTS FOR (n:Document) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT concept_id_unique      IF NOT EXISTS FOR (n:Concept) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT event_id_unique        IF NOT EXISTS FOR (n:Event) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT claim_id_unique        IF NOT EXISTS FOR (n:Claim) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT chunk_id_unique        IF NOT EXISTS FOR (n:Chunk) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT run_id_unique          IF NOT EXISTS FOR (n:IngestionRun) REQUIRE n.id IS UNIQUE;
```

## Índices auxiliares

Range index em `canonical_name` por label de entidade, para acelerar a busca de candidatos da entity resolution:

```cypher
CREATE INDEX person_name_idx IF NOT EXISTS FOR (n:Person) ON (n.canonical_name);
CREATE INDEX place_name_idx  IF NOT EXISTS FOR (n:Place) ON (n.canonical_name);
CREATE INDEX polity_name_idx IF NOT EXISTS FOR (n:Polity) ON (n.canonical_name);
```

(Otimização futura, não V1: índice fulltext composto sobre `canonical_name` + `aliases` quando o catálogo crescer além de centenas de nós por tipo.)

## Vector index

```cypher
CREATE VECTOR INDEX chunk_embedding_idx IF NOT EXISTS
FOR (c:Chunk) ON (c.embedding)
OPTIONS {indexConfig: {`vector.dimensions`: $dim, `vector.similarity_function`: 'cosine'}}
```

`$dim` é obtido empiricamente: `app/persistence/vector.py::get_or_detect_dimension` embeda uma string de teste na primeira execução e cacheia `len(vetor)`, respeitando um override manual via `EMBEDDING_DIMENSIONS` no `.env`. Antes de criar o índice, `ensure_vector_index` consulta `SHOW VECTOR INDEXES`; se já existir um índice com dimensão diferente da detectada, falha com um erro explícito em vez de mascarar o conflito (isso normalmente significa que `OLLAMA_EMBEDDING_MODEL`/`OPENAI_EMBEDDING_MODEL` mudou depois que dados já foram ingeridos — ver limitação conhecida em `06-acceptance-tests-spec.md`).

Similaridade: `cosine`.

## Nota de compatibilidade futura com `neo4j-graphrag-python`

Não adicionamos essa dependência agora (não há retriever nesta fase — seria abstração prematura), mas o schema foi desenhado deliberadamente compatível com o que ela espera: nome do índice (`chunk_embedding_idx`), label (`:Chunk`), propriedade (`embedding`) e o padrão `(:Chunk)-[:DESCRIBES]->(:Entity)` são a via natural de upgrade quando a fase de GraphRAG de consulta for implementada (`VectorRetriever`/`VectorCypherRetriever`/`Text2Cypher`).

## Padrão de merge idempotente

Nó:

```cypher
MERGE (n:Person {id: $id})
SET n += $props, n.updated_at = datetime()
```

Relacionamento — **o `id` precisa estar dentro do padrão do `MERGE`**, nunca aplicado via `SET` depois de um `MERGE` sem propriedades:

```cypher
MATCH (s {id: $source_id}), (t {id: $target_id})
MERGE (s)-[r:KING_OF {id: $rel_id}]->(t)
SET r += $props
```

## Nós de proveniência de conhecimento

```
(:Person)-[:SUBJECT_OF]->(:Claim)-[:ABOUT]->(:Event)
(:Chunk)-[:DESCRIBES]->(:Person|:Event|:Place|:Polity|:Document|:Concept|:Civilization)
```

## `IngestionRun`

```
(:IngestionRun {
  id, started_at, finished_at, status,
  model, civilization,
  entities_created, entities_updated,
  errors  // lista serializada (JSON string) de {node, item, message}
})
```
