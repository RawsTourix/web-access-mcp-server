# v0.1 — Service Foundation

## Статус

`design in progress`

Версия становится `ready for implementation`, когда закрыты все blockers этого документа и согласован `implementation-sequence.md`.

---

# 1. Цель

Создать production-oriented фундамент Web Access MCP, на который Search/Retrieval/Content/Browser/Jobs смогут добавляться без перестройки process/dependency/auth/persistence boundaries.

После v0.1 сервис уже должен:

- запускаться локально через Docker Compose;
- иметь REST + MCP Control Plane;
- аутентифицировать клиентов;
- создавать trusted PrincipalContext;
- иметь PostgreSQL/Redis/ContentStore infrastructure foundation;
- иметь typed configuration;
- иметь canonical application result/error contracts;
- иметь health/readiness/status;
- иметь structured observability baseline;
- иметь CI/architecture/contract tests.

При этом v0.1 намеренно **не выполняет web search/fetch/browser работу**.

---

# 2. Prerequisites

Обязательные документы:

- `../../principles.md`;
- `../../glossary.md`;
- `../../dependency-rules.md`;
- `../../system-context.md`;
- `../../runtime-topology.md`;
- `../../application-contracts.md`;
- `../../resource-model.md`;
- `../../persistence.md`;
- `../../security.md`;
- `../../observability.md`;
- `../../deployment.md`;
- `../../testing.md`;
- `../../release-gates.md`;
- `../../decisions/ADR-0002-authentication-principal-baseline.md`.

---

# 3. Explicit non-goals

v0.1 не реализует:

- SearXNG/Yandex Search;
- `web_search`;
- external HTTP Retrieval;
- Native Parsers;
- ContentObject application API;
- Browser Worker;
- Playwright;
- Job Worker/arq/outbox runtime;
- public Job resources;
- L2 processing;
- user accounts/OIDC;
- admin UI;
- persistent browser state.

Не следует добавлять «временный поиск» или «простую Playwright функцию» ради demo.

---

# 4. Target repository layout v0.1

```text
src/
└── web_access/
    ├── core/
    │   ├── config.py
    │   ├── logging.py
    │   ├── ids.py
    │   └── time.py
    │
    ├── domain/
    │   └── common/
    │       ├── enums.py
    │       └── refs.py
    │
    ├── application/
    │   └── common/
    │       ├── context.py
    │       ├── results.py
    │       ├── errors.py
    │       ├── hints.py
    │       ├── auth.py
    │       └── ports.py
    │
    ├── transport/
    │   ├── rest/
    │   │   ├── app.py
    │   │   ├── dependencies.py
    │   │   ├── errors.py
    │   │   ├── schemas.py
    │   │   └── routers/
    │   │       └── health.py
    │   └── mcp/
    │       ├── server.py
    │       └── errors.py
    │
    ├── infrastructure/
    │   ├── auth/
    │   │   └── static_bearer.py
    │   ├── database/
    │   │   ├── engine.py
    │   │   ├── unit_of_work.py
    │   │   └── base.py
    │   ├── redis/
    │   │   └── client.py
    │   ├── content/
    │   │   └── filesystem.py
    │   └── observability/
    │       └── health.py
    │
    ├── bootstrap/
    │   ├── container.py
    │   ├── lifespan.py
    │   └── wiring.py
    │
    └── entrypoints/
        └── api.py

alembic/
tests/
docs/
Dockerfile
docker-compose.yml
pyproject.toml
```

Exact split одного файла может уточняться, но layer ownership не меняется.

---

# 5. Python/package baseline

- Python `>=3.11`;
- `src` layout;
- один installable package `web_access`;
- dependencies управляются через `pyproject.toml` + reproducible lock mechanism;
- runtime imports не зависят от project root working directory;
- package version доступна operational metadata.

Точный lock tool (`uv`, Poetry, pip-tools и т.п.) должен быть выбран implementation plan; предпочтительно использовать уже знакомый проекту `uv`, если нет причины выбрать другое.

---

# 6. Initial runtime dependencies

v0.1 должен включить только foundation dependencies:

- FastAPI;
- Uvicorn;
- FastMCP 3.x compatible line;
- Pydantic v2;
- pydantic-settings;
- SQLAlchemy 2 async;
- asyncpg;
- Alembic;
- redis asyncio client;
- необходимые observability/testing dependencies.

