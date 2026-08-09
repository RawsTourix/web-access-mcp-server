# План проектирования design-документации Web Access MCP

## Статус документа

Этот документ задаёт **порядок проектирования полноценной design-документации** проекта.

Он является метапланом: не описывает конкретную реализацию Search, Browser или MCP, а определяет, **в какой последовательности необходимо проектировать систему**, чтобы архитектурные решения грамотно ложились друг на друга и могли использоваться как основа для реализации Codex, ChatGPT и другими coding agents.

Главный принцип:

```text
общие инварианты
→ общие application-контракты
→ предметные подсистемы
→ runtime/infrastructure
→ REST
→ MCP
→ deployment/testing
→ roadmap и версии
```

Version roadmap проектируется **после** формирования архитектуры, а не используется для преждевременного разбиения ещё не спроектированной системы.

---

# 1. Этап 1 — фундамент документации

Сначала должны быть созданы сквозные документы, которые определяют язык и правила всей последующей архитектуры.

Необходимо спроектировать:

- `principles.md`;
- `glossary.md`;
- `dependency-rules.md`.

## Результат этапа

Должны быть однозначно определены:

- главные архитектурные принципы;
- направление зависимостей;
- базовые термины;
- границы domain/application/transport/infrastructure;
- правило backend-first;
- правило единого application layer для REST и MCP;
- запрет скрытых reasoning-эвристик;
- правила ownership и lifecycle, если они уже могут быть сформулированы на уровне invariants.

Эти документы становятся фундаментом для всех последующих design-файлов.

---

# 2. Этап 2 — system context и граница ответственности

Создаётся `system-context.md`.

Документ должен определить Web Access как систему в окружении других компонентов.

Необходимо описать как минимум:

```text
Agent / client
      ↓
Web Access
      ↓
Internet / search providers / websites / browser runtime
```

Также необходимо определить границу с внешними системами advanced processing.

## Обязательно закрепить

Web Access отвечает за:

- Search;
- безопасный Retrieval;
- Content Inspection;
- Native Parsing;
- Content storage/representations;
- Browser runtime;
- durable Jobs, когда они действительно необходимы.

Web Access **не является** универсальным OCR/document/media-processing сервисом.

Advanced Processing уровня L2 находится за границей системы:

- OCR;
- VLM;
- сложный layout recognition;
- LibreOffice-based conversion;
- transcription;
- тяжёлая multimedia processing;
- специализированная обработка неподдерживаемых форматов.

Сервис может возвращать structured hints о возможном следующем шаге, но не должен скрыто выполнять внешнюю orchestration.

---

# 3. Этап 3 — process topology и runtime boundaries

Создаётся `runtime-topology.md`.

До проектирования конкретных application-компонентов необходимо определить физическую модель исполнения.

Предварительная топология:

```text
API/MCP control plane × N
job worker × N
browser worker × N
SearXNG
PostgreSQL
Redis
ContentStore
```

## Нужно определить

- какие процессы stateless;
- какие процессы владеют живым состоянием;
- какие компоненты масштабируются независимо;
- какие process boundaries одновременно являются security boundaries;
- кто владеет Playwright/Chromium;
- почему BrowserSession не привязана к HTTP/MCP connection;
- какие компоненты требуют PostgreSQL;
- какие используют Redis;
- какие операции могут выполняться request-bound;
- какие требуют durable execution.

На этом этапе не требуется выбирать точный internal transport к browser worker, если решение ещё не принято. Такой выбор может стать отдельным ADR.

---

# 4. Этап 4 — общий application contract

Создаётся `application-contracts.md`.

Это один из самых важных документов системы.

До проектирования Search, Retrieval и Browser нужно определить общий язык application operations.

## Необходимо спроектировать

Понятия уровня:

```text
OperationId
Execution/OperationContext
Principal / Owner context
deadline
cancellation
OperationResult
OperationError
OperationOutcome
StructuredHint
Warning
Provenance
```

Точные имена определяются в процессе design.

## Обязательно определить

### Batch semantics

Для batch-first независимых операций:

- сохраняется ли порядок входных элементов;
- как представляется partial success;
- ошибка одного item не должна автоматически уничтожать успешные результаты остальных, если семантика операции допускает независимое выполнение;
- каждый item должен иметь собственный outcome/error;
- aggregate result должен однозначно описывать общий статус.

### Retry / idempotency semantics

Нужно разделить как минимум:

