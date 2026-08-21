# 02 — Domain Model Spec

## Diagrama conceitual

```
(Civilization)──[:HAS_PERIOD]──(Period)
(Person)──[:PARTICIPATED_IN]──(Event)──[:OCCURRED_AT]──(Place)
(Person)──[:KING_OF {start_year,end_year}]──(Polity)
(Polity)──[:LOCATED_IN]──(Place)
(Person)──[:SUBJECT_OF]──(Claim)──[:ABOUT]──(Event|Person|Polity)
(Chunk)──[:DESCRIBES]──(Person|Event|Place|Polity|Document|Concept|Civilization)
```

`Relationship` (aresta tipada) e `Claim` (nó de proveniência textual) coexistem e servem propósitos diferentes:

- **Relationship**: aresta de vocabulário controlado, criada sempre que a extração está confiante o bastante para normalizar a afirmação em um triplo (`source -[TYPE]-> target`). É o que sustenta travessias de grafo eficientes.
- **Claim**: nó que carrega o texto completo de uma afirmação (`statement`), sua data estimada e confiança. Pode ou não corresponder 1:1 a uma Relationship — permite representar interpretações concorrentes/disputadas sobre o mesmo par de entidades sem forçar uma única aresta "verdadeira".

## Metadados obrigatórios

Todo registro gerado por LLM (entidades, eventos, relações, claims, chunks) carrega:

| Campo | Tipo | Default |
|---|---|---|
| `origin` | `str` | `"llm_generated"` |
| `verification_status` | `str` | `"unverified"` |
| `generated_by_model` | `str \| None` | nome do modelo que gerou o registro |
| `confidence` | `float \| None` | confiança declarada pela extração |
| `created_at` / `updated_at` | `datetime` | timestamp da persistência |
| `ingestion_run_id` | `str` | id do `IngestionRun` que produziu/atualizou o registro |

## `EntityType` vs `EventType`

A spec original listava tipos de evento (`BATTLE`, `WAR`, `MIGRATION`, `TREATY`, `CONQUEST`, `FOUNDATION`, `DESTRUCTION`) dentro de `EntityType`, o que contradiz a separação Entity/Event do glossário (01). Correção: dois enums separados.

```python
class EntityType(str, Enum):
    CIVILIZATION = "CIVILIZATION"
    POLITY = "POLITY"
    EMPIRE = "EMPIRE"
    KINGDOM = "KINGDOM"
    DYNASTY = "DYNASTY"
    PERSON = "PERSON"
    PLACE = "PLACE"
    CITY = "CITY"
    REGION = "REGION"
    DOCUMENT = "DOCUMENT"
    TEXT = "TEXT"
    INSCRIPTION = "INSCRIPTION"
    RELIGION = "RELIGION"
    DEITY = "DEITY"
    CULTURE = "CULTURE"
    LANGUAGE = "LANGUAGE"
    CONCEPT = "CONCEPT"

class EventType(str, Enum):
    GENERIC = "GENERIC"
    BATTLE = "BATTLE"
    WAR = "WAR"
    MIGRATION = "MIGRATION"
    TREATY = "TREATY"
    CONQUEST = "CONQUEST"
    FOUNDATION = "FOUNDATION"
    DESTRUCTION = "DESTRUCTION"
```

## `HistoricalEntity`: base + 6 subclasses concretas

Um único modelo genérico com todos os campos opcionais perderia segurança de tipo (nada garante que `person.birth_date` existe); 23 subclasses (uma por valor de `EntityType`) seria over-engineering, já que `KINGDOM`/`EMPIRE`/`DYNASTY` não têm campos estruturalmente distintos entre si — só o rótulo muda. Solução intermediária: base + 6 subclasses cobrindo toda a variação estrutural real.

