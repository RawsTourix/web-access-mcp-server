# Архитектурная концепция Web Access MCP

## Статус документа

Этот документ фиксирует **макроархитектуру и границы модулей** Web Access MCP.

Он является concept-level обзором. Точные runtime protocols, concrete libraries, database schemas, REST/MCP DTO, limits и version steps принадлежат `docs/design/` и accepted ADR.

Если ранний concept расходится с поздним Design/ADR/contract, канонический design имеет приоритет.

---

# 1. Главный принцип структуры

Структура отражает **границы ответственности и владения state**, а не список libraries.

Базовое направление зависимостей:

```text
transport
   ↓
application
   ↓
domain

infrastructure
   ↑ implements application ports

workers/runtime executors
   → исполняют runtime-specific contracts

bootstrap
   → связывает concrete implementations

entrypoints
   → запускают собранные runtimes
```

Проект не должен превращаться ни в плоский `services/utils`, ни в формальную Clean Architecture с искусственными слоями без реальной пользы.

---

# 2. Repository layout direction

```text
web-access-mcp-server/
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
├── alembic/
├── tests/
├── docs/
├── deploy/
├── scripts/
├── pyproject.toml
└── docker-compose.yml
```

Предпочтителен `src` layout.

Фактическая детализация package tree определяется version implementation plans; направление зависимостей — нет.

---

# 3. Domain/application areas

Основные предметные области:

```text
search
retrieval
content
browser
jobs
```

Cross-cutting application foundation:

```text
execution context
results/errors/warnings/hints
ownership/resource references
policy
observability context
```

Domain/application code не зависит от FastAPI/FastMCP, SQLAlchemy, Redis clients, HTTP/browser libraries или конкретного provider SDK.

---

# 4. Ports принадлежат потребителю

Application module объявляет нужный port рядом со своим use case.

Примеры:

```text
Search
→ SearchProvider
→ SearchCache/flow policy interfaces

Retrieval
→ SafeHttpFetcher / URL policy

Content
→ ContentStore / NativeParser registry

Browser
→ BrowserWorkerClient / BrowserSessionRepository

Jobs
→ JobRepository / queue-delivery abstractions
```

Concrete adapter выбирается bootstrap/composition root.

---

# 5. Infrastructure

`infrastructure/` содержит concrete implementations:

```text
database
redis
search providers
safe retrieval
content identification/parsers/storage
job delivery
observability adapters
internal RPC clients
```

Infrastructure может зависеть от внешних libraries; application/domain — нет.

Provider/library-specific payload никогда автоматически не становится public REST/MCP model.

---

# 6. Transport

Два основных public facade:

```text
transport/rest
transport/mcp
```

Оба вызывают общий application layer.

Запрещён baseline:

```text
MCP tool → HTTP request к собственному REST
REST route → internal MCP call
```

Transport отвечает за:

- auth/context mapping;
- transport DTO/validation;
- application mapper;
- response/error projection;
- protocol-specific metadata.

Business logic там не живёт.

---

# 7. Runtime topology

В одном репозитории существуют разные runtime classes.

## Control Plane

```text
web-access-api
```

Владеет:

- FastAPI/FastMCP;
- application services;
- request-bound orchestration;
- PostgreSQL/Redis/ContentStore adapters;
- routing к workers.

Он не владеет authoritative live Browser objects.

## Job Worker

```text
web-access-worker
```

Исполняет durable registered typed workloads через Job lifecycle.

Queue message не несёт arbitrary function/code; PostgreSQL остаётся authoritative source of truth.

## Browser Worker supervisor

```text
web-access-browser-worker
```

Владеет Browser worker generation/lease/capacity и supervision session subprocesses.

## BrowserSession subprocess

Одна логическая BrowserSession исполняется в отдельном child process:

```text
session subprocess
→ Playwright
→ dedicated Chromium
→ non-persistent BrowserContext
→ bounded Pages
```

