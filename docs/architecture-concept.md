# Архитектурная концепция Web Access MCP

## Статус документа

Этот документ продолжает `docs/project-concept.md` и фиксирует предполагаемую **структуру проекта, границы модулей, process boundaries и направление зависимостей**.

Это всё ещё не полноценный design document. Точные классы, schemas, database tables, Redis-протоколы, endpoints, MCP tools и version roadmap будут определяться позднее по отдельным компонентам.

---

## 1. Главный принцип структуры

Структура проекта должна отражать не список библиотек, а **границы ответственности**.

Базовое направление зависимостей:

```text
transport
   ↓
application
   ↓
domain

infrastructure
   ↑ implements ports required by application

bootstrap
   → связывает конкретные реализации
```

Не следует превращать проект в формальную Clean Architecture с большим количеством искусственных слоёв. Нужны только те границы, которые реально защищают application logic от transport и infrastructure деталей.

---

## 2. Предлагаемый repository layout

```text
web-access-mcp-server/
│
├── src/
│   └── web_access/
│       ├── core/
│       ├── domain/
│       ├── application/
│       ├── transport/
│       ├── infrastructure/
│       ├── workers/
│       ├── bootstrap/
│       └── entrypoints/
│
├── alembic/
├── tests/
├── docs/
├── deploy/
├── scripts/
├── pyproject.toml
├── docker-compose.yml
└── README.md
```

Предпочтителен `src`-layout, чтобы import behavior в development и installed environment совпадал.

---

## 3. `domain/`

`domain/` содержит только устойчивые предметные понятия и invariants.

Предварительная структура:

```text
domain/
├── search/
├── retrieval/
├── content/
├── browser/
└── jobs/
```

Здесь могут жить сущности и value objects вроде:

```text
SearchQuery
SearchResult
RetrievedResource
ContentObject
ContentRepresentation
BrowserSession
BrowserSessionState
BrowserActionResult
Job
JobState
```

Здесь не должны находиться:

- SQLAlchemy models;
- FastAPI requests;
- FastMCP schemas;
- HTTPX responses;
- Redis keys;
- Playwright `Page`/`BrowserContext`;
- SearXNG/Yandex-specific payloads.

---

## 4. `application/`

`application/` является основным прикладным слоем проекта.

Предварительная структура:

```text
application/
├── common/
│   ├── context.py
│   ├── results.py
│   └── errors.py
│
├── search/
│   ├── service.py
│   ├── contracts.py
│   └── ports.py
│
├── retrieval/
│   ├── service.py
│   ├── contracts.py
│   └── ports.py
│
├── content/
│   ├── service.py
│   ├── contracts.py
│   ├── inspection.py
│   ├── representations.py
│   └── ports.py
│
├── browser/
│   ├── service.py
│   ├── lifecycle.py
│   ├── contracts.py
│   └── ports.py
│
└── jobs/
    ├── service.py
    ├── lifecycle.py
    ├── contracts.py
    └── ports.py
```

Точные имена файлов могут измениться после детального проектирования.

Application layer определяет use cases и необходимые ему ports. Он не должен импортировать FastAPI router, FastMCP tool или конкретный provider client.

### Почему ports располагаются рядом с владельцем

Port принадлежит модулю, которому он нужен.

Например Search может объявлять:

```text
SearchProvider
SearchCache
```

Browser:

```text
BrowserWorkerClient
BrowserSessionRepository
```

Content:

```text
ContentStore
ContentInspector
NativeContentParser
```

Так dependency contract остаётся рядом с application use case и не возникает глобальной папки `ports/`, превращающейся в свалку интерфейсов.

---

## 5. `Content` как единая предметная область

Отдельного верхнеуровневого bounded context `Extraction` не предполагается.

`Content` владеет:

```text
Identification
Inspection (L0)
Native Parsing (L1)
Representation management
Storage
Provenance
```

Advanced Processing (L2) находится за границей Web Access.

