# Правила зависимостей Web Access MCP

## Статус документа

Этот документ является каноническим владельцем **направления зависимостей, module boundaries и правил взаимодействия слоёв** проекта.

Он задаёт ограничения, которые должны соблюдаться кодом, component design и version implementation plans.

Цель — не реализовать формальную Clean Architecture, а защитить application logic от transport/infrastructure связанности и сохранить возможность независимого масштабирования компонентов.

---

## 1. Базовое направление зависимостей

Каноническая схема:

```text
transport
   ↓
application
   ↓
domain

infrastructure
   ↑ implements ports required by application

workers
   → исполняют runtime-specific contracts

bootstrap
   → связывает concrete implementations

entrypoints
   → запускают собранные runtimes
```

Внешние framework/library details должны находиться на краях системы.

---

## 2. Предлагаемый package layout

```text
src/web_access/
├── core/
├── domain/
├── application/
├── transport/
│   ├── rest/
│   └── mcp/
├── infrastructure/
├── workers/
│   ├── jobs/
│   └── browser/
├── bootstrap/
└── entrypoints/
```

Фактическая структура может уточняться, но направление зависимостей должно сохраняться.

---

# 3. `domain/`

## 3.1. Ответственность

`domain/` содержит устойчивые предметные понятия и invariants:

- value objects;
- enums/state machines;
- domain entities, если они действительно нужны;
- простые pure transformations/invariants.

Предварительные области:

```text
domain/search/
domain/retrieval/
domain/content/
domain/browser/
domain/jobs/
```

## 3.2. Разрешённые зависимости

`domain/` может зависеть только от:

- Python standard library;
- минимального `core/`, если это действительно сквозной стабильный primitive и не создаёт обратную связанность.

## 3.3. Запрещённые зависимости

`domain/` не должен импортировать:

- `application/`;
- `transport/`;
- `infrastructure/`;
- `workers/`;
- `bootstrap/`;
- `entrypoints/`;
- FastAPI/FastMCP;
- SQLAlchemy/asyncpg;
- Redis/arq;
- HTTPX;
- Playwright;
- SearXNG/Yandex client implementation;
- filesystem/S3 implementation.

Domain model не является ORM model или transport schema.

---

# 4. `application/`

## 4.1. Ответственность

`application/` является владельцем use cases и application contracts.

Он определяет:

- application services;
- operation inputs/outputs;
- execution semantics;
- ports;
- orchestration между domain capabilities;
- application error/result model;
- lifecycle application resources;
- policy boundaries, не завязанные на конкретный framework.

## 4.2. Разрешённые зависимости

`application/` может зависеть от:

- `domain/`;
- `core/`;
- standard library;
- lightweight typing/schema primitives, если отдельное техническое решение разрешит их использование без утечки transport semantics.

## 4.3. Запрещённые зависимости

Application logic не должна напрямую импортировать:

- FastAPI routers/request/response;
- FastMCP Context/tool decorators;
- SQLAlchemy models/session;
- Redis client;
- arq worker/job context;
- HTTPX client implementation;
- Playwright objects;
- S3/filesystem concrete storage;
- provider-specific SDKs.

Если application layer нуждается во внешней capability, он объявляет port.

---

# 5. Ports принадлежат потребителю

Port определяется в application-модуле, который использует capability.

Пример:

```text
application/search/ports.py
    SearchProvider
    SearchCache (если отдельный port действительно нужен)

application/retrieval/ports.py
    HttpFetcher
    UrlSafetyPolicy / resolver boundary

application/content/ports.py
    ContentStore
    NativeParser / ParserRegistry contract

application/browser/ports.py
    BrowserWorkerClient
    BrowserSessionRepository

application/jobs/ports.py
    JobRepository
    JobQueue
```

Не следует создавать глобальный `ports/` как свалку interfaces без ясного владельца.

Cross-cutting port допускается только если capability действительно используется несколькими application areas с одинаковой семантикой.

---

# 6. `infrastructure/`

## 6.1. Ответственность

`infrastructure/` реализует ports и содержит конкретные integrations.

Предварительные категории:

```text
infrastructure/database/
infrastructure/redis/
infrastructure/search/
infrastructure/retrieval/
infrastructure/content/
infrastructure/jobs/
infrastructure/observability/
```