- безопасные read-only операции;
- idempotent mutating операции;
- операции, которые нельзя автоматически повторять.

### Unknown outcome

Если операция могла фактически выполнить side effect, но подтверждение результата потеряно, система должна уметь представить `unknown` отдельно от `failed`.

### Deadline и cancellation

Клиентский deadline должен иметь понятную семантику на всём пути:

```text
transport
→ application
→ provider / HTTP / worker
```

Cancellation request-bound operation и cancellation durable job должны проектироваться отдельно.

### Structured hints

Hint является данными, а не командой orchestration.

Предварительная форма может содержать:

```text
code
reason
related_capability
context / parameters
```

Для внутренних capabilities Web Access допускаются точные рекомендации.

Например:

```text
browser_may_be_required
```

Для внешних capabilities рекомендации должны быть осторожнее:

```text
advanced_processing_may_be_required
```

Не следует жёстко рекомендовать конкретный внешний продукт или инструмент, если он не является частью контракта системы.

---

# 5. Этап 5 — общая модель ресурсов

Создаётся `resource-model.md`.

Необходимо определить сущности, которые имеют lifecycle и могут переживать один transport request.

Предварительно:

```text
ContentObject
ContentRepresentation
BrowserSession
Job
remote/content handles
```

## Нужно определить

- opaque identifiers;
- ownership;
- principal readiness;
- lifecycle states;
- resource provenance;
- source/derived relationships;
- expiration;
- retention;
- cleanup ownership;
- связь между durable metadata и фактическим blob/state.

### Content representation graph

Нужно спроектировать происхождение representations, например:

```text
raw PDF
├── native text
├── native metadata
└── future externally-produced representation
```

Derived representation должна иметь provenance и ссылку на source content.

Это необходимо для:

- reproducibility;
- cache;
- debugging;
- повторного parsing;
- безопасной смены parser version.

---

# 6. Этап 6 — persistence и coordination

Создаётся `persistence.md`.

Только после определения resource model можно проектировать роли PostgreSQL, Redis и ContentStore.

## PostgreSQL

Необходимо определить, что является authoritative durable state.

Примерные категории:

- operation/job metadata;
- resource metadata;
- browser session metadata;
- provider usage;
- audit records;
- content references;
- lifecycle state.

## Redis

Необходимо отдельно определить роли:

- cache;
- rate limiting;
- distributed locks;
- leases/fencing;
- arq queue;
- browser worker registry/routing;
- event coordination;
- backpressure state.

Нельзя считать Redis одной универсальной «очередью для всего».

## ContentStore

Необходимо определить абстракцию хранения крупных bytes/representations.

Базовое направление:

```text
FilesystemContentStore
S3CompatibleContentStore
```

## Transaction boundaries

Нужно отдельно спроектировать:

- commit-before-enqueue;
- возможный outbox;
- reconciliation после частичных infrastructure failures;
- случаи, когда PostgreSQL update и Redis enqueue не могут считаться одной atomic operation.

---

# 7. Этап 7 — security foundation

Создаётся `security.md`.

Security проектируется до детальной реализации Retrieval и Browser.

## Общие области

- SSRF;
- DNS rebinding;
- redirect validation;
- private/link-local networks;
- egress policy;
- decompression bombs;
- resource limits;
- unsafe archives/files;
- secrets;
- safe logging;
- opaque handles;
- ownership;
- quotas;
- browser isolation;
- temporary files/downloads;
- process/container boundaries;
- trust model web content;
- prompt-injection-aware presentation содержимого агенту.

Каждая предметная подсистема позднее дополняет общую security model только своими специфическими рисками.

---

# 8. Этап 8 — Search design

Создаётся `search.md`.

Search проектируется как независимая application capability.

## Нужно определить

- domain models;
- application operations;
- `SearchProvider` port;
- SearXNG adapter;
- Yandex Search adapter;
- future provider extension model;
- batch semantics;
- provider selection;
- configured default provider;
- rate limiting;
- cache/freshness;
- normalization;
- deduplication, если она действительно нужна и её семантика определена;
- provenance;
- errors;
- hints;
- observability;
- acceptance criteria.

## Важный non-goal

Search не анализирует содержимое найденных страниц и не запускает Retrieval или Browser автоматически.

Не следует использовать скрытые эвристики вида:

```text
мало результатов → автоматически сменить provider
```

Search может вернуть диагностику или hint, но orchestration остаётся у клиента.

---

# 9. Этап 9 — Retrieval design