Это означает, что структура может развиваться примерно так:

```text
application/content/
    service.py
    inspection.py
    representations.py
    ports.py

infrastructure/content/
    identification/
    parsers/
    storage/
```

### Native parsers

Infrastructure может содержать registry прямых parsers:

```text
infrastructure/content/parsers/
├── registry.py
├── html.py
├── text.py
├── json.py
├── xml.py
├── csv.py
├── pdf.py
├── docx.py
├── xlsx.py
├── pptx.py
├── epub.py
└── ...
```

Поддержка нового формата не должна автоматически требовать изменений MCP/REST surface.

### Representation graph

Исходный объект и производные представления должны иметь явное происхождение:

```text
raw PDF
├── native text
├── native metadata
└── external OCR result, если позднее создан другим processor
```

или:

```text
raw HTML
├── native text/Markdown
├── metadata
└── links/structured data
```

Web Access не обязан самостоятельно создавать L2-представления, но архитектура Content должна позволять сохранить полученный извне derived result с provenance.

---

## 6. `infrastructure/`

Infrastructure реализует ports application layer и содержит конкретные библиотеки/интеграции.

Предварительная структура:

```text
infrastructure/
├── database/
│   ├── session.py
│   ├── models/
│   └── repositories/
│
├── redis/
│   ├── client.py
│   ├── cache/
│   ├── locks/
│   └── leases/
│
├── search/
│   ├── searxng.py
│   └── yandex.py
│
├── retrieval/
│   ├── httpx_fetcher.py
│   ├── url_policy.py
│   ├── dns.py
│   └── mime.py
│
├── content/
│   ├── identification/
│   ├── parsers/
│   └── storage/
│
├── jobs/
│   └── arq.py
│
└── observability/
    ├── metrics.py
    └── tracing.py
```

Здесь допустимы зависимости от HTTPX, SQLAlchemy, asyncpg, Redis, arq, Trafilatura, pypdf и конкретных provider SDK/API.

---

## 7. Browser runtime как отдельная runtime-граница

Playwright отличается от обычной infrastructure library: он владеет долгоживущим state.

Поэтому browser execution лучше выделить отдельно:

```text
workers/
├── jobs/
│   ├── worker.py
│   └── tasks.py
│
└── browser/
    ├── worker.py
    ├── runtime.py
    ├── sessions.py
    ├── actions.py
    ├── snapshots.py
    ├── downloads.py
    └── playwright.py
```

`BrowserApplicationService` не должен напрямую владеть `BrowserContext` или `Page`.

Концептуальный flow:

```text
BrowserApplicationService
        ↓
BrowserWorkerClient port
        ↓
worker routing implementation
        ↓
BrowserWorker
        ↓
Playwright / Chromium
```

Фактический transport между control plane и browser worker будет выбран отдельным техническим решением.

---

## 8. Три основных runtime-а

Один репозиторий предполагает как минимум три независимо запускаемых runtime-а.

### 8.1 Control plane

```text
web-access-api
```

Владеет:

- FastAPI;
- FastMCP;
- REST transport;
- MCP transport;
- application services;
- обычными request-bound operations;
- orchestration к infrastructure adapters и workers.

REST и MCP могут работать в одном process и одном application lifespan.

### 8.2 Durable job worker

```text
web-access-worker
```

Предназначен для действительно долгих/фоновых операций:

- crawl;
- большие batch operations;
- фоновые Web Access workflows;
- другие durable jobs.

Его lifecycle основан на PostgreSQL + Redis/arq модели.

### 8.3 Browser worker

```text
web-access-browser-worker
```

Имеет другой lifecycle:

```text
worker startup
→ Playwright/Chromium startup
→ BrowserSession ownership
→ ordered actions
→ TTL/reaper cleanup
→ graceful shutdown
```

Его нельзя механически объединять с arq worker, поскольку stateful BrowserSession принадлежит конкретному живому worker-у.

---

## 9. `transport/`

REST и MCP являются разными фасадами одного application backend.