Не устанавливаются заранее:

- Playwright;
- Trafilatura;
- pypdf;
- arq;
- Office parsers.

Они добавляются версиями, которые реально их используют.

---

# 7. Configuration

Используется единый `Settings` composition root с prefix уровня:

```text
WEB_ACCESS_
```

Configuration groups:

```text
AppSettings
AuthSettings
DatabaseSettings
RedisSettings
ContentStoreSettings
ObservabilitySettings
SecuritySettings (foundation)
```

Nested settings предпочтительнее гигантского flat object.

Secrets используют `SecretStr`/secret abstraction и не отображаются в repr/logs.

---

# 8. Configuration validation

Startup fail-fast для обязательной некорректной config.

Примеры:

- отсутствует production bearer token/principal config;
- malformed PostgreSQL URL;
- invalid resource limit;
- filesystem ContentStore root невалиден/недоступен при required profile.

Development defaults не должны становиться insecure production defaults.

---

# 9. Application common contracts

Реализуются типы/протоколы из `application-contracts.md`:

- `OperationId`;
- `ExecutionContext`;
- `PrincipalContext`;
- `OperationOutcome`;
- `OperationResult[T]`;
- `OperationError`;
- `Warning`;
- `StructuredHint`;
- common error categories;
- cancellation/deadline foundation.

v0.1 tests фиксируют aggregate/result invariants, даже если batch business capability появится позже.

---

# 10. IDs

Server-generated opaque IDs используют единый generator abstraction/helper.

Требования:

- достаточная random/uniqueness entropy;
- lowercase/type-prefixed representation допустима;
- client не извлекает meaning из ID;
- deterministic fake generator для unit tests.

Точный UUID/ULID/random-token choice фиксируется implementation, но ResourceRef API не должен зависеть от сортируемости конкретного формата.

---

# 11. Clock/time

Application timestamps UTC/timezone-aware.

Durations/deadlines используют monotonic time там, где возможно.

Для TTL/state tests должен существовать Clock abstraction или injection point, чтобы не использовать real sleep.

---

# 12. Authentication baseline

Реализуется ADR-0002:

```text
Authorization: Bearer
→ StaticBearerAuthProvider
→ PrincipalContext
```

Requirements:

- multiple configured service principals;
- scopes;
- constant-time comparison;
- rotation overlap;
- no raw token logs;
- REST/MCP use same provider;
- `/health/live`/`ready` access policy explicit;
- detailed status protected.

---

# 13. Authorization foundation

Нужен минимальный reusable application helper/policy port:

```text
require_scope(...)
require_owner(...)
```

или эквивалентный сервис.

v0.1 пока не имеет business resources, но tests должны доказать:

- principal A ≠ principal B;
- scope denial structured;
- transport auth не смешан с application authorization.

---

# 14. PostgreSQL foundation

Реализуется:

- async engine;
- async session factory;
- SQLAlchemy declarative base/metadata;
- explicit UnitOfWork;
- Alembic environment;
- empty/initial baseline migration при необходимости tooling consistency;
- DB health probe;
- pool shutdown/lifespan.

v0.1 не создаёт искусственные business tables только ради проверки ORM.

---

# 15. UnitOfWork

Target implementation:

```text
SqlAlchemyUnitOfWork
```

который:

- владеет `AsyncSession`;
- открывает явную transaction boundary;
- предоставляет repositories поздним modules;
- commit/rollback выполняется только явным application boundary;
- repositories не выполняют hidden commit.

v0.1 может пока не иметь concrete business repositories.

---

# 16. Alembic

Requirements:

- config работает внутри package/container;
- metadata import не запускает application side effects;
- migration command отдельный от API startup;
- CI проверяет единственный head;
- empty DB upgrade succeeds.

---

# 17. Redis foundation

Реализуется async Redis client factory/lifecycle.

v0.1 использует Redis только для:

- connectivity/health foundation;
- future adapter wiring tests.

Не нужно создавать premature cache/lock/queue abstractions без consumer module.

Redis outage может делать status degraded, но не должен ломать `/health/live`.

---

# 18. ContentStore port foundation