Создаётся `retrieval.md`.

Retrieval отвечает за безопасное получение известных HTTP(S)-ресурсов.

## Необходимо определить

- URL input model;
- batch-first semantics;
- HTTP streaming;
- redirect handling;
- DNS/IP validation;
- SSRF;
- decompression limits;
- size limits;
- deadlines;
- content identification handoff;
- raw ContentObject creation;
- partial batch failures;
- cache/freshness;
- retry semantics;
- error taxonomy;
- observability;
- acceptance criteria.

## Граница ответственности

Retrieval не запускает Browser автоматически.

Retrieval не выполняет OCR и advanced processing.

Он получает и сохраняет ресурс и передаёт его Content subsystem.

---

# 10. Этап 10 — Content design

Создаётся `content.md`.

В документе должна быть подробно формализована трёхуровневая модель.

## L0 — Inspection

Дешёвая идентификация и metadata:

- declared MIME;
- detected format;
- size;
- hash;
- page count;
- dimensions;
- container information;
- EXIF/technical metadata, где это уместно.

Inspection не должна пытаться понять семантику документа.

## L1 — Native Parsing

Прямое детерминированное чтение доступной структуры без тяжёлого processing.

Примеры:

```text
HTML → text / links / metadata
PDF с text layer → text
JSON → structured data
XML → structure
CSV → rows
DOCX → paragraphs/tables
XLSX → sheets/cells
PPTX → slides/text
EPUB/FB2 → chapters/text
```

Поддержка форматов должна определяться через parser registry, а не архитектурный список расширений.

Если parser отсутствует или native representation недоступна, Web Access возвращает raw content + diagnostics/hints.

## L2 — Advanced Processing

Явно находится за границей Web Access:

- OCR;
- VLM;
- complex layout recognition;
- transcription;
- LibreOffice conversion;
- тяжёлая multimedia/document processing.

Web Access не переходит на L2 автоматически.

## Дополнительно проектируется

- ContentStore;
- representation graph;
- provenance;
- parser versioning;
- retention;
- native parsing errors;
- structured hints;
- acceptance criteria.

---

# 11. Этап 11 — Browser design

Создаётся `browser.md`.

Browser проектируется после application/resource/persistence contracts, потому что является самой сложной stateful частью системы.

## Нужно определить

- BrowserSession domain model;
- session lifecycle;
- opaque handles;
- worker ownership;
- worker routing;
- BrowserContext ownership;
- pages/tabs;
- snapshots;
- actions;
- action ordering;
- session revision/generation/fencing при необходимости;
- uploads/downloads;
- Content integration;
- idle TTL;
- maximum lifetime;
- reaper;
- client cleanup requests;
- worker crash;
- session `lost` state;
- cancellation;
- unknown side-effect outcome;
- reconnect semantics;
- process/container isolation;
- horizontal scaling;
- acceptance criteria.

## Ключевой invariant

```text
MCP/HTTP connection lifecycle
≠
BrowserSession lifecycle
```

BrowserSession принадлежит сервису и конкретному browser worker, а не transport connection.

---

# 12. Этап 12 — Jobs и async execution

Создаётся `jobs.md`.

Jobs проектируются только после обычных application operations.

Сначала нужно понять, какие задачи действительно требуют durable execution.

## Необходимо определить

- критерий durable operation;
- job lifecycle;
- PostgreSQL source of truth;
- enqueue protocol;
- arq;
- cancellation;
- retry;
- progress/events;
- result persistence;
- cleanup;
- expiration;
- worker crash/restart;
- reconciliation;
- idempotency;
- acceptance criteria.

## Важный принцип

Короткая операция не должна становиться Job только потому, что Redis/arq уже есть в стеке.

---

# 13. Этап 13 — observability и operability

Создаётся `observability.md`.

После проектирования реальных runtime-операций можно определить наблюдаемость без догадок.

## Нужно определить

- structured logging;
- correlation/operation IDs;
- metrics;
- traces;
- upstream call diagnostics;
- provider usage;
- cache statistics;
- browser worker health;
- session/resource lifecycle metrics;
- queue health;
- degraded states;
- readiness;
- audit vs telemetry boundary;
- cardinality limits;
- data retention для observability.

---

# 14. Этап 14 — REST API design

Создаётся `rest-api.md`.

REST проектируется только после стабилизации application surface.

## REST должен

