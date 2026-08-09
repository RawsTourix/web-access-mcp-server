# Roadmap Web Access MCP

## Статус документа

Канонический владелец **порядка реализации принятой архитектуры по версиям**.

Roadmap не переопределяет component design/ADR. Каждая версия реализует часть уже принятых contracts и обязана проходить собственный Definition of Done + applicable release gates.

---

# 1. Общий dependency graph

```text
v0.1 Service Foundation
→ v0.2 Search Runtime
→ v0.3 Retrieval & Content Core
→ v0.4 Managed Browser Runtime
→ v0.5 Native Content Expansion
→ v0.6 Durable Jobs Runtime
→ v0.7 Distributed Operations & Policy Hardening
→ v0.8 REST/MCP & Agent Integration Stabilization
→ v0.9 Production Hardening
→ v1.0 Stable Web Access
```

Это dependency order, а не утверждение, что разработчик обязан делать каждый commit строго последовательно, если independent work не нарушает prerequisites. Release acceptance следует цепочке.

---

# 2. Что означает v0.x

`v0.x` здесь не означает MVP/одноразовый код.

Каждая версия должна:

- реализовывать законченный архитектурный слой;
- не закладывать заведомый shortcut, который следующая версия обязана переписать;
- иметь explicit non-goals;
- проходить applicable unit/contract/race/fault/security gates;
- сохранять предыдущие invariants;
- быть пригодной foundation следующей версии.

До v1.0 public contracts могут корректироваться быстрее, но только через явный design/compatibility review, особенно после v0.8 freeze candidate.

---

# 3. v0.1 — Service Foundation

## Цель

Production-oriented каркас без premature web logic.

## Scope

- `src/web_access` layered package;
- FastAPI + FastMCP Control Plane;
- common OperationResult/Error/Hint contracts;
- AuthProvider/PrincipalContext baseline;
- PostgreSQL/SQLAlchemy async/Alembic/UnitOfWork;
- Redis lifecycle foundation;
- ContentStore port + filesystem adapter;
- structured observability foundation;
- health/readiness;
- Docker Compose;
- CI/architecture/contract tests.

## Non-goals

Search/Retrieval/Content public API/Browser/Jobs.

## Status

`ready for implementation`

---

# 4. v0.2 — Search Runtime

## Цель

Первый полноценный web capability через общий backend + REST + MCP.

## Scope

- Search domain/application;
- provider registry;
- SearXNG default free provider;
- optional direct Yandex Search provider;
- common language/region mapping;
- explicit/default provider selection;
- batch-first search;
- Redis cache/rate/concurrency controls;
- provider health/usage metadata;
- REST Search API;
- MCP `web_search`.

## Critical invariant

```text
Search result ≠ target page content
```

No hidden provider fallback.

## Status

`ready for implementation`

---

# 5. v0.3 — Retrieval & Content Core

## Цель

Известный URL становится непосредственно читаемым без Browser, если native content доступен.

## Retrieval

- safe arbitrary HTTP(S) GET;
- SSRF/DNS rebinding/redirect/TLS protection;
- bounded streaming/decompression;
- deadlines/cancellation;
- batch-first retrieval.

## Content

- durable ContentObject lifecycle;
- staged/finalized filesystem storage;
- L0 Inspection;
- initial L1 registry:
  - HTML;
  - text;
  - JSON;
  - XML;
  - CSV;
  - PDF native text;
- isolated risky parser executor;
- immutable derived representations/provenance;
- bounded Content read/cursor;
- REST Content/Retrieval;
- MCP `web_fetch`, `content_get`, `content_parse`.

## Critical invariant

```text
L0/L1 only
no Browser/OCR/LibreOffice/VLM hidden fallback
```

## Status

`ready for implementation`

---

# 6. v0.4 — Managed Browser Runtime

## Цель

Stateful browser capability, независимая от MCP connection и single API process.

## Scope

- Browser Worker supervisor runtime;
- one BrowserSession subprocess per session;
- one Chromium + non-persistent BrowserContext per session baseline;
- direct authenticated Control Plane→worker RPC;
- PostgreSQL authoritative session owner generation;
- Redis worker registry/route cache;
- worker lease/self-fencing;
- semantic snapshots/exact `element_ref`;
- serialized actions/action status recovery;
- first-class `unknown`;
- pages/popups/dialogs;
- screenshot/rendered/download/upload through Content;
- TTL/reaper/drain/loss;
- public-only browser egress gateway;
- REST Browser facade;
- MCP Browser tools according current `mcp.md`/ADR-0022.

## Critical invariant

Browser is expensive explicit capability, not hidden `web_fetch` mode.

## Status

`ready for implementation`

---

# 7. v0.5 — Native Content Expansion

## Цель

Расширить direct L1 reading и production shared ContentStore, не превращая сервис в L2 document processor.

## Scope

- SafePackageReader;
- parser isolation profiles;
- direct L1:
  - DOCX/XLSX/PPTX;
  - ODT/ODS/ODP;
  - EPUB/FB2;
  - SVG textual structure;
- image technical metadata;
- optional audio technical metadata;
- macro/formula/external resource execution forbidden;
- S3-compatible ContentStore;
- common filesystem/S3 contract tests.

## Non-goals

OCR/VLM/LibreOffice conversion/transcription/legacy Office conversion.

## Status

`ready for implementation`

---

# 8. v0.6 — Durable Jobs Runtime

