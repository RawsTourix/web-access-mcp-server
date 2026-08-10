# Web Access MCP

Production-oriented Web Access service для ИИ-агентов и других программных клиентов.

Проект предоставляет единый backend для:

```text
Search
Retrieval
Content
Browser
Durable Jobs
```

с двумя публичными фасадами:

```text
REST API — богатый typed программный interface
MCP      — компактный LLM-friendly interface
```

## Статус

**v0.1 Service Foundation принят.**

Acceptance HEAD:

```text
3e5df8775f99cf15a30e17b56db740c08b00233c
```

Следующий разрешённый implementation milestone:

```text
v0.2 — Search Runtime
```

v0.2 готов к реализации по design, но его implementation ещё не начат. Реализация идёт строго version-by-version с acceptance gates.

## Основные принципы

- backend-first;
- общий application layer для REST/MCP;
- PostgreSQL как durable structured source of truth;
- Redis как cache/coordination/flow/queue signal, не единственная durable truth;
- ContentStore для больших immutable payloads;
- explicit Browser runtime с отдельными session subprocesses;
- no hidden Search→Fetch→Browser/OCR orchestration;
- L0 Inspection + L1 Native Parsing внутри Web Access;
- L2 OCR/VLM/LibreOffice/transcription вне core service;
- opaque owner-bound resources;
- cost/resource-aware retry semantics;
- production security/recovery/observability designed before coding shortcuts.

## Документация

Начальная точка:

```text
docs/README.md
```

Для coding agent обязательно:

```text
docs/AGENTS.md
→ docs/design/current.md
→ target Design/ADR/contracts
→ target version implementation sequence
→ testing/release gates
```

Основные каталоги:

```text
docs/design/decisions/   ADR
docs/design/contracts/   exact public REST/MCP/policy DTO
docs/design/versions/    version implementation plans
```

## MCP

Текущий v0.8 freeze candidate — **28 semantic tools**.

Он намеренно не включает:

- raw Playwright/CDP;
- arbitrary JavaScript/code execution;
- admin/operator controls;
- generic arbitrary Job runner;
- OCR/L2 processing.

Exact target:

```text
docs/design/contracts/mcp-tools.md
```

## REST

REST `/api/v1` является более богатым программным фасадом.

Exact target split:

```text
docs/design/contracts/rest-api-v1.md
docs/design/contracts/browser-api-v1.md
docs/design/contracts/policy-models.md
docs/design/contracts/admin-api-v1.md
```

## Reference integrations

Проект проектируется для совместимости с:

```text
RawsTourix/internet-search-bot
```

и использует проверенные engineering patterns из:

```text
RawsTourix/kudago-nominatim-mcp-server
```

при этом остаётся самостоятельным сервисом без runtime dependency на эти репозитории.

## Локальный запуск v0.1 Service Foundation

Требуются Docker Engine с Compose v2. Скопируйте `.env.example` в `.env` и замените оба placeholder. Например, URL-safe значения можно сгенерировать менеджером секретов или `openssl rand -hex 32`.

Reference stack содержит только Control Plane, PostgreSQL, Redis и one-shot migration:

```bash
docker compose up --build
```

После успешного запуска:

```text
REST liveness   http://127.0.0.1:8000/health/live
REST readiness  http://127.0.0.1:8000/health/ready
MCP              http://127.0.0.1:8000/mcp/
```

Detailed status требует `Authorization: Bearer <token>` и scope `admin:read` либо явно настроенный wildcard `*`. MCP использует тот же bearer registry. В production-каталоге v0.1 нет business tools — это ожидаемое состояние foundation.

Миграции выполняются отдельным one-shot service. Ручной повторный запуск безопасен:

```bash
docker compose run --rm migration
```

Остановка:

```bash
docker compose down
```

Удаление local development volumes выполняется только явно:

```bash
docker compose down --volumes
```

PostgreSQL и Redis по умолчанию не публикуют host ports. Наружу на loopback публикуется только общий REST/MCP Control Plane.
