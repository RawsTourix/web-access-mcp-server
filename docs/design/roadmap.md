# Roadmap Web Access MCP

## Статус документа

Этот документ является каноническим владельцем **порядка реализации принятой архитектуры по версиям**.

Roadmap не переопределяет component design. Каждая версия реализует часть уже принятых contracts и обязана ссылаться на канонические документы.

Подробные implementation plans создаются в `docs/design/versions/` после закрытия ADR/open decisions соответствующего scope.

---

# 1. Принцип roadmap

Версии упорядочены по dependency graph:

```text
Foundation
→ Search
→ Retrieval + Content Core
→ Managed Browser
→ Native Content Expansion
→ Durable Jobs
→ Distributed/Operator Hardening
→ Contract & Agent Integration Stabilization
→ Production Hardening
→ v1.0
```

Нельзя реализовать Browser раньше Content foundation, потому что screenshots/downloads/rendered content должны использовать Content boundary.

Нельзя делать production Jobs раньше persistence/outbox foundation.

---

# 2. Что означает pre-1.0 version

`v0.x` — законченный архитектурный этап, но public API/MCP contract ещё может развиваться быстрее, чем после `v1.0`.

Это не означает MVP-качество.

Каждая версия обязана:

- не закладывать заведомый технический долг в core boundaries;
- проходить applicable release gates;
- иметь explicit non-goals;
- сохранять предыдущие invariants;
- быть пригодной как foundation следующего этапа.

---

# 3. v0.1 — Service Foundation

## Цель

Создать production-oriented каркас сервиса без преждевременной web capability logic.

## Scope

- `src/web_access` layout;
- domain/application/transport/infrastructure/bootstrap/entrypoints boundaries;
- typed configuration;
- OperationResult/Error/Hint/Warning foundation;
- Principal/Owner minimal model;
- ResourceRef/content/job/browser ID primitives;
- FastAPI + FastMCP в одном Control Plane app;
- PostgreSQL + SQLAlchemy async + Alembic;
- Redis connectivity/adapters foundation;
- ContentStore port + filesystem adapter;
- UnitOfWork/transaction foundation;
- structured logging/operation IDs;
- liveness/readiness/status foundation;
- service authentication baseline;
- Docker Compose reference stack;
- migration command;
- CI/static/unit/contract infrastructure;
- architecture import tests.

## Non-goals

- Search;
- external Retrieval;
- Native Parsers;
- Browser;
- durable user Jobs;
- rich REST/MCP business tools.

## Required gates

G0–G6, G12, foundation parts G15/G21.

---

# 4. v0.2 — Search Runtime

## Цель

Получить первый полноценный web capability через общий backend + REST + MCP.

## Scope

- Search domain/application;
- SearchProvider registry/port;
- SearXNG adapter;
- private SearXNG Compose service;
- optional Yandex Search adapter;
- provider capabilities;
- explicit/default provider selection;
- batch-first Search;
- cache/freshness;
- provider rate/capacity controls;
- billable usage accounting foundation;
- provider health/degraded state;
- REST `POST /api/v1/search`;
- provider discovery/status REST;
- MCP `web_search`;
- actual OpenAPI/MCP schema tests;
- controlled SearXNG integration.

## Non-goals

- чтение найденных страниц;
- auto provider fallback;
- Browser;
- image/video search;
- live billable provider calls в default CI.

## Required gates

G0–G7, G12–G15, G20/G21 для MCP integration.

---

# 5. v0.3 — Retrieval & Content Core

## Цель

Сделать известный URL непосредственно читаемым для агента/REST без Browser, если native content доступен.

## Scope Retrieval

- SafeHttpFetcher;
- SSRF/redirect/DNS/egress protections;
- bounded streaming GET;
- TLS;
- deadlines/cancellation;
- batch-first Retrieval;
- HTTP response normalization;
- Content handoff.

## Scope Content

- ContentObject metadata/resource lifecycle;
- filesystem ContentStore production-quality local profile;
- staged/finalized ingest + reconciliation;
- L0 Inspection;
- ContentFormatRegistry;
- NativeParser abstraction/executor;
- initial parser set sufficient for web use:
  - HTML;
  - plain text;
  - JSON;
  - XML;
  - CSV/tabular text;
  - PDF native text;
- HTML main-content + structural metadata;
- PDF image-only/no-native-text diagnostics;
- derived ContentObjects/provenance;
- bounded content read/cursor foundation.

