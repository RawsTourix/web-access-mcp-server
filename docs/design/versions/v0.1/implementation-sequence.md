# v0.1 — Implementation sequence

## Статус

`ready for implementation`

Этот документ задаёт patch-oriented последовательность реализации `v0.1 Service Foundation`.

Codex/ChatGPT должен выполнять этапы по порядку и после каждого этапа сохранять предыдущие gates зелёными. Нельзя добавлять Search, Retrieval, Browser, Native Parsing или Jobs раньше соответствующих версий.

---

# 1. Зафиксированные implementation choices

## 1.1 Dependency management

Использовать:

```text
uv
pyproject.toml
uv.lock
```

Требования:

- `uv.lock` commit-ится;
- CI/install используют lock;
- runtime не выполняет floating dependency install;
- production dependency versions воспроизводимы.

## 1.2 Python

Baseline:

```text
Python >=3.11,<3.13
```

Первая реализация и CI должны использовать Python 3.11 как minimum compatibility target. Позднее supported matrix можно расширить отдельным patch.

## 1.3 FastMCP/FastAPI composition

Использовать проверенный pattern существующего KudaGo-сервиса:

```text
FastMCP instance
→ mcp.http_app()
→ mount в общий FastAPI root application
→ объединённый lifespan
```

Pinned FastMCP major line:

```text
fastmcp >=3,<4
```

Точная minor/patch версия фиксируется `uv.lock` после compatibility test.

Не создавать отдельный MCP process и не проксировать MCP через REST.

## 1.4 Logging

Использовать:

```text
structlog
+
stdlib logging
+
contextvars
```

Requirements:

- JSON renderer production;
- console developer renderer optional;
- `operation_id`, `request_id`, `trace_id` добавляются через context;
- secrets/redacted fields не сериализуются;
- third-party stdlib logs проходят тот же logging pipeline насколько возможно.

## 1.5 Metrics

Использовать:

```text
prometheus-client
```

для `/metrics` и низкокардинальных service metrics.

## 1.6 Tracing

Использовать OpenTelemetry-compatible stack:

```text
opentelemetry-api
opentelemetry-sdk
opentelemetry-instrumentation-fastapi
```

Exporter должен быть optional/configurable. Если exporter не настроен, application остаётся работоспособной.

SQLAlchemy/Redis auto-instrumentation можно добавлять только после проверки пользы/кардинальности; v0.1 не обязана включать каждый instrumentation package.

## 1.7 Opaque IDs

Использовать prefixed UUID4 hex strings:

```text
op_<32 hex>
cnt_<32 hex>
brs_<32 hex>
job_<32 hex>
```

Для v0.1 реально используются только типы, нужные foundation/tests.

Requirements:

- `uuid.uuid4().hex`;
- prefix является presentation/type guard, но client не парсит ID;
- отдельный `IdGenerator`/factory injection point для tests;
- DB PK позднее может быть UUID/native type, public ID contract от этого не зависит.

## 1.8 Bearer principals config

Поддержать два mutually exclusive source modes:

### Local/simple env

```text
WEB_ACCESS_AUTH__PRINCIPALS=<JSON array>
```

Пример shape:

```json
[
  {
    "principal_id": "builtin-agent",
    "tokens": ["<secret>"],
    "scopes": ["*"]
  }
]
```

### Secret file

```text
WEB_ACCESS_AUTH__PRINCIPALS_FILE=/run/secrets/web_access_principals.json
```

Формат файла тот же.

Rules:

- одновременно задать оба нельзя;
- token fields представлены `SecretStr`/secret type;
- startup требует хотя бы одного principal, кроме explicit test profile;
- duplicate token/principal ambiguity rejected;
- multiple active tokens одного principal поддерживают rotation.

## 1.9 FastMCP auth integration

Не создавать второй независимый список токенов FastMCP.

Реализовать adapter текущего FastMCP 3.x auth/token-verification API, который использует **тот же configured principal registry/AuthProvider**, что и REST.

Если pinned FastMCP API предоставляет `TokenVerifier`/эквивалентный extension point, использовать собственный verifier adapter.

Requirements:

```text
Bearer token
→ single AuthProvider/credential registry
→ REST PrincipalContext
→ MCP PrincipalContext
```

FastMCP-specific auth object остаётся transport adapter и не протекает в application layer.