## 6.2. Разрешённые зависимости

Infrastructure adapters могут зависеть от:

- соответствующих application ports/contracts;
- domain models/value objects;
- `core/`;
- конкретных libraries/SDKs.

## 6.3. Запрещённое направление

Application/domain не должны импортировать concrete infrastructure adapters.

Например запрещено:

```python
# application/search/service.py
from web_access.infrastructure.search.searxng import SearXNGProvider
```

Вместо этого concrete adapter передаётся через bootstrap/composition root.

---

# 7. Database model не является domain model

SQLAlchemy models принадлежат `infrastructure/database/models/`.

Repositories обязаны выполнять явное mapping между:

```text
SQLAlchemy persistence representation
↔ application/domain representation
```

Запрещено передавать ORM object напрямую:

- в REST response;
- в MCP result;
- в Browser Worker protocol;
- в domain/application API как публичный contract.

Database schema может оптимизироваться независимо от transport schemas.

---

# 8. `transport/`

## 8.1. Ответственность

Transport является внешним facade application capabilities.

```text
transport/rest/
transport/mcp/
```

Он отвечает за:

- transport schemas;
- transport-specific validation;
- authentication/principal extraction;
- mapping в application contract;
- mapping application result/error обратно в transport representation;
- protocol-specific metadata.

## 8.2. Разрешённые зависимости

Transport может зависеть от:

- application services/contracts;
- domain enums/value objects, если это действительно удобно и не раскрывает внутреннюю модель;
- `core/`;
- transport framework.

## 8.3. Запрещённые зависимости

Transport не должен напрямую:

- вызывать SQLAlchemy repositories;
- обращаться к Redis для бизнес-операции;
- создавать HTTPX search/fetch clients;
- работать с Playwright;
- выполнять native parsing;
- реализовывать retry/fallback business logic;
- самостоятельно управлять BrowserSession lifecycle.

Transport вызывает application operation.

---

# 9. REST и MCP не вызывают друг друга

Запрещены конструкции:

```text
MCP tool → HTTP request к собственному REST API
REST endpoint → internal MCP call
```

Оба facade должны вызывать общий application layer напрямую.

Исключение возможно только как отдельное deployment/integration решение вне основного in-process composition и требует ADR.

---

# 10. REST schema, MCP schema и application contract различаются

Допускается и ожидается:

```text
REST SearchRequest
        ↓ mapper
Application SearchRequest
        ↑ mapper
MCP WebSearchInput
```

Нельзя автоматически переиспользовать transport schema как application/domain model только ради уменьшения количества классов.

Reuse допускается лишь если семантика действительно полностью совпадает и не создаёт transport coupling.

---

# 11. `workers/`

Workers являются отдельными runtime executors, а не application layer.

В проекте как минимум различаются:

```text
workers/jobs/
workers/browser/
```

Их lifecycle и ownership semantics различаются.

---

# 12. Job Worker

Job Worker исполняет durable/background work.

Он может:

- получать job envelope из queue;
- восстанавливать application execution context;
- вызывать application service/handler;
- сохранять durable result/state через ports;
- публиковать events/metrics.

Job Worker не должен содержать отдельную копию application business logic.

Arq-specific context не должен протекать в application contracts.

---

# 13. Browser Worker

Browser Worker владеет live Playwright state.

Только внутри browser worker могут существовать:

- `Browser`;
- `BrowserContext`;
- `Page`;
- `Locator`;
- связанные live runtime objects.

Browser Worker выполняет runtime-specific action protocol, но не является владельцем общей agent/application orchestration.

Он не должен самостоятельно решать:

- какой URL искать;
- нужно ли переключиться на Search;
- нужно ли запускать OCR;
- какое следующее смысловое действие должен выполнить агент.

---

# 14. Control plane не хранит authoritative live browser state

API/MCP process не должен считать process-local mapping вида:

```text
browser_session_id → Playwright BrowserContext
```

authoritative state архитектуры.

Любой API instance должен в целевой горизонтально масштабируемой topology иметь возможность определить owning browser worker через routing/coordination contract.

Точный механизм маршрутизации проектируется отдельно.

---

# 15. BrowserApplicationService и BrowserWorker разделены