Предварительно:

```text
transport/
├── rest/
│   ├── app.py
│   ├── dependencies.py
│   ├── errors.py
│   ├── schemas/
│   ├── mappers/
│   └── routers/
│
└── mcp/
    ├── server.py
    ├── errors.py
    ├── annotations.py
    ├── schemas/
    ├── serializers/
    └── tools/
```

### Transport schemas не равны application contracts

Нормально иметь:

```text
REST SearchRequest ─┐
                    ├→ mapper → application SearchRequest
MCP WebSearchInput ─┘
                              ↓
                    SearchApplicationService
```

REST может быть богаче и технически подробнее.

MCP должен оставаться компактным agent-facing интерфейсом с русскоязычными descriptions.

---

## 10. Structured hints в result contracts

Application result может содержать **структурированные подсказки** о разумных следующих шагах.

Это не orchestration engine и не автоматический fallback.

Подсказки должны строиться на наблюдаемом результате и diagnostics.

Концептуально клиент должен иметь возможность различить:

```text
фактический результат
warnings/diagnostics
recommendations/hints
```

Пример смыслового результата:

```text
Retrieval succeeded
Content identified as HTML
Native Parsing produced no useful text
Hint: browser capability may provide rendered page state
```

Другой пример:

```text
Content identified as PDF
No accessible text layer detected
Hint: further reading may require OCR/document-processing capability outside native Web Access parsing
```

### Приоритет рекомендаций

1. Если подходящий следующий шаг является capability самого Web Access — подсказка может быть конкретной.
2. Если следующий шаг требует внешней системы — подсказка должна описывать требуемый класс capability, а не предполагать конкретный установленный инструмент.
3. Search не должен рекомендовать смену provider-а только потому, что выдача кажется «маленькой»: это уже предметное решение клиента, если нет объективной provider-level ошибки или ограничения.

Подсказка никогда не должна автоматически запускать рекомендуемую операцию.

---

## 11. `bootstrap/`

Composition root должен быть явным.

Предварительно:

```text
bootstrap/
├── container.py
├── lifespan.py
└── wiring.py
```

Здесь связываются abstractions и implementations:

```text
SearchProvider → SearXNGProvider
SearchCache → Redis cache adapter
ContentStore → FilesystemContentStore или S3CompatibleContentStore
BrowserWorkerClient → выбранный worker transport adapter
Repositories → SQLAlchemy implementations
```

Application service не должен создавать собственный SQLAlchemy engine, Redis pool или HTTPX client.

---

## 12. `entrypoints/`

Entrypoints должны быть максимально тонкими:

```text
entrypoints/
├── api.py
├── job_worker.py
└── browser_worker.py
```

Их ответственность:

```text
load config
→ build dependencies
→ start corresponding runtime
→ shutdown cleanly
```

Бизнес-логика в entrypoints не размещается.

---

## 13. `core/`

`core/` содержит только действительно сквозную техническую основу, например:

```text
core/
├── config.py
├── logging.py
├── ids.py
└── time.py
```

Нельзя превращать `core/` в свалку `utils.py`, `helpers.py`, `misc.py` или предметной логики.

---

## 14. Execution paths

### Request-bound

Короткие операции выполняются непосредственно в control plane или через owning browser worker:

```text
search
retrieval
content inspection/native parsing
content read
browser action
```

Они могут логироваться и иметь audit metadata, но не обязаны создавать durable job.

### Durable

Длительные операции используют job runtime:

```text
client
→ application job creation
→ PostgreSQL authoritative state
→ Redis/arq
→ job worker
→ persisted events/result
```

Выбор между request-bound и durable execution должен определяться семантикой операции, а не скрытой эвристикой вроде размера ответа.

---

## 15. PostgreSQL и Redis не являются центром domain architecture

PostgreSQL и Redis проходят поперёк системы как infrastructure.

PostgreSQL используется для durable structured state.