Точный вызов API FastMCP должен быть подтверждён integration test against locked version; не копировать непроверенную сигнатуру из памяти.

## 1.10 Filesystem ContentStore physical keys

Использовать content-addressed physical blob layout на SHA-256:

```text
<root>/blobs/sha256/<first2>/<sha256>
<root>/staging/<random>.part
```

Flow:

```text
stream → staging file
→ incremental sha256 + size
→ flush/close
→ atomically publish to hash path
→ return StoredBlob(key, sha256, size)
```

Если target hash уже существует и размер/integrity совпадает:

- staging удаляется;
- существующий physical blob переиспользуется.

Это **physical dedup optimization**, а не Resource ownership merge. В v0.1 ContentObject metadata ещё не реализуется.

## 1.11 Filesystem atomicity

Staging и final blob directory должны находиться на одном filesystem/root, чтобы `os.replace`/atomic rename semantics были доступны.

Нельзя staging писать в system temp на другом volume, а потом считать rename atomic.

Production-strength fsync policy не является blocker v0.1 и уточняется при Content durability hardening; tests должны проверять отсутствие partially published final blob.

---

# 2. Patch F0 — repository/tooling skeleton

## Цель

Создать installable repository skeleton и CI baseline без runtime logic.

## Создать

- `pyproject.toml`;
- `uv.lock`;
- `src/web_access/__init__.py`;
- package directories из v0.1 README;
- `tests/` structure;
- `.gitignore`;
- `.env.example`;
- basic `README.md`;
- lint/type/test config;
- GitHub Actions baseline.

## Dependencies

Runtime foundation deps только из v0.1 README + choices выше.

Dev:

- `pytest`;
- `pytest-asyncio`;
- `httpx` для ASGI tests;
- chosen lint/type tools;
- architecture/import checker dependency только если custom AST test недостаточен.

### Static tool choice

Использовать:

```text
ruff
pyright
```

- Ruff: formatting + lint.
- Pyright: static typing.

Начальный pyright режим: `standard`, но запрещать новые implicit unknown/obvious typing regressions через CI. Переход к stricter mode может быть отдельным hardening patch после появления codebase.

## Tests/gates

- package imports from installed environment;
- `ruff check`;
- `ruff format --check`;
- `pyright`;
- empty pytest suite infrastructure.

## Non-goals

Никаких FastAPI/database/auth классов в этом patch.

---

# 3. Patch F1 — core IDs/time/config

## Реализовать

### `core/ids.py`

- typed prefix helper;
- UUID4 public ID generator;
- fake/deterministic test generator.

### `core/time.py`

- UTC wall clock;
- monotonic deadline helper;
- fake Clock for tests.

### `core/config.py`

Typed settings composition:

```text
AppSettings
AuthSettings
DatabaseSettings
RedisSettings
ContentStoreSettings
ObservabilitySettings
SecuritySettings
Settings
```

Requirements:

- `WEB_ACCESS_` prefix;
- nested delimiter `__`;
- principals env/file parsing;
- production-safe validation;
- secrets redacted from repr.

## Tests

- env parsing;
- secret file parsing;
- both sources conflict;
- duplicate/empty principals;
- malformed URLs;
- secret not shown repr/log;
- fake Clock/ID deterministic.

---

# 4. Patch F2 — application common contracts

## Реализовать

`application/common/`:

- `context.py`;
- `results.py`;
- `errors.py`;
- `hints.py`;
- `auth.py`;
- common protocols.

Use Pydantic/dataclasses pragmatically:

- public/serialization-oriented models: Pydantic v2;
- pure internal immutable value objects may use frozen dataclasses if clearer.

Do not create one giant BaseModel for every object.

## Canonical enums

Implement outcomes/categories exactly from design.

## Batch helper

Central deterministic aggregate-outcome function.

## Deadline/cancellation

Create application-neutral primitives; do not import `asyncio.Task` as public contract unnecessarily.

A lightweight cancellation token/interface can wrap `asyncio.Event` internally.

## Tests

All `application-contracts.md` acceptance invariants.

---

# 5. Patch F3 — auth/policy foundation

## Infrastructure

`infrastructure/auth/static_bearer.py`:

- loaded credential registry;
- constant-time comparison;
- multiple tokens/principal;
- scopes;
- no raw-token logging.

## Application

Reusable authorization helpers/port:

```text
require_scope
require_owner
```

Keep policy engine small; do not invent RBAC DSL.