Это даёт отдельный hard-kill/failure boundary для каждой сессии.

---

# 8. Browser control vs website egress

Browser control traffic и web egress — разные trust paths.

Концептуально:

```text
Control Plane
→ authenticated internal Browser Worker RPC

BrowserSession/Chromium
→ controlled public-only egress boundary
→ Internet
```

Browser child не должен получать DB/Redis/provider/auth secrets.

Подробный transport/lease/egress contract принадлежит Browser ADR.

---

# 9. Content architecture

`Content` — единая область для:

```text
Identification
L0 Inspection
L1 Native Parsing
Representation graph
Provenance
Storage/lifecycle
```

Standalone generic `Extraction` bounded context не используется.

Пример lineage:

```text
raw PDF
├── native text
└── metadata

raw HTML
├── native document representation
└── structured metadata/links
```

Derived representation не заменяет original.

L2 processors остаются внешними по отношению к Web Access core.

---

# 10. Request-bound vs durable execution

Request-bound path используется для коротких explicit operations:

```text
Search
Retrieval
Content read/native parse
Browser action через owning worker
```

Durable Job — отдельный resource/lifecycle для long-running work:

```text
create Job durably
→ queue wake-up
→ DB claim/attempt/fencing
→ checkpoints/progress
→ terminal result
```

Нельзя автоматически переводить direct call в Job hidden heuristic-ой.

---

# 11. Persistence responsibilities

```text
PostgreSQL
→ authoritative durable structured state

Redis
→ cache / rate / short-lived coordination / routing / queue delivery signal

ContentStore
→ large immutable blobs/representations
```

Cross-system crash windows закрываются explicit lifecycle/reconciliation, а не надеждой на последовательность вызовов.

---

# 12. Composition root

Concrete dependencies собираются сверху.

Концептуально:

```text
SearchProvider port → SearXNG/Yandex adapter
ContentStore port → filesystem/S3-compatible adapter
BrowserWorkerClient → internal worker RPC adapter
Repositories → SQLAlchemy implementations
Job delivery → Redis/arq infrastructure
```

Application service не создаёт себе concrete client/repository сам.

---

# 13. Entrypoints

Entrypoints тонкие:

```text
api
job_worker
browser_worker
parser/session child entrypoints where required by isolation
```

Их работа:

```text
load validated config
→ build dependencies/runtime
→ run
→ graceful bounded shutdown
```

Не business logic.

---

# 14. Масштабирование

Архитектура допускает независимое масштабирование:

```text
Control Plane replicas
Job Workers
Browser Workers
SearXNG
PostgreSQL
Redis
ContentStore
Browser egress gateway
```

API replica restart не должен автоматически уничтожать durable Job/Content или BrowserSession.

Потеря owning Browser Worker/session child может сделать BrowserSession `lost`; это explicit lifecycle, а не скрытый reconnect retry.

---

# 15. Structured hints

Application result разделяет:

```text
facts/result
warnings
trusted structured hints
errors
```

Hint может рекомендовать capability, но не выполняет её автоматически.

Особенно точными могут быть same-service рекомендации (`web_fetch` result → browser may be useful). External processing recommendations формулируются через capability class, не как hidden dependency на конкретный продукт.

---

# 16. Testing topology

Проект должен иметь разные классы evidence:

```text
unit
contract
integration
race/concurrency
fault/restart
security
browser lifecycle
migration/restore
soak/leak
load/backpressure
REST/OpenAPI
actual MCP schemas
e2e
```

Runtime/process boundaries считаются архитектурой только после tests, доказывающих crash/recovery semantics.

---

# 17. Канонический подробный design

Concept-level структура развёрнута в:

```text
docs/design/dependency-rules.md
docs/design/runtime-topology.md
docs/design/persistence.md
docs/design/<component>.md
docs/design/decisions/
docs/design/contracts/
docs/design/versions/
```

Для реализации использовать именно эти документы и `docs/AGENTS.md`.
