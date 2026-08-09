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

**Design первой stable line v1.0 сформирован. Production implementation ещё не начат.**

Следующий implementation milestone:

```text
v0.1 — Service Foundation
```

Реализация идёт строго version-by-version с acceptance gates.

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