## REST adapter

Parse standard Bearer header and map to PrincipalContext.

## MCP adapter

Use pinned FastMCP 3 auth verifier/provider extension point delegating to same credential registry.

## Tests

- valid/invalid/missing;
- rotation;
- two principals;
- scopes;
- constant-time comparison code path (behavioral; microbenchmark timing not required);
- no raw token logs;
- FastAPI + FastMCP auth parity.

---

# 6. Patch F4 — PostgreSQL/UoW/Alembic foundation

## `infrastructure/database/`

- async engine factory;
- sessionmaker;
- declarative metadata base;
- `SqlAlchemyUnitOfWork`;
- transaction context;
- health probe.

## UoW contract

Application-facing UoW protocol should not expose `AsyncSession` as part of common business signatures.

Implementation may expose repository registry properties later; v0.1 can provide transaction lifecycle + synthetic test repository.

## Commit semantics

```text
async with uow:
    ...
    await uow.commit()
```

or equivalent explicit method.

Exiting without commit rolls back.

Repository never commits.

## Alembic

- environment configured against same SQLAlchemy metadata;
- empty baseline migration allowed;
- migration container/command.

## Tests

Real PostgreSQL:

- commit;
- rollback;
- exception rollback;
- concurrent sessions;
- connection recovery;
- empty DB → head;
- single migration head.

---

# 7. Patch F5 — Redis foundation

Implement only:

- async Redis client factory;
- lifecycle;
- ping/health;
- safe close/reconnect behavior;
- typed minimal Redis dependency wrapper if helpful.

Do **not** implement premature:

- JobQueue;
- locks;
- cache abstraction;
- worker registry.

Those belong consumer versions.

Tests real Redis restart/connectivity.

---

# 8. Patch F6 — filesystem ContentStore foundation

## Port

Create storage-level port separate from future ContentApplicationService.

Conceptual methods:

```text
write_stream/stage
open_stream
stat
exists
remove
```

Return storage metadata object, not local path as public application ResourceRef.

## Adapter

Implement SHA-256 layout from §1.10.

Streaming implementation must avoid loading full object into RAM.

Use bounded blocking file I/O through `asyncio.to_thread`/small async file adapter; do not add heavy dependency solely for trivial file calls unless benchmark justifies it.

## Security

- generated paths only;
- root containment check;
- no client filename path;
- random staging names;
- permissions sensible;
- symlink/path traversal resistant within managed root.

## Tests

- stream roundtrip;
- concurrent same-content writes;
- atomic final publication;
- hash/size;
- remove;
- missing;
- staging cleanup failure/reconciliation helper;
- root escape attempts.

---

# 9. Patch F7 — structured observability

## Logging

Configure `structlog` + stdlib bridge.

Create request/operation context helpers using `contextvars`.

## Metrics

`prometheus-client` registry + foundation metrics.

Do not label by request/resource IDs.

## Tracing

OpenTelemetry SDK provider configuration:

- no-op/default exporter if not configured;
- OTLP exporter may be optional dependency/profile if chosen;
- FastAPI instrumentation;
- manual application operation spans helpers.

Do not make collector availability readiness-critical.

## Tests

- JSON output;
- context fields;
- redaction;
- no secret;
- low-cardinality metric labels;
- exporter disabled/failing does not break app.

---

# 10. Patch F8 — health/status model

Implement capability-aware foundation even though business capabilities not yet present.

Schemas:

```text
DependencyStatus
RuntimeStatus
ServiceStatus
```

Endpoints later mapped by REST.

Dependency probes:

- PostgreSQL;
- Redis;
- filesystem ContentStore.

Do not perform side effects.

Semantics:

- liveness purely process;
- readiness startup/mandatory deps per profile;
- detailed status reports degraded dependencies.

Tests outage/recovery.

---

# 11. Patch F9 — bootstrap/lifespan composition

Create composition root.

No dependency clients at import time.

App factory preferred:

```python
create_app(settings: Settings | None = None) -> FastAPI
```

Stable production target may export:

```python
app = create_app()
```

if Uvicorn ergonomics requires it, but tests primarily call factory.

Build:

- settings;
- logging/metrics/tracing;
- auth;
- DB;
- Redis;
- ContentStore;
- health registry;
- REST/MCP adapters.

Shutdown in reverse order.

---

# 12. Patch F10 — FastAPI REST foundation