Redis — для тех координационных задач, где это оправдано: cache, rate limiting, locks, queues, leases, routing metadata и потенциально event coordination.

Нельзя строить application contracts вокруг Redis keys или SQLAlchemy models.

---

## 16. Масштабирование

Архитектура должна позволять независимо масштабировать:

```text
API/MCP replicas
job workers
browser workers
SearXNG
PostgreSQL
Redis
ContentStore backend
```

Stateful BrowserSession маршрутизируется к worker-у, который фактически владеет её живым state.

Падение API replica не должно автоматически означать потерю BrowserSession.

Падение owning browser worker, напротив, может перевести принадлежащую ему session в `lost`; это должно быть явно представлено в lifecycle, а не скрыто под transport retry.

---

## 17. Testing structure

Предварительно:

```text
tests/
├── unit/
├── contract/
├── integration/
├── e2e/
└── load/
```

Особенно важны contract tests для:

- application ports;
- фактических MCP schemas, которые увидит клиент;
- REST schemas;
- content format identification;
- native parser contracts;
- browser session lifecycle;
- worker crash/restart;
- storage backends;
- PostgreSQL/Redis failure modes.

---

## 18. Полная ориентировочная структура

```text
web-access-mcp-server/
│
├── src/
│   └── web_access/
│       ├── core/
│       │   ├── config.py
│       │   ├── logging.py
│       │   ├── ids.py
│       │   └── time.py
│       │
│       ├── domain/
│       │   ├── search/
│       │   ├── retrieval/
│       │   ├── content/
│       │   ├── browser/
│       │   └── jobs/
│       │
│       ├── application/
│       │   ├── common/
│       │   ├── search/
│       │   ├── retrieval/
│       │   ├── content/
│       │   ├── browser/
│       │   └── jobs/
│       │
│       ├── transport/
│       │   ├── rest/
│       │   │   ├── routers/
│       │   │   ├── schemas/
│       │   │   └── mappers/
│       │   └── mcp/
│       │       ├── tools/
│       │       ├── schemas/
│       │       ├── serializers/
│       │       └── annotations.py
│       │
│       ├── infrastructure/
│       │   ├── database/
│       │   │   ├── models/
│       │   │   └── repositories/
│       │   ├── redis/
│       │   ├── search/
│       │   ├── retrieval/
│       │   ├── content/
│       │   │   ├── identification/
│       │   │   ├── parsers/
│       │   │   └── storage/
│       │   ├── jobs/
│       │   └── observability/
│       │
│       ├── workers/
│       │   ├── jobs/
│       │   └── browser/
│       │
│       ├── bootstrap/
│       │   ├── container.py
│       │   ├── lifespan.py
│       │   └── wiring.py
│       │
│       └── entrypoints/
│           ├── api.py
│           ├── job_worker.py
│           └── browser_worker.py
│
├── alembic/
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   ├── e2e/
│   └── load/
│
├── docs/
│   ├── project-concept.md
│   ├── architecture-concept.md
│   └── design/
│
├── deploy/
├── scripts/
├── pyproject.toml
├── docker-compose.yml
└── README.md
```

---

## 19. Открытые архитектурные вопросы

До полноценного design document остаётся отдельно решить как минимум:

1. Точный backend contract Search.
2. Точный Retrieval contract и security pipeline.
3. Каноническую модель `ContentObject` и representation/provenance graph.
4. Какие форматы относятся к поддерживаемому Native Parsing L1.
5. Внутренний transport control plane ↔ browser worker.
6. BrowserSession lifecycle, routing, leases и failure semantics.
7. Что является обычной Operation, а что Durable Job.
8. Persistence model PostgreSQL.
9. Точное назначение Redis по подсистемам.
10. Полный failure/error contract.
11. Security model и service authentication.
12. Observability contracts.
13. REST facade.
14. MCP facade и его agent-facing schemas.
15. Version roadmap и release gates.

Эти вопросы должны прорабатываться последовательно, а не решаться одним большим implementation patch.
