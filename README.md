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

**v0.2 Search Runtime accepted.**

Acceptance v0.1 остаётся зафиксирован на:

```text
3e5df8775f99cf15a30e17b56db740c08b00233c
```

Acceptance v0.2 зафиксирован на repository HEAD:

```text
a6af55ba5e6b2781af580f335342e356a8fbe747
```

Search доступен через REST и MCP. Остальные Web Access capabilities ещё не реализованы. v0.3 Retrieval & Content Core — следующий разрешённый implementation milestone; v0.3 ещё не начат.

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

## Локальный запуск v0.2 Search Runtime

Требуются Docker Engine с Compose v2. Скопируйте `.env.example` в `.env` и заполните все три обязательных значения. Например, URL-safe значения можно сгенерировать менеджером секретов или `openssl rand -hex 32`.

Reference stack содержит Control Plane, PostgreSQL, Redis, private SearXNG и one-shot migration:

```bash
docker compose up --build
```

После успешного запуска:

```text
REST liveness   http://127.0.0.1:8000/health/live
REST readiness  http://127.0.0.1:8000/health/ready
REST Search      http://127.0.0.1:8000/api/v1/search
MCP              http://127.0.0.1:8000/mcp/
```

Detailed status требует scope `admin:read`; REST Search и единственный production MCP tool `web_search` требуют `search:read`. Оба фасада используют один bearer registry и общий SearchApplicationService. Search возвращает metadata/snippets и не читает содержимое найденных страниц.

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
