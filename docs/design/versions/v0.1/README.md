# v0.1 — Service Foundation

## Статус

`implemented, pending acceptance`

Версия создаёт production-oriented фундамент Web Access без преждевременной web capability logic.

Подробный порядок реализации: `implementation-sequence.md`.

---

# 1. Цель

После v0.1 сервис должен:

- запускаться локально через Docker Compose;
- иметь общий FastAPI + FastMCP Control Plane;
- аутентифицировать REST/MCP clients;
- создавать trusted `PrincipalContext`;
- иметь PostgreSQL/Redis/ContentStore infrastructure foundation;
- иметь typed configuration;
- иметь canonical application result/error/hint contracts;
- иметь liveness/readiness/status foundation;
- иметь structured logging/metrics/tracing extension points;
- иметь migration/test/CI foundation.

v0.1 намеренно **не выполняет Search/Retrieval/Browser/Job business work**.

---

# 2. Canonical design

Обязательны:

- `../../principles.md`;
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
- ADR-0002 authentication/principal baseline.

---

# 3. Non-goals

Не реализуются:

- Search providers;
- `web_search`;
- arbitrary external HTTP Retrieval;
- ContentObject public application API;
- Native Parsers;
- Browser Worker/Playwright;
- Job Worker/arq/outbox runtime;
- public Jobs;
- OCR/L2 processing;
- end-user account/OIDC product.

Не добавлять «временную» Search/Playwright функцию ради demo.

---

# 4. Repository/package baseline

```text
src/web_access/
├── core/
├── domain/common/
├── application/common/
├── transport/rest/
├── transport/mcp/
├── infrastructure/
│   ├── auth/
│   ├── database/
│   ├── redis/
│   ├── content/
│   └── observability/
├── bootstrap/
└── entrypoints/api.py

alembic/
tests/
docs/
Dockerfile
docker-compose.yml
pyproject.toml
uv.lock
```

- Python `>=3.11`;
- `src` layout;
- package `web_access`;
- `uv` + committed reproducible `uv.lock`;
- runtime imports independent of repository working directory.

---

# 5. Initial dependencies

Foundation only:

- FastAPI;
- Uvicorn;
- FastMCP 3.x compatible line;
- Pydantic v2;
- pydantic-settings;
- SQLAlchemy 2 async;
- asyncpg;
- Alembic;
- Redis asyncio client;
- observability/test dependencies.

Не устанавливать заранее:

- Playwright;
- Trafilatura;
- pypdf;
- arq;
- Office/media parsers.

---

# 6. Configuration

Единый typed `Settings` composition root с prefix:

```text
WEB_ACCESS_
```

Группы conceptually:

```text
AppSettings
AuthSettings
DatabaseSettings
RedisSettings
ContentStoreSettings
ObservabilitySettings
SecuritySettings
```

- secrets через secret-aware types/references;
- production-required config fail-fast;
- insecure developer defaults не переходят автоматически в production;
- startup log может показывать безопасный config summary без secret values.

---

# 7. Common application contracts

Реализовать фундамент из `application-contracts.md`:

```text
OperationId
ExecutionContext
PrincipalContext
OperationOutcome
OperationResult[T]
OperationError
Warning
StructuredHint
deadline/cancellation foundation
batch/partial invariants
```

Даже до business batch capabilities unit tests фиксируют общие semantics.

---

# 8. IDs and time

Opaque IDs используют один server generator baseline:

```text
type prefix + UUID4 hex
```

Например будущие:

```text
cnt_<uuid4hex>
brs_<uuid4hex>
job_<uuid4hex>
```

Client не извлекает authorization/routing semantics из prefix.

Application timestamps UTC/timezone-aware; duration/deadline uses monotonic clock where possible.

Tests use injectable/fake clock/id generator; no real sleep for lifecycle correctness.

---

# 9. Authentication

ADR-0002 baseline:

```text
Authorization: Bearer
→ AuthProvider
→ StaticBearerAuthProvider baseline
→ PrincipalContext
```

Requirements:

- multiple configured service principals;
- scopes;
- constant-time token compare;
- overlap for rotation;
- no raw token logs/storage;
- REST/MCP use same provider;
- detailed status protected.

External bearer credentials are not MCP tool arguments.

---

# 10. Authorization foundation

Reusable application policy/helper for:

```text
require_scope
require_owner
```

или эквивалент.

Transport authentication и application resource authorization не смешиваются.

v0.1 tests prove principal/scope denial semantics.

---

# 11. PostgreSQL foundation

```text
PostgreSQL
SQLAlchemy 2 async
asyncpg
Alembic
```

Implement:

- async engine/session factory;
- declarative metadata;
- explicit `SqlAlchemyUnitOfWork`;
- Alembic environment;
- DB health probe;
- pool lifecycle.

Не создавать искусственные business tables ради демонстрации ORM.

Repositories never hidden-commit.

---

# 12. Alembic

- migration command separate from API startup;
- metadata import no application side effects;
- CI verifies one head;
- empty DB upgrade succeeds;
- production does not use `create_all()` as migration system.

---

# 13. Redis foundation

Создать async client lifecycle/health foundation.

v0.1 не создаёт premature generic cache/lock/queue abstractions без consumer module.

Redis outage:

- liveness remains alive;
- detailed readiness/capabilities may be degraded;
- behavior explicit.

---

# 14. ContentStore port foundation

Минимальный async-friendly storage port + filesystem adapter:

```text
stage/write stream
finalize
open/read stream
stat/exists
remove
```

Public `ContentObject` lifecycle появляется v0.3.

Filesystem adapter:

- configurable root;
- generated storage keys;
- no user filename as path;
- no traversal;
- staging/finalization-friendly layout;
- bounded streaming, no giant RAM buffer.

---

# 15. FastAPI + FastMCP bootstrap

Использовать проверенный KudaGo-style pattern:

```text
create FastMCP separately
→ mcp.http_app(path="/")
→ combine FastAPI/MCP lifespans
→ mount at /mcp
```

REST `/api/v1` и MCP используют общий application/bootstrap container.

Не копировать KudaGo queued business execution в v0.1.

---

# 16. Health/readiness

Минимально:

```text
/health/live
/health/ready
protected detailed status
```

Liveness = process/event loop alive.

Readiness учитывает required foundation dependencies according deployment profile.

No secrets/DSN in health response.

---

# 17. Observability foundation

- structured JSON production logging;
- human-readable dev mode допустим;
- operation/request/trace correlation;
- redaction;
- Prometheus-compatible metrics foundation;
- OpenTelemetry tracing extension points;
- no raw web/business content in logs by default.

Concrete adapters remain replaceable infrastructure.

---

# 18. Docker Compose

Reference local stack:

```text
Control Plane
PostgreSQL
Redis
```

plus filesystem ContentStore volume.

No SearXNG/Browser Worker/Job Worker until their versions.

Requirements:

- one-command startup;
- health checks;
- non-secret example env;
- migration command documented;
- persistent DB volume;
- clean shutdown.

---

# 19. Testing

Required v0.1 layers:

- unit common contracts;
- config validation;
- auth positive/negative;
- owner/scope foundation;
- DB UoW/migration;
- Redis health;
- ContentStore adapter contract;
- actual mounted FastAPI/MCP smoke;
- architecture/dependency import tests;
- local Compose smoke.

---

# 20. Definition of Done

v0.1 complete only if:

1. Repository/package layout enforces dependency rules.
2. REST + MCP mount successfully through shared application bootstrap.
3. External auth creates trusted PrincipalContext.
4. PostgreSQL/Alembic/UoW foundation is explicit and testable.
5. Redis lifecycle/readiness is explicit.
6. Filesystem ContentStore passes storage contract tests.
7. Common OperationResult/Error/Hint contracts are implemented/tested.
8. Structured observability foundation works without secret leakage.
9. Docker Compose starts reproducibly.
10. No premature Search/Browser/Job implementation exists.
11. Applicable foundation release gates are green.