```python
class HistoricalEntity(BaseModel):
    id: str
    entity_type: EntityType
    canonical_name: str
    aliases: list[str] = []
    summary: str | None = None
    origin: str = "llm_generated"
    verification_status: str = "unverified"
    generated_by_model: str | None = None
    confidence: float | None = None
    created_at: datetime
    updated_at: datetime

class Civilization(HistoricalEntity):
    entity_type: Literal[EntityType.CIVILIZATION] = EntityType.CIVILIZATION
    start_year: int | None = None
    end_year: int | None = None

class Person(HistoricalEntity):
    entity_type: Literal[EntityType.PERSON] = EntityType.PERSON
    birth_date: HistoricalDate | None = None
    death_date: HistoricalDate | None = None
    titles: list[str] = []

class Place(HistoricalEntity):
    entity_type: Literal[EntityType.PLACE, EntityType.CITY, EntityType.REGION]
    latitude: float | None = None
    longitude: float | None = None
    modern_country: str | None = None
    ancient_region: str | None = None
    coordinate_origin: str | None = None  # "llm_generated" when the LLM guessed lat/long

class Polity(HistoricalEntity):
    entity_type: Literal[EntityType.POLITY, EntityType.EMPIRE, EntityType.KINGDOM, EntityType.DYNASTY]
    start_year: int | None = None
    end_year: int | None = None

class Document(HistoricalEntity):
    entity_type: Literal[EntityType.DOCUMENT, EntityType.TEXT, EntityType.INSCRIPTION]

class Concept(HistoricalEntity):
    entity_type: Literal[EntityType.RELIGION, EntityType.DEITY, EntityType.CULTURE, EntityType.LANGUAGE, EntityType.CONCEPT]

AnyEntity = Annotated[
    Civilization | Person | Place | Polity | Document | Concept,
    Discriminator(entity_type_discriminator),
]
```

`Polity` mapeia 4 valores de `EntityType` para 1 classe (many-to-one) — o discriminador de campo padrão do Pydantic v2 assume 1:1, então o union usa um **discriminador callable** (`entity_type_discriminator(value) -> str`, mapeando cada `EntityType` para a chave de subclasse correta).

## `HistoricalDate`

```python
class DatePrecision(str, Enum):
    EXACT = "exact"
    APPROXIMATE = "approximate"
    RANGE = "range"
    BEFORE = "before"
    AFTER = "after"
    UNKNOWN = "unknown"
    DISPUTED = "disputed"

class HistoricalDate(BaseModel):
    earliest_year: int | None = None
    latest_year: int | None = None
    estimated_year: int | None = None
    precision: DatePrecision
    confidence: float | None = None

    @model_validator(mode="after")
    def check_range(self) -> "HistoricalDate":
        if self.earliest_year is not None and self.latest_year is not None:
            assert self.earliest_year <= self.latest_year
        return self
```

Anos negativos = BCE (`701 BCE = -701`, `70 CE = 70`).

## `HistoricalEvent`, `HistoricalRelationship`, `HistoricalClaim`, `KnowledgeChunk`

Exatamente como especificado pelo usuário (ver `03-architecture-spec.md` para os campos completos e `05-llm-integration-spec.md` para os contratos de extração). `RelationshipType` é um enum de vocabulário controlado (`KING_OF`, `RULED`, `MEMBER_OF_DYNASTY`, `FATHER_OF`, `MOTHER_OF`, `CHILD_OF`, `MARRIED_TO`, `ALLY_OF`, `ENEMY_OF`, `CONQUERED`, `ATTACKED`, `BESIEGED`, `DEFEATED`, `PARTICIPATED_IN`, `COMMANDER_IN`, `FOUNDED`, `DESTROYED`, `LOCATED_IN`, `OCCURRED_AT`, `PRECEDED_BY`, `SUCCEEDED_BY`, `CONTEMPORARY_OF`, `MENTIONED_IN`, `DESCRIBED_BY`, `INFLUENCED`, `RELATED_TO`).

## IDs estáveis

```python
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "chronos.ingestion")

def stable_entity_id(entity_type: EntityType, canonical_name: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{entity_type.value}:{slugify(canonical_name)}"))

def stable_relationship_id(source_id: str, relationship_type: str, target_id: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{source_id}:{relationship_type}:{target_id}"))

def stable_claim_id(subject_id: str | None, predicate: str, object_id: str | None, statement: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{subject_id}:{predicate}:{object_id}:{statement}"))
```

`stable_claim_id` inclui o **texto completo** da `statement`, não só o triplo — evita colapsar afirmações textualmente distintas (e potencialmente conflitantes/disputadas) sobre o mesmo par de entidades. Trade-off aceito: reruns em que o LLM formula a frase de forma ligeiramente diferente podem acumular quase-duplicatas (ver `06-acceptance-tests-spec.md`, limitações conhecidas).

IDs estáveis (determinísticos) são o que viabiliza `MERGE` idempotente no Neo4j: rodar a mesma ingestão duas vezes converge para o mesmo `id`, nunca cria um nó novo.
