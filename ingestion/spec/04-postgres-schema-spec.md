# 04 — Postgres Schema Spec

> Revisão: a spec original desenhava isso para Neo4j. O projeto migrou para **Postgres + pgvector** (instância local do usuário), usando `WITH RECURSIVE` para travessia multi-hop em vez de Cypher nativo. Esta é a versão vigente.

## Por que Postgres em vez de um grafo nativo

Trade-off consciente: Postgres com uma tabela de arestas genérica + `WITH RECURSIVE` não tem a adjacência O(1) de um banco de grafo nativo (Neo4j) para travessias multi-hop — cada hop é um join adicional dentro da CTE recursiva. Aceitável para o volume desta etapa (catálogo de dezenas/centenas de nós por civilização) e para a preferência do usuário por reaproveitar a instância Postgres+pgvector que já tem localmente, evitando uma segunda tecnologia de banco só para isso. Ver `spec/06-acceptance-tests-spec.md` para a limitação de performance documentada.

## Modelo: colunas reais + `data JSONB`

Cada tabela tem só as colunas que efetivamente entram em `WHERE`/`JOIN` (tipo, nome, `source_id`/`target_id` para travessia, `entity_ids` para lookup de chunk), mais uma coluna `data JSONB` com o dump completo do modelo Pydantic — qualquer registro é reconstruído exatamente via `Model.model_validate(row["data"])`, sem precisar listar cada campo em SQL.

IDs continuam sendo os UUID5 determinísticos de sempre (`app/utils/ids.py`), mas armazenados como `TEXT` (não o tipo `uuid` nativo do Postgres) — evita conversão `str ↔ uuid.UUID` em todo repositório, sem custo real no volume desta etapa.

## Tabelas

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    aliases TEXT[] NOT NULL DEFAULT '{}',
    data JSONB NOT NULL
);
CREATE INDEX entities_type_idx ON entities (entity_type);
CREATE INDEX entities_name_idx ON entities (canonical_name);

CREATE TABLE events (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    aliases TEXT[] NOT NULL DEFAULT '{}',
    data JSONB NOT NULL
);
CREATE INDEX events_name_idx ON events (name);

CREATE TABLE relationships (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    data JSONB NOT NULL
);
CREATE INDEX relationships_source_idx ON relationships (source_id);
CREATE INDEX relationships_target_idx ON relationships (target_id);
CREATE INDEX relationships_type_idx ON relationships (relationship_type);

CREATE TABLE claims (
    id TEXT PRIMARY KEY,
    subject_id TEXT,
    object_id TEXT,
    data JSONB NOT NULL
);
CREATE INDEX claims_subject_idx ON claims (subject_id);
CREATE INDEX claims_object_idx ON claims (object_id);

CREATE TABLE chunks (
    id TEXT PRIMARY KEY,
    entity_ids TEXT[] NOT NULL,
    chunk_type TEXT NOT NULL,
    text TEXT NOT NULL,
    embedding vector,          -- sem dimensão fixa até ensure_vector_ready() detectar
    data JSONB NOT NULL
);
CREATE INDEX chunks_entity_ids_idx ON chunks USING gin (entity_ids);

CREATE TABLE ingestion_runs (
    id TEXT PRIMARY KEY,
    civilization_id TEXT NOT NULL,
    data JSONB NOT NULL
);
```

Todo o SQL vive em `app/persistence/schema.py` (DDL), `app/persistence/repositories.py` (CRUD) e `app/persistence/vector.py` (coluna de embedding).

## Idempotência

Todo upsert é `INSERT ... ON CONFLICT (id) DO UPDATE SET ...` sobre o `id` determinístico — o equivalente direto do `MERGE` por id que a versão Neo4j usava. Nenhuma tabela usa `ON CONFLICT` sobre `(source_id, type, target_id)`; o `id` já é derivado desse triplo (`stable_relationship_id`), então conflito por `id` já cobre o caso.

## Vector column (`chunks.embedding`)

pgvector exige dimensão fixa (`vector(n)`) para indexar, mas permite uma coluna `vector` sem dimensão declarada. `app/persistence/vector.py::ensure_vector_ready`:

1. Detecta a dimensão do modelo de embedding em uso (`get_or_detect_dimension` — embeda uma string de teste, cacheia `len(vetor)`; override via `EMBEDDING_DIMENSIONS` no `.env`).
2. Na primeira vez, `ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(N)` + `CREATE INDEX ... USING hnsw (embedding vector_cosine_ops)`.
3. Se a coluna já tiver uma dimensão diferente da detectada, falha com erro explícito (mesma filosofia "fail loud" da versão Neo4j) — normalmente significa que `OLLAMA_EMBEDDING_MODEL`/`OPENAI_EMBEDDING_MODEL` mudou depois que dados já foram ingeridos.

Antes do `ALTER`, buscas por similaridade ainda funcionam via sequential scan (`ORDER BY embedding <=> $1`) — só não há índice ANN ainda. Sem otimização prematura: aceitável no volume desta etapa.

## Travessia multi-hop: `WITH RECURSIVE`

`RelationshipRepository.find_connected(start_id, max_hops)` — o bloco de construção para a exploração cross-civilização (seção 28 da spec original: `Assyria → Judah → Babylon → Persia → Greece`). Não está conectado ao pipeline de ingestão ainda (isso é uma feature de consulta futura, fora do escopo desta etapa — ver `spec/01`), mas já existe e é testado (`tests/test_workflow.py::test_relationship_traversal_with_recursive_cte`, `@pytest.mark.integration`):

```sql
WITH RECURSIVE traversal(id, path, depth) AS (
    SELECT $1::text, ARRAY[$1::text], 0
    UNION ALL
    SELECT
        next_id,
        t.path || next_id,
        t.depth + 1
    FROM traversal t
    JOIN relationships r ON r.source_id = t.id OR r.target_id = t.id
    CROSS JOIN LATERAL (
        SELECT CASE WHEN r.source_id = t.id THEN r.target_id ELSE r.source_id END AS next_id
    ) hop
    WHERE t.depth < $2
      AND NOT (hop.next_id = ANY(t.path))
)
SELECT DISTINCT id, path, depth FROM traversal WHERE depth > 0 ORDER BY depth, id
```

Deliberadamente simples (não otimizado): re-percorre `relationships` a cada passo da recursão, sem tuning de query plan — aceitável por decisão explícita do projeto. Proteção contra ciclo via `NOT (next_id = ANY(path))`. Não-direcionado (segue tanto `source_id` quanto `target_id`) porque a pergunta "como X se conecta com Y" não deve se importar com a direção da aresta.

## Nota sobre `neo4j-graphrag-python`

A spec original (Neo4j) documentava compatibilidade futura com o pacote `neo4j-graphrag-python`. Isso não se aplica mais — com Postgres, o caminho natural para GraphRAG futuro é `pgvector` para busca vetorial combinado com `find_connected`/CTEs recursivas para travessia, sem um pacote equivalente dedicado. Deixado como nota para quando essa fase for implementada.