Реализуется минимальный `ContentStore` storage port и filesystem adapter, достаточный для contract tests streaming bytes.

Минимальные operations conceptually:

```text
stage/write stream
finalize
open/read stream
exists/stat
remove
```

Application `ContentObject` lifecycle появляется в v0.3; v0.1 не публикует Content API.

---

# 19. Filesystem ContentStore

Requirements:

- root configurable;
- root создаётся/валидируется startup;
- generated storage keys;
- no client filename as path;
- temp/staging inside same storage filesystem where atomic finalize is needed;
- atomic rename/replace finalization where platform/filesystem semantics allow;
- hash/size contract-testable;
- no path traversal;
- async-friendly streaming via bounded thread/file strategy, без giant RAM buffering.

Exact fsync durability policy фиксируется implementation/production profile позже.

---

# 20. Structured logging

v0.1 вводит structured logging:

- JSON/machine-readable production format;
- human-readable developer option допустим;
- operation/request/trace context;
- redaction;
- startup configuration summary без secrets.

No business web content в logs.

---

# 21. Metrics/tracing foundation

v0.1 должен иметь extension points и minimal operational metrics.

Минимум:

- process/startup;
- HTTP request duration/outcome;
- DB/Redis health;
- auth rejects;
- operation common counters.

Full component metrics добавляются соответствующими версиями.

OpenTelemetry/metrics concrete libraries выбираются implementation plan без изменения application interfaces.

---

# 22. Health endpoints

Реализуются:

```text
GET /health/live
GET /health/ready
GET /health/status
```

Semantics из `observability.md`.

### live

Не проверяет external dependencies как restart condition.

### ready

Проверяет runtime bootstrap/mandatory foundation.

### status

Возвращает detailed dependency/capability summary и требует appropriate auth/admin scope, кроме явно redacted local profile.

---

# 23. FastAPI + FastMCP application composition

Control Plane создаёт один FastAPI root app и монтирует/подключает FastMCP Streamable HTTP sub-application.

Lifespan должен единообразно управлять:

- settings;
- auth provider;
- DB engine;
- Redis client;
- ContentStore;
- metrics/tracing;
- FastMCP lifespan.

Используется проверенный общий application-layer pattern, а не отдельный MCP process.

---

# 24. MCP v0.1

MCP endpoint должен:

- запускаться по Streamable HTTP;
- требовать Bearer auth;
- корректно отвечать standard client initialization/list tools;
- не публиковать placeholder business tools.

Первые реальные tools появляются v0.2.

Tests могут регистрировать synthetic test-only tool fixture для проверки PrincipalContext/schema integration, но production catalog остаётся пустым до Search.

---

# 25. REST v0.1

Application REST пока содержит только operational/foundation routes.

`/api/v1` может возвращать service/version metadata в authorized status endpoint, но не нужно создавать fake business CRUD.

---

# 26. Error mapping foundation

FastAPI transport-level validation/auth/internal errors должны иметь согласованный safe envelope.

Expected structure следует `rest-api.md`.

Stack traces/internal URLs/secrets не возвращаются.

---

# 27. Bootstrap/container

`bootstrap/container.py` или эквивалент строит dependency graph.

Никаких global clients, созданных import-time.

Tests могут заменить:

- AuthProvider;
- Clock;
- ID generator;
- DB/Redis/ContentStore ports.

---

# 28. Lifespan

Startup order conceptually:

```text
load/validate settings
→ configure logging/telemetry
→ build auth
→ create DB/Redis/storage clients
→ verify mandatory local prerequisites
→ build application container
→ start transport apps
```

Shutdown reverse/bounded.

Optional dependency failure отражается degraded status согласно configuration, а не всегда process crash.

---

# 29. Entry point

Canonical Uvicorn target должен быть стабильным, например:

```text
web_access.entrypoints.api:app
```

или app factory equivalent.

Exact target фиксируется README/Compose/scripts и не зависит от repository cwd hacks.

---

# 30. Docker image

v0.1 application image:

- Python 3.11+ compatible;
- non-root runtime user;
- pinned/install-locked dependencies;
- source package installed;
- health-compatible;
- no compilers/build secrets в runtime layer, где возможно;
- no Playwright/browser dependencies.

---

# 31. Docker Compose v0.1

Services:

```text
postgres
redis
migration
api
```