## Цель

Durable background execution только для явно typed long-running workloads.

## Runtime

```text
PostgreSQL Job + JobItems + Outbox
→ arq wake-up
→ PostgreSQL Attempt claim/lease/fencing
→ typed Job handler
```

## Initial workloads

```text
retrieval_batch
content_parse_batch
```

Persistent JobItem checkpoints позволяют после worker crash продолжать незавершённые items, не повторяя successful items.

## MCP

Per ADR-0021:

```text
web_fetch         direct
web_fetch_job     creates durable Job
content_parse     direct
content_parse_job creates durable Job
job_get
job_cancel
```

No argument-sensitive direct/durable execution class.

## Non-goals

Crawl, durable Browser workflows, arbitrary task runner.

## Status

`ready for implementation`

---

# 9. v0.7 — Distributed Operations & Policy Hardening

## Цель

Сделать multi-replica/multi-principal service управляемым без code changes/redeploy для каждого non-secret operational policy.

## Scope

- revisioned PostgreSQL dynamic PolicySnapshot;
- bounded policy staleness/replica refresh;
- principal capability/soft-limit policy;
- durable Browser/Job/Content quota accounting;
- billable provider unit reservation/accounting;
- Job fairness;
- retention classes;
- protected admin REST;
- typed worker drain/maintenance;
- transactional operator/security audit;
- usage reconciliation;
- capability-aware detailed readiness;
- S3 production profile hardening.

## Critical invariant

Dynamic policy can restrict existing authority, not mint missing authentication scope or exceed software hard ceilings.

## Status

`ready for implementation`

---

# 10. v0.8 — REST/MCP & Agent Integration Stabilization

## Цель

Стабилизировать внешний contract перед production hardening.

## Scope

- generated deterministic REST OpenAPI fixture;
- generated actual MCP tool/schema fixture;
- contract manifest/fingerprints;
- common error/resource/cursor review;
- exact MCP freeze candidate ADR-0022;
- one stable execution class per MCP tool;
- public-contract diff CI gate;
- generic MCP client acceptance;
- representative REST client acceptance;
- coordinated builtin integration with `internet-search-bot`;
- Browser cleanup/unknown end-to-end;
- durable Job integration end-to-end.

## Freeze candidate MCP catalog

Canonical owner remains `mcp.md`; version does not duplicate schema definitions beyond acceptance references.

## Status

`ready for implementation`

---

# 11. v0.9 — Production Hardening

## Цель

Доказать operational correctness существующей системы, не добавляя capabilities.

## Scope

- dependency/image reproducibility;
- migration drills;
- PostgreSQL + ContentStore backup/restore;
- Redis destructive recovery;
- Browser/Job/parser/Content long soak;
- race/fault/chaos matrices;
- capacity characterization;
- saturation/backpressure;
- rolling upgrade/rollback;
- secret rotation;
- security/supply-chain scans;
- alert validation;
- runbook game days;
- production smoke;
- release evidence;
- known limitations register.

## Critical invariant

Hardening cannot be used as feature creep or reason to silently drift v0.8 public contracts.

## Status

`ready for implementation`

---

# 12. v1.0 — Stable Web Access

## Цель

Объявить первую stable contract line **только после** выполнения release checklist конкретным v0.9-proven candidate.

## Stable promises

- `/api/v1` compatibility policy;
- stable MCP semantic catalog;
- stable resource/lifecycle semantics;
- upgrade/migration discipline;
- production restore/operations evidence;
- own-agent + generic client compatibility;
- additive-by-default future evolution.

v1.0 не является feature big bang.

## Release condition

[`versions/v1.0/release-checklist.md`](versions/v1.0/release-checklist.md) полностью evidenced, release blockers absent.

## Status

`release contract defined`

---

# 13. Почему именно такой порядок

### Search раньше Retrieval

Позволяет получить первый полезный capability без риска arbitrary URL parser/browser surface.

### Retrieval + Content раньше Browser

Browser screenshots/downloads/rendered content должны сразу использовать нормальный Content boundary.

### Browser раньше Native Content Expansion

Основной web workflow становится завершённым; дальнейшее количество direct document formats не блокирует browser capability.

### Native Content Expansion раньше Jobs

Durable `content_parse_batch` опирается на уже определённый parser registry/isolation.

### Jobs раньше Policy Hardening

Multi-principal quotas/fairness должны учитывать реальный durable resource model, а не абстрактный будущий job.

### Policy раньше Contract Freeze

External stable errors/admin/readiness должны freeze-иться уже после operational policy model.

### Contract Freeze раньше Hardening

v0.9 должен проверять один release-candidate contract, а не постоянно меняющийся facade.

### Hardening раньше v1.0

Stable contract без restore/race/security/soak evidence не считается production stability.

---

# 14. Правило изменения roadmap

Новая идея не вставляется в roadmap автоматически.

Сначала определить:

1. является ли это capability Web Access;
2. меняет ли она existing invariant;
3. нужна ли отдельная ADR/component design;
4. какие prerequisites;
5. additive ли она после v1.0.

Например:

```text
crawl
```

не является «ещё одним флагом Retrieval» и требует отдельного design перед добавлением в future roadmap.

---

# 15. Implementation source of truth

Для coding agent:

```text
roadmap
→ target version README
→ relevant Design/ADR
→ target implementation-sequence
→ tests/release-gates
```

Roadmap сам по себе недостаточен для написания production code.