- предоставлять мощный программный интерфейс практически ко всему полезному backend-функционалу;
- быть удобным для других микросервисов и будущего web UI;
- предоставлять richer controls, чем MCP;
- поддерживать resources/jobs/browser management;
- иметь стабильные versioned schemas;
- не дублировать business logic;
- не раскрывать случайные детали HTTPX/Playwright/SearXNG/Redis/SQLAlchemy.

## Нужно определить

- resource-oriented endpoint structure;
- request/response schemas;
- pagination;
- batch contracts;
- status/error mapping;
- idempotency keys, где нужны;
- cancellation;
- content transfer;
- long-running job representation;
- versioning;
- OpenAPI contract;
- auth integration points;
- acceptance criteria.

---

# 15. Этап 15 — MCP facade design

Создаётся `mcp.md`.

MCP проектируется как agent-facing projection готового application backend-а.

## Основные правила

- один intent — один canonical tool;
- нет бессмысленных aliases;
- независимые stateless операции batch-first;
- stateful sequential actions не batch-ятся механически;
- tools максимально просты для LLM;
- MCP должен сохранять почти всю практическую мощность backend-а;
- provider/infrastructure internals скрыты;
- JSON Schema рассматривается как agent UX;
- все публичные поля имеют качественные descriptions;
- docstrings и agent-facing тексты преимущественно на русском языке;
- machine-readable constraints реальны;
- cross-field invariants отражаются в фактической schema;
- validation errors позволяют LLM исправить вызов;
- tool annotations соответствуют реальной side-effect/retry semantics;
- structured hints передаются агенту явно;
- schema тестируется через настоящий MCP client, а не только через Pydantic model.

## Важно

MCP не обязан повторять REST один к одному.

Несколько backend capabilities могут быть представлены одним удобным MCP intent, если это не скрывает важную семантику.

И наоборот, stateful/side-effecting действия должны оставаться отдельными, если объединение ухудшает контроль агента.

---

# 16. Этап 16 — deployment и масштабирование

Создаётся `deployment.md`.

## Нужно спроектировать

- Docker images;
- Docker Compose для локального/односерверного deployment;
- API replicas;
- job worker replicas;
- browser worker pool;
- SearXNG deployment;
- PostgreSQL;
- Redis;
- ContentStore;
- health/live/readiness;
- graceful shutdown;
- rolling restart;
- worker draining;
- browser session cleanup/migration policy;
- degraded startup modes;
- configuration;
- secrets;
- capacity limits;
- horizontal scaling;
- network segmentation;
- backup/recovery requirements.

Внутренний browser-worker transport при необходимости оформляется отдельным ADR.

---

# 17. Этап 17 — testing и release gates

Создаются:

- `testing.md`;
- `release-gates.md`.

Тестовая стратегия должна быть частью архитектуры.

Необходимо определить уровни:

```text
unit
contract
integration
REST/OpenAPI
MCP schema
browser lifecycle
failure injection
restart/recovery
concurrency/race
security
load
end-to-end
```

Особенно важны:

- actual FastMCP schema tests;
- batch partial failure tests;
- SSRF tests;
- provider outage tests;
- Redis/PostgreSQL outage tests;
- browser worker death;
- session expiry/reaper;
- unknown side-effect outcome;
- cancellation races;
- duplicate/retry behavior;
- memory/resource leak tests;
- horizontal scaling tests.

Release gates должны быть бинарными и проверяемыми.

---

# 18. Этап 18 — roadmap и версии

Только после завершения архитектурного design создаётся `roadmap.md` и структура `versions/`.

## Принцип

Версии определяются dependency graph архитектуры, а не заранее выбранными красивыми номерами.

Нельзя заранее считать:

```text
v0.1 = foundation
v0.2 = Search
v0.3 = Retrieval
```

пока не понятно, какие общие contracts необходимы каждой подсистеме.

## Для каждой версии необходимо определить

- prerequisites;
- цель;
- scope;
- non-goals;
- затрагиваемые design contracts;
- implementation sequence;
- schema/database migrations;
- compatibility requirements;
- rollback/recovery considerations;
- tests;
- acceptance criteria;
- release gate.

Version docs не должны заново изобретать архитектуру.

Они отвечают на вопрос:

> Какую часть уже принятого design реализовать на этом этапе и в каком безопасном порядке?

---

# 19. Стандартная структура компонентного design-документа

Чтобы документация была удобна для Codex и других coding agents, component documents (`search.md`, `browser.md`, `content.md` и т. д.) должны по возможности следовать общей форме.