## REST

- Retrieval fetch;
- Content metadata/data;
- Native Parsing existing content.

## MCP

- `web_fetch`;
- `content_get`;
- `content_parse`.

## Non-goals

- Browser fallback;
- OCR/VLM;
- LibreOffice conversion;
- exhaustive Office/media support;
- generic file conversion.

## Required gates

G0–G9, G12–G15, G17, G20/G21.

---

# 6. v0.4 — Managed Browser Runtime

## Цель

Добавить полноценную stateful browser capability без привязки к MCP connection и без single-process shortcut.

## Scope

- separate Browser Worker runtime/image;
- Playwright Python + Chromium;
- ephemeral BrowserSession;
- worker registry/identity/generation;
- session placement/capacity;
- owning-worker routing protocol;
- lease/fencing policy;
- session action serialization;
- page identities/popups;
- semantic snapshot;
- snapshot-scoped element refs;
- navigation;
- typed interactions;
- tabs/pages;
- screenshots → Content;
- rendered page → Content;
- downloads → Content;
- uploads from Content;
- bounded browser events;
- TTL/max lifetime/reaper;
- worker drain/loss;
- `unknown outcome`;
- private/internal browser egress protection;
- Browser REST API;
- Browser MCP tools approved for this version.

## Explicit ADR prerequisites

До implementation должны быть закрыты:

1. Control Plane ↔ Browser Worker transport.
2. Worker registry/lease/fencing protocol.
3. Snapshot/ElementRef representation/resolution strategy.
4. Dialog handling policy.
5. Browser service authentication.

## Non-goals

- persistent browser profiles;
- unrestricted JavaScript evaluate;
- stealth/CAPTCHA bypass;
- durable browser workflows;
- automatic Browser launch from Retrieval.

## Required gates

G0–G6, G10, G12–G17, G19/G20/G21; Browser load baseline begins here.

---

# 7. v0.5 — Native Content Expansion

## Цель

Расширить L1 Native Parsing, не превращая Web Access в L2 document-processing service.

## Scope

После отдельной library/security evaluation добавляются прямые parsers/inspectors, где они инженерно оправданы.

Приоритетные families:

- OOXML: DOCX/XLSX/PPTX;
- ODF: ODT/ODS/ODP и совместимые непосредственно читаемые структуры;
- EPUB/FB2;
- SVG;
- bitmap image L0 metadata;
- additional safe tabular/text formats;
- media technical metadata, если выбран bounded inspector;
- optional legacy direct parsers только при безопасной библиотеке.

Дополнительно:

- isolated parser executor для riskier L1 parsers;
- parser registry/revision tooling;
- expanded format fixture/security corpus;
- representation schema stabilization;
- ContentStore S3-compatible adapter.

## Non-goals

- OCR;
- VLM;
- LibreOffice fallback;
- transcription;
- «поддерживать любой файл любой ценой».

## Required gates

G0–G6, G9, G12–G17, G19/G21 по Content scope.

---

# 8. v0.6 — Durable Jobs Runtime

## Цель

Добавить устойчивое explicit background execution для long-running/batch workloads.

## Scope

- Job/JobAttempt persistence;
- Transactional Outbox;
- Outbox publisher;
- Redis/arq JobQueue adapter;
- worker capability registry;
- claim/lease/fencing;
- retry_wait/backoff;
- cancellation;
- progress/events;
- reconciler;
- Job REST lifecycle;
- MCP `job_get` / `job_cancel`;
- первые **typed** durable operations, выбранные после отдельного design.

В качестве первых candidates рассматриваются:

- durable large Retrieval batch;
- job-required Content Native Parsing;
- bounded crawl, только если предварительно создан отдельный `crawl.md` design.

## Non-goals

- generic arbitrary task execution;
- cron scheduler;
- durable browser click workflow;
- infinite retry.

## Required gates

G0–G6, G11–G17, G19–G21.

---

# 9. v0.7 — Distributed Operations & Policy Hardening

## Цель

Довести уже распределённую архитектуру до устойчивой multi-replica/multi-principal эксплуатации под реальной нагрузкой, **не переписывая core runtime**.

## Scope