SearXNG добавляется v0.2.

Browser/Job workers добавляются их версиями.

Volumes:

- PostgreSQL data;
- Redis dev persistence optional;
- filesystem ContentStore.

Наружу по умолчанию публикуется только API port.

---

# 32. `.env.example`

Repository содержит безопасный example с placeholders.

Не содержит рабочий token/password.

Документация даёт command/script для генерации random bearer secret.

---

# 33. Test foundation

v0.1 создаёт:

```text
tests/unit
tests/contract
tests/integration
```

и support fixtures для:

- Settings;
- fake Clock/IDs/Auth;
- PostgreSQL;
- Redis;
- filesystem ContentStore;
- ASGI app;
- FastMCP client.

---

# 34. Architecture tests

Автоматически enforce dependency rules.

Любой import FastAPI/SQLAlchemy/Redis из `domain`/application core должен ломать CI.

---

# 35. Auth tests

Обязательны:

- missing bearer;
- invalid bearer;
- two principals;
- scope denial;
- rotation overlap;
- no token in repr/log;
- REST auth;
- MCP auth;
- live/ready access policy;
- detailed status protection.

---

# 36. Persistence foundation tests

- PostgreSQL connection/reconnect;
- UoW commit/rollback;
- repository hidden commit absent (через synthetic test repository допускается);
- Alembic empty DB→head;
- Redis connectivity/restart behavior;
- ContentStore stream/finalize/read/remove/path traversal.

---

# 37. Health/degraded tests

Scenarios:

- all ready;
- Redis down;
- PostgreSQL down;
- ContentStore unavailable;
- optional dependency down;
- app draining/shutdown.

Liveness не должна создавать restart storm из-за Redis/PostgreSQL outage.

Exact readiness response следует design.

---

# 38. MCP schema foundation test

Даже с пустым business catalog test должен подтвердить:

- server initializes;
- unauthorized client rejected;
- authorized standard client connects;
- list_tools succeeds;
- no unexpected placeholder tools.

---

# 39. Required gates

Обязательны:

- G0 Design completeness;
- G1 Build/static;
- G2 Unit/application contracts;
- G3 MCP/REST foundation schema where applicable;
- G4 Persistence/migrations;
- G6 Security baseline;
- G12 Observability/health foundation;
- G15 reference deployment foundation;
- G21 Documentation consistency.

G5 cross-system Job/ContentObject consistency полноценно применяется позднее, когда соответствующие resources появятся.

---

# 40. Acceptance criteria v0.1

Версия принимается, если:

1. Repository имеет принятый src-layout/layer boundaries.
2. Project устанавливается reproducibly и imports работают вне repo cwd.
3. Typed Settings загружаются/валидируются.
4. REST + Streamable HTTP MCP запускаются в одном Control Plane.
5. Bearer AuthProvider создаёт PrincipalContext для REST/MCP.
6. Cross-principal/scope tests foundation green.
7. OperationResult/Error/Hint/Warning contracts реализованы/tested.
8. PostgreSQL async engine + UoW + Alembic работают.
9. Redis lifecycle/health работает.
10. Filesystem ContentStore contract roundtrip/atomic finalization работает.
11. Structured logs/redaction/operation IDs работают.
12. `/health/live`, `/health/ready`, `/health/status` соответствуют design.
13. Docker Compose поднимается с пустого окружения одной командой.
14. Только API port exposed по умолчанию.
15. Migration выполняется отдельным one-shot step.
16. Architecture dependency tests green.
17. Actual FastMCP authorized/unauthorized initialization tests green.
18. Required gates имеют 0 failures/flaky defects.
19. Search/Retrieval/Browser/Jobs dependencies не добавлены преждевременно.

---

# 41. Blockers before `ready for implementation`

Остаётся определить в `implementation-sequence.md`/tooling choice:

1. exact dependency/lock tool;
2. exact structured logging implementation;
3. exact metrics/OpenTelemetry libraries;
4. exact static bearer config schema;
5. exact opaque ID format;
6. exact filesystem ContentStore key/finalization implementation details;
7. exact FastMCP mount/auth propagation APIs для выбранной pinned FastMCP version.

Это implementation choices, которые должны быть зафиксированы в sequence до coding handoff, но не требуют смены архитектуры.