## Обязательные разделы

### Purpose

Зачем компонент существует.

### Responsibilities

Что входит в его ответственность.

### Non-goals

Что явно не входит.

### Domain model

Сущности, value objects, enums и состояния.

### Application operations

Реальные backend operations независимо от REST/MCP.

### Ports

Какие внешние зависимости требуются компоненту.

### Invariants

Условия, которые нельзя нарушать ни одной реализацией.

### Execution model

Request-bound, stateful или durable.

### Persistence

Что хранится в PostgreSQL, Redis, ContentStore или только в памяти runtime.

### Concurrency

Ordering, locks, fencing, races, parallelism и backpressure.

### Lifecycle

Создание, активная работа, terminal states и cleanup.

### Cancellation

Когда и как операция может быть остановлена.

### Retry / idempotency

Какие операции можно повторять и при каких условиях.

### Failure model

Ошибки и outcomes компонента.

### Structured hints

Какие наблюдаемые ситуации могут сопровождаться рекомендацией следующего шага и почему это не является автоматической orchestration.

### Security

Специфические угрозы компонента.

### Observability

Логи, метрики, traces и audit.

### REST projection

Как component capability должна быть представлена REST после проектирования общего REST facade.

### MCP projection

Какие требования должна учитывать agent-facing projection. До этапа MCP этот раздел может содержать только constraints, а не окончательную schema.

### Tests

Обязательные классы тестов.

### Acceptance criteria

Бинарные проверяемые критерии готовности.

### Open questions

Только действительно непринятые решения.

После принятия решения open question должен исчезнуть либо превратиться в ADR.

---

# 20. Стандартная структура version-документа

Version specification должна быть максимально пригодна для прямой реализации coding agent-ом.

Рекомендуемая структура:

```text
Status
Context
Prerequisites
Goal
Scope
Non-goals
Affected design contracts
Target architecture after this version
Implementation sequence
Database/schema migrations
Configuration changes
Compatibility
Failure/recovery considerations
Tests
Acceptance criteria
Release gate
Deferred work
```

Если update слишком большой, необходимо создавать отдельный `implementation-sequence.md` вместо одного гигантского README.

---

# 21. Правила для Codex/ChatGPT-friendly документации

Документация должна позволять coding agent-у работать без угадывания архитектурного намерения.

Поэтому необходимо:

- использовать точные термины из glossary;
- явно указывать владельца каждого состояния;
- явно описывать dependency direction;
- явно описывать transaction boundary;
- явно указывать side effects;
- не смешивать planned и implemented state;
- не использовать неопределённое «и т.п.» в critical contracts;
- отделять required от optional;
- отделять current decision от open question;
- указывать non-goals;
- давать positive/negative examples там, где контракт легко неправильно понять;
- формулировать acceptance criteria так, чтобы их можно было автоматизировать тестом;
- не копировать один контракт в несколько документов.

Если implementation agent должен сам решить существенный архитектурный вопрос, design считается недостаточно готовым.

---

# 22. Последовательность реального проектирования

Итоговый порядок работы над design:

```text
1. principles / glossary / dependency rules
2. system context
3. runtime topology
4. application contracts
5. resource model
6. persistence
7. security
8. Search
9. Retrieval
10. Content
11. Browser
12. Jobs
13. observability
14. REST API
15. MCP facade
16. deployment
17. testing / release gates
18. roadmap / versions
```

Допускаются итерации назад, если детальное проектирование выявило отсутствующий сквозной invariant.

Однако нельзя локально «решить проблему» в компонентном документе, если это решение на самом деле относится ко всей системе. В таком случае сначала обновляется канонический cross-cutting design.

---

# 23. Критерий готовности design к реализации

Полноценный implementation roadmap можно считать готовым только если:

- предметные границы непротиворечивы;
- application contracts определены;
- resource ownership и lifecycle определены;
- persistence roles определены;
- security boundaries определены;
- Search/Retrieval/Content/Browser/Jobs имеют полноценные component designs;
- REST отражает backend без собственной business logic;
- MCP предоставляет удобный LLM-facing facade над тем же backend;
- deployment topology согласована с lifecycle/state model;
- testing strategy проверяет основные failure/race scenarios;
- версии построены по dependency graph;
- у implementation agent не остаётся необходимости самостоятельно изобретать ключевую архитектуру.

После достижения этого состояния version specifications могут использоваться как основа для подробных implementation prompts Codex/ChatGPT.