- principal/owner policy hardening;
- quotas/fairness;
- operator/admin REST surface;
- capability/provider/parser/worker diagnostics;
- S3 production profile hardening;
- Redis cache vs coordination split, если load evidence требует;
- HA outbox/reconciler;
- health/readiness finalization;
- rolling deployment compatibility matrices;
- configuration revision/operational controls;
- retention/cleanup administration;
- rate/cost budgets;
- audit policy для security-sensitive actions;
- load-driven capacity defaults.

## Non-goals

- создание пользовательских аккаунтов как отдельного identity product;
- новый reasoning layer;
- архитектурный rewrite single-node→distributed: distributed assumptions уже должны существовать раньше.

## Required gates

Все применимые G0–G21, включая load/soak/rolling subsets для hardened capabilities.

---

# 10. v0.8 — REST/MCP & Agent Integration Stabilization

## Цель

Зафиксировать внешний contract перед production-hardening и будущим `v1.0`.

## Scope

- REST endpoint/schema audit;
- MCP catalog/schema audit;
- Russian descriptions/docs polish;
- public error taxonomy stabilization;
- ResourceRef/cursor shapes stabilization;
- OpenAPI compatibility fixtures;
- FastMCP tool schema compatibility fixtures;
- own `internet-search-bot` builtin integration;
- trusted presentation metadata mapping;
- BrowserSession lifecycle cleanup integration;
- agent retry semantics/unknown outcome verification;
- generic MCP client compatibility;
- optional generated REST client/SDK evaluation;
- protocol/version negotiation where needed.

## Non-goals

- major new backend capability;
- breaking architecture changes без нового design.

## Required gates

G0–G6, G12–G17, G20–G21 + full schema compatibility suite.

---

# 11. v0.9 — Production Hardening

## Цель

Прожарить всю систему до production-ready состояния.

## Scope

- complete fault-injection matrix;
- randomized race suite;
- Browser/Job/Content soak;
- load baselines/performance budgets;
- security review/threat model closure;
- dependency/container scans;
- backup/restore/DR drills;
- Redis loss recovery;
- rolling upgrade tests;
- leak/resource accounting;
- alert/SLO baseline;
- operator runbooks;
- release evidence/report automation;
- all previous open implementation questions resolved for v1 scope.

## Non-goals

- feature expansion;
- L2 processing.

## Required gates

Полный применимый набор G0–G21.

---

# 12. v1.0 — Stable Web Access

## Цель

Объявить текущий public REST/MCP/application behavior стабильной первой major contract line.

## Требования

- v0.9 gates green;
- no unresolved implementation-critical architecture questions;
- REST v1 compatibility policy опубликована;
- MCP core catalog/version policy опубликована;
- migration/upgrade path документирован;
- own-agent integration production accepted;
- generic MCP client accepted;
- backup/restore/runbooks validated;
- performance/capacity defaults основаны на измерениях;
- security gates closed.

`v1.0` не означает «в проект больше нечего добавить». Он означает, что foundation/contracts можно развивать additive образом без постоянной смены основных границ.

---

# 13. Dependency graph

```text
v0.1 Foundation
   │
   ├──→ v0.2 Search
   │       │
   │       └──────────────┐
   │                      │
   └──→ v0.3 Retrieval + Content Core
               │          │
               ├──→ v0.4 Browser
               │          │
               ├──→ v0.5 Content Expansion
               │          │
               └──→ v0.6 Jobs ←────────┘
                           │
                           ▼
                  v0.7 Operations/Policy
                           │
                           ▼
                  v0.8 Contract/Agent
                           │
                           ▼
                  v0.9 Hardening
                           │
                           ▼
                         v1.0
```

v0.4/v0.5 теоретически могут разрабатываться независимо после v0.3, но canonical project sequence оставляет Browser раньше расширения форматов, поскольку Browser является core Web Access capability.

---

# 14. Почему Search раньше Retrieval

Search имеет более простую stateless provider boundary и позволяет:

- проверить FastAPI/FastMCP/application skeleton;
- проверить batch/result schemas;
- проверить provider adapters/cache;
- интегрировать первый полезный MCP tool;

до появления сложного Content storage/security pipeline.

---

# 15. Почему Retrieval и Content вместе в v0.3

Retrieval без Content быстро упирается в giant raw bytes/HTML.

Content без источника реального web content менее полезен.

Их contracts уже разделены архитектурно, но implementation milestone должен сразу обеспечить законченный flow:

```text
URL
→ safe Retrieval
→ raw ContentObject
→ L0/L1
→ bounded result/ContentRef
```