Implement:

```text
/health/live
/health/ready
/health/status
/metrics
```

Application `/api/v1` can expose a minimal authenticated service metadata endpoint only if useful; do not create fake CRUD.

### Auth policy

- `/health/live`: unauthenticated;
- `/health/ready`: unauthenticated but minimal/redacted;
- `/health/status`: authenticated, requires diagnostic/admin-capable scope;
- `/metrics`: default internal/network-protected; optionally auth middleware per deployment, not exposed public Compose port separately.

### Error handling

Introduce common REST envelope and override FastAPI validation handler accordingly.

Actual OpenAPI contract tests required.

---

# 13. Patch F11 — FastMCP foundation

Create:

```text
transport/mcp/server.py
```

Pattern:

```text
FastMCP(... auth=FastMCPAuthAdapter(...))
→ http_app()
→ mount root FastAPI at /mcp
```

Use combined lifespan exactly as required by the **locked FastMCP version**, verified against KudaGo pattern and FastMCP official API.

No production business tools yet.

### Tests

Real MCP client:

- unauthorized connect/request rejected;
- authorized initialization;
- list_tools returns expected empty catalog;
- health of REST unaffected;
- PrincipalContext adapter tested via test-only registered fixture, not production catalog;
- FastMCP Context hidden from public schema.

---

# 14. Patch F12 — Docker/Compose/reference runtime

## Dockerfile

- Python 3.11 slim-compatible image;
- create non-root app user;
- install from uv lock reproducibly;
- install package;
- no dev dependencies runtime;
- entrypoint Uvicorn.

## Compose

Services:

```text
postgres
redis
migration
api
```

- healthchecks;
- migration waits DB then `alembic upgrade head`;
- api starts only after migration success;
- ContentStore named volume;
- DB/Redis not host-published by default;
- API port only published;
- bearer principals secret/config injected safely.

## Dev convenience

Document how to generate token and run.

---

# 15. Patch F13 — CI + full foundation acceptance

CI jobs:

### Static

- uv sync/check lock;
- Ruff;
- Pyright;
- architecture tests.

### Unit/contract

- common application;
- config/auth;
- REST OpenAPI;
- MCP actual schema/client.

### Integration

- real PostgreSQL;
- Redis;
- filesystem ContentStore;
- migration;
- ASGI/MCP.

### Compose smoke

From clean volumes:

```text
docker compose up/build
→ migration success
→ live/ready
→ REST auth behavior
→ MCP authenticated initialization
```

No internet/billable calls.

---

# 16. Architecture import rules to implement

At minimum tests enforce:

```text
domain
  cannot import application/transport/infrastructure/workers/bootstrap

application
  cannot import FastAPI/FastMCP/SQLAlchemy/redis concrete packages

transport
  cannot import infrastructure concrete providers except through bootstrap dependency injection

infrastructure
  may implement application ports

bootstrap
  may import all composition participants
```

Implementation may use a small allowlist for common `core` types.

---

# 17. Dependency versions policy

`pyproject.toml` uses intentional compatible ranges where appropriate, but `uv.lock` is execution source for CI/release.

Do not use `latest` runtime identifiers.

FastMCP pinned lock must be tested with KudaGo-compatible mounting pattern before v0.1 acceptance.

---

# 18. No speculative dependencies gate

At v0.1 acceptance, dependency tree must **not** include solely for future use:

```text
playwright
trafilatura
pypdf
openpyxl
python-docx
python-pptx
arq
searxng client package
```

HTTPX may exist transitively/test-side due FastAPI/FastMCP and is allowed, but Retrieval application is not implemented.

---

# 19. Documentation updates during implementation

At final patch:

- `docs/design/current.md` marks v0.1 implemented/pending acceptance or accepted;
- `docs/design/versions/README.md` status updated;
- README gains local setup;
- actual config/env examples synchronized;
- implementation choices that diverged from this sequence require design/ADR update first.

---

# 20. Final acceptance checklist

All v0.1 README criteria + gates must pass.

Release evidence should record:

- commit SHA;
- locked Python/dependency versions;
- FastMCP version;
- migration head;
- test counts;
- skips reasons;
- Ruff/Pyright status;
- OpenAPI/MCP contract checks;
- Compose smoke result;
- billable/network external calls = 0.

После этого v0.1 получает статус `accepted`, а v0.2 Search implementation может начинаться.