`BrowserApplicationService` отвечает за application semantics:

- validation ownership/policy;
- lifecycle orchestration;
- session state transitions на application уровне;
- routing request через `BrowserWorkerClient` port;
- normalization результата/error;
- persistence metadata;
- cleanup policy invocation.

Browser Worker отвечает за фактическое выполнение Playwright action.

Application service не должен импортировать Playwright.

---

# 16. Search не вызывает Retrieval автоматически

`SearchApplicationService` возвращает поисковую выдачу.

Запрещён скрытый flow:

```text
Search
→ автоматически открыть top results
→ Retrieval
→ Browser
```

Если composed operation понадобится позднее, она должна иметь отдельную явную application semantics, а не скрываться внутри Search.

---

# 17. Retrieval не вызывает Browser автоматически

`RetrievalApplicationService` получает известный HTTP(S)-ресурс.

Если результат — минимальный JS shell или другой материал, который может потребовать browser rendering, Retrieval/Content может вернуть structured hint.

Запрещено:

```text
Retrieval failure/poor content
→ hidden Browser fallback
```

Browser запускается отдельной explicit capability.

---

# 18. Content не запускает L2 автоматически

Content может выполнять:

- L0 Inspection;
- L1 Native Parsing;
- representation/storage operations.

Если Native Parser отсутствует или native text недоступен, Content возвращает diagnostics/hints.

Запрещён автоматический переход к:

- OCR;
- VLM;
- LibreOffice conversion;
- transcription;
- другому L2 processor.

---

# 19. Browser может производить Content, но не владеть ContentStore policy

Browser subsystem может создавать:

- rendered HTML;
- screenshot;
- download;
- export.

Но сохранение крупного результата должно происходить через Content application/port contract, а не через случайную запись browser worker в внутренний filesystem path, который затем протекает клиенту.

Публичный результат должен использовать ContentObject/handle abstraction.

---

# 20. Retrieval может производить raw Content

Полученный HTTP resource может быть сохранён как raw ContentObject через ContentStore/application contract.

Retrieval не должен самостоятельно определять storage implementation.

Не должно быть зависимости:

```text
Retrieval service → конкретный local filesystem path
```

---

# 21. Content parser registry является расширяемой границей

Поддержка форматов не должна реализовываться одним монолитным `if extension == ...`.

Content subsystem должен иметь registry/dispatch contract для Native Parsers.

Определение parser должно опираться на идентифицированный content format/media characteristics, а не только URL suffix.

Добавление нового Native Parser не должно требовать изменений REST/MCP facade, если application contract representation остаётся прежним.

---

# 22. Provider adapters изолированы

Search provider adapter отвечает за mapping:

```text
application Search request
↔ provider protocol
↔ normalized Search result
```

Provider adapter не должен:

- самостоятельно вызывать другой provider по reasoning-эвристике;
- менять application-level provider policy;
- генерировать agent-facing текст как canonical contract.

---

# 23. Cache располагается за application/infrastructure boundary

Application contract определяет семантику freshness/caching настолько, насколько она видима клиенту.

Concrete Redis/in-memory cache implementation принадлежит infrastructure.

Нельзя позволять cache adapter тихо менять смысл результата, например возвращать неограниченно старые данные без отражённой policy/freshness metadata.

---

# 24. PostgreSQL, Redis и ContentStore имеют разные роли

Каноническое направление:

```text
PostgreSQL
→ durable structured metadata / lifecycle / source of truth там, где это требуется

Redis
→ cache / queue / coordination / locks / leases / routing metadata

ContentStore
→ крупные raw/derived bytes
```

Нельзя заменять одну роль другой только ради локального упрощения без design decision.

---

# 25. Durable enqueue требует явной transaction semantics

Если операция должна одновременно:

1. сохранить authoritative durable job/state;
2. поставить работу в Redis/arq;

то порядок commit/enqueue, retry/reconciliation и crash windows должны быть явно определены в `persistence.md`/`jobs.md`.

Запрещено оставлять dual-write semantics неявной.

Возможность outbox/reconciliation должна быть рассмотрена до production реализации durable jobs.

---

# 26. `bootstrap/` — единственное место composition root

Concrete dependencies собираются в bootstrap/composition root.

Предварительно:

```text
bootstrap/container.py
bootstrap/wiring.py
bootstrap/lifespan.py
```

Именно здесь допустимы связи вида:

```text
SearchProvider = SearXNGProvider(...)
ContentStore = FilesystemContentStore(...)
JobQueue = ArqJobQueue(...)
BrowserWorkerClient = ...
```

Application service не создаёт concrete adapter самостоятельно.

---

# 27. `entrypoints/` максимально тонкие

Предварительные entrypoints:

```text
entrypoints/api.py
entrypoints/job_worker.py
entrypoints/browser_worker.py
```

Entrypoint отвечает за:

- загрузку config;
- вызов bootstrap;
- запуск соответствующего runtime;
- корректный shutdown.

Entrypoint не содержит application business logic.

---

# 28. `core/` не является папкой для случайных helpers

В `core/` допускаются только действительно сквозные технические primitives, например:

- configuration foundation;
- structured logging foundation;
- ID generation primitive;
- clock/time abstraction, если она оправдана;
- общие constants, если у них есть ясный владелец.

Запрещено создавать бесконтрольные:

```text
utils.py
helpers.py
misc.py
common.py
```

для предметной логики без владельца.

Если функция относится к Search/Content/Browser, она должна находиться рядом с владельцем.

---

# 29. Cross-cutting concerns не должны становиться скрытыми business services

Observability, security enforcement, rate limits и policy могут использовать middleware/decorators/ports, но не должны незаметно менять смысл application operation.

Например security policy может запретить URL, но не должна подменять URL другим.

---

# 30. Structured Hint формируется на application уровне

Hint является частью application result semantics.

Infrastructure adapter может предоставить diagnostics/facts, на основании которых application layer формирует канонический hint.

Transport только сериализует hint в REST/MCP representation.

Не следует хранить agent-facing canonical hint исключительно внутри MCP tool implementation.

---

# 31. Agent-facing текст не должен жить в provider adapters

Русскоязычные descriptions MCP tools/fields принадлежат `transport/mcp/`.

Application errors/hints могут содержать стабильный human-readable message на русском, если это часть принятой модели, но provider adapter не должен становиться владельцем agent UX.

---

# 32. Infrastructure error нормализуется до transport

Concrete exceptions:

```text
httpx.TimeoutException
redis.ConnectionError
sqlalchemy.exc.*
playwright.*
provider-specific exceptions
```

не должны напрямую утекать в REST/MCP contract.

Infrastructure/Application boundary должна преобразовать их в нормализованную failure taxonomy с сохранением безопасной diagnostic cause для logs/observability.

---

# 33. Неизвестный outcome не лечится transport retry

Если mutating operation могла завершиться на owning runtime, но response был потерян, transport/controller не должен автоматически повторять её только потому, что получил connection error.

`unknown outcome` должен пройти вверх как application semantics, после чего клиент/агент сможет выполнить безопасную проверку состояния.

---

# 34. Public contracts не содержат внутренних paths/objects

REST/MCP/application public results не должны возвращать клиенту как стабильный contract:

- local filesystem paths;
- SQLAlchemy model repr;
- Redis keys;
- worker internal address;
- Playwright object IDs без специально определённого opaque handle contract;
- stack traces.

Для addressable resources используются opaque handles/ContentObject references.

---

# 35. Testing должно проверять boundaries

Помимо функциональных тестов, проект должен иметь архитектурные/contract проверки, которые не дают случайно нарушить dependency direction.

Минимально необходимо проверять:

- domain/application не импортируют transport/infrastructure;
- фактические MCP schemas соответствуют design contract;
- REST/OpenAPI не содержит внутренних provider fields;
- persistence adapters не протекают в public results;
- browser state не зависит от одного API process;
- reconnect не уничтожает resource lifecycle без отдельного события.

Конкретная стратегия фиксируется в `testing.md`.

---

# 36. Изменение dependency boundary требует design update

Если реализация требует нового направления зависимости, которое противоречит этому документу, нельзя молча вносить coupling ради удобства.

Нужно:

1. проверить, действительно ли существующая граница неверна;
2. при необходимости обновить canonical design/ADR;
3. только затем менять код.

Version implementation plan не имеет права самостоятельно отменять сквозное dependency rule.