---

# 16. Почему Browser только после Content Core

Browser производит:

- screenshots;
- downloads;
- rendered HTML;

которые должны использовать уже готовую Content resource/storage/provenance model.

Иначе Browser неизбежно создаст собственное временное artifact storage, которое потом придётся мигрировать.

---

# 17. Почему Content Expansion после Browser

Широкая поддержка Office/ebook/media formats полезна, но не является prerequisite основного web-browsing workflow.

Core HTML/PDF/text достаточно, чтобы безопасно построить Browser first.

Parser registry позволит расширить formats additive без rewrite.

---

# 18. Почему Jobs после Browser/Content

Jobs должен оборачивать уже готовые application operations, а не становиться местом, где впервые появляется Search/Retrieval/Content logic.

Worker вызывает существующие services.

Это предотвращает duplicate «worker implementation» backend-а.

---

# 19. Почему scaling не отдельная поздняя переделка

Horizontal/multi-worker assumptions входят design с v0.1/v0.4.

v0.7 только hardening/operations:

```text
не: single-node → distributed rewrite
а: distributed design → production HA/policy tuning
```

---

# 20. ADR schedule

До detailed version implementation plans необходимо закрывать ADR **до версии, которая от него зависит**.

Минимально ожидаемые decisions:

## До v0.1

- baseline authentication/service-principal mechanism;
- application UoW/transaction implementation pattern;
- FastMCP/FastAPI mounting/bootstrap pattern;
- initial ContentStore filesystem finalization semantics.

## До v0.2

- SearchRegion/language common mapping;
- Yandex API/version adapter strategy;
- rate-limit/cache implementation choices.

## До v0.3

- SafeHttpFetcher DNS-rebinding/connect strategy;
- structural HTML parser;
- PDF native parser;
- Content staged/finalized write protocol;
- initial Native Parser set.

## До v0.4

- Browser Worker transport;
- worker registry/lease/fencing;
- ElementRef/snapshot implementation;
- dialog policy;
- browser internal auth/egress.

## До v0.5

- isolated Native Parser executor;
- S3-compatible adapter semantics;
- format library choices.

## До v0.6

- outbox publisher runtime placement;
- Job lease/cancellation signal;
- first typed job types;
- crawl design, если crawl входит version.

---

# 21. Version document requirements

Каждый version folder должен содержать минимум:

```text
README.md
implementation-sequence.md
```

При необходимости:

```text
migration-plan.md
compatibility.md
acceptance.md
```

Version README не дублирует component design целиком, а ссылается на него.

---

# 22. Patch granularity

Даже если Codex получает один большой запрос, implementation sequence внутри версии должен быть patch-oriented.

Например:

```text
contracts/models
→ ports/fakes/tests
→ infrastructure adapters
→ application service
→ REST
→ MCP
→ integration/fault tests
→ docs/status
```

Это позволяет независимо проверять состояние после каждого логического блока и уменьшает риск гигантского монолитного diff.

---

# 23. No speculative version features

Если capability не имеет component design, она не должна внезапно появиться внутри version implementation prompt.

Например bounded crawler сначала получает отдельный design, только затем включается в v0.6 scope.

---

# 24. Post-v1 candidates

За пределами текущего v1 roadmap могут рассматриваться:

- bounded/site crawling advanced policies;
- image/news/video search kinds;
- persistent encrypted browser profiles;
- advanced authorized browser evaluate;
- additional search providers;
- separate L2 document/media processing MCP-service;
- richer async MCP Tasks integration;
- user-facing admin/Web UI;
- distributed Content processing worker pool, если native parser load требует.

Они не должны усложнять v1 core без доказанной необходимости.

---

# 25. Roadmap acceptance

Roadmap считается готовым к подробному version planning, если:

1. Dependencies между версиями не требуют будущего архитектурного rewrite.
2. Каждая версия имеет полезный и проверяемый результат.
3. Core security/persistence не отложены «на потом» после capability release.
4. Browser строится сразу через proper worker boundary.
5. L2 processing остаётся отдельной ответственностью.
6. REST/MCP развиваются поверх backend каждого этапа.
7. v0.7 hardens scaling, а не впервые добавляет его.
8. v0.8 стабилизирует contracts после завершения основных capabilities.
9. v0.9 содержит hardening, а не feature rush.
10. v1.0 имеет ясный definition of stable contract.
