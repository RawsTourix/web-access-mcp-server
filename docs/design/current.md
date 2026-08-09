# Текущее состояние design-проектирования Web Access MCP

## Назначение

Краткий factual status проекта. Канонические contracts принадлежат соответствующим Design/ADR/`contracts/*`; этот файл только показывает состояние и следующий допустимый шаг.

---

# 1. Общий статус

**Архитектурный design первой stable line v1.0 сформирован. Production-код Web Access ещё не реализован.**

Закрыты:

```text
Concept
→ architecture foundation
→ component design
→ runtime/persistence/security
→ REST/MCP facade semantics
→ accepted ADR
→ exact public DTO/contracts
→ roadmap v0.1..v1.0
→ implementation sequences
→ testing/release/operational gates
```

Следующий implementation milestone:

```text
v0.1 Service Foundation
```

Version-by-version order обязателен; design readiness поздней версии не разрешает перепрыгнуть acceptance prerequisites.

---

# 2. Core architecture

Основные application areas:

```text
Search
Retrieval
Content
Browser
Jobs
```

Cross-cutting foundation:

- `principles.md`;
- `glossary.md`;
- `dependency-rules.md`;
- `system-context.md`;
- `runtime-topology.md`;
- `application-contracts.md`;
- `resource-model.md`;
- `persistence.md`;
- `security.md`.

Главные invariants:

- backend-first;
- REST/MCP share application backend;
- PostgreSQL durable source of truth;
- Redis cache/coordination/queue signal, not durable truth;
- ContentStore large immutable payloads;
- opaque owner-bound resources;
- no hidden Search→Fetch→Browser/L2 orchestration;
- `unknown outcome` first-class;
- security/recovery designed before implementation shortcuts.

---

# 3. Runtime topology

```text
Control Plane
Job Worker
Browser Worker supervisor
BrowserSession subprocess
```

BrowserSession process model:

```text
1 logical session
→ 1 child Python process
→ 1 Playwright runtime
→ 1 dedicated Chromium
→ bounded Pages
```

Browser control and website egress are separate trust paths.

External/runtime services:

```text
PostgreSQL
Redis
ContentStore
SearXNG
optional Yandex Search
Browser Egress Gateway
```

---

# 4. Component/operations design

Canonical:

- `search.md`;
- `retrieval.md`;
- `content.md`;
- `browser.md`;
- `jobs.md`;
- `observability.md`;
- `policy-and-operations.md`;
- `operational-readiness.md`;
- `limitations.md`.

L0 Inspection/L1 Native Parsing входят Web Access.

L2 OCR/VLM/LibreOffice/transcription остаётся внешней responsibility.

---

# 5. Important ADR chains

Registry: `decisions/README.md`.

```text
Browser
→ ADR-0001, 0009..0014, 0025

Content
→ ADR-0007, 0008, 0015, 0016

Jobs
→ ADR-0017, 0018, 0021

Policy/usage/admin authority
→ ADR-0019, 0020, 0023

MCP external contract
→ ADR-0021, 0022, 0024, 0025
```

ADR-0012 и ADR-0022 частично superseded; читать их вместе с более поздними ADR и current exact contracts.

---

# 6. Public facades

Semantic owners:

- `rest-api.md`;
- `mcp.md`;
- `compatibility.md`;
- `agent-integration.md`.

Exact contracts index: `contracts/README.md`.

Current exact specs:

```text
contracts/common-models.md
contracts/mcp-tools.md
contracts/rest-api-v1.md
contracts/browser-api-v1.md
contracts/policy-models.md
contracts/admin-api-v1.md
```

MCP freeze candidate: **28 semantic tools**.

Not in core MCP:

- raw Playwright/HTTP;
- admin/operator tools;
- L2 processing;
- generic Job/code runner.

REST v1 is richer and includes protected Admin/Operations namespace.

---

# 7. Final MCP refinements already accepted

Current contract includes:

- direct/durable split (`web_fetch` vs `web_fetch_job`, `content_parse` vs `content_parse_job`);
- cost/resource-aware retry semantics;
- explicit `browser_scroll` for bounded/lazy UI exploration;
- form fill sequential fail-fast + `not_attempted` remainder;
- structured key + modifiers for `browser_press`;
- multi-file ContentRef upload;
- no hidden active-tab state;
- exact ElementRef targeting/no fuzzy retargeting.

---

# 8. Policy/Admin refinements already accepted

Dynamic policy:

- revisioned PostgreSQL logical state;
- global defaults/maxima + exact principal override exceptions;
- durable quotas/billable accounting;
- task capabilities only.

According ADR-0023, `admin:read/admin:write` belongs to AuthProvider/deployment control plane and cannot be self-disabled by mutable dynamic task policy.

Exact Admin REST covers policy revisions/rollback, overrides, usage/providers, audit, worker drain and bounded typed maintenance.

---

# 9. Version design status

```text
v0.1 Service Foundation                         ready for implementation
v0.2 Search Runtime                             ready for implementation
v0.3 Retrieval & Content Core                   ready for implementation
v0.4 Managed Browser Runtime                    ready for implementation
v0.5 Native Content Expansion                   ready for implementation
v0.6 Durable Jobs Runtime                       ready for implementation
v0.7 Distributed Operations & Policy Hardening  ready for implementation
v0.8 REST/MCP & Agent Integration Stabilization ready for implementation
v0.9 Production Hardening                       ready for implementation
v1.0 Stable Web Access                          release contract defined
```

Это design status, не implementation status.

---

# 10. Release evidence

Canonical:

- `testing.md`;
- `release-gates.md`;
- `deployment.md`;
- `operational-readiness.md`.

По мере версий обязательны contract/integration/race/fault/restart/security/soak/load/migration/restore/rolling evidence, а не один happy-path pytest.

---

# 11. Designed exclusions

См. `limitations.md`.

v1 baseline намеренно не обещает:

- L2 processing;
- CAPTCHA bypass/stealth;
- arbitrary JS/code execution;
- raw HTTP proxy;
- generic arbitrary Job runner;
- persistent browser profiles;
- live BrowserSession migration;
- automatic research/orchestration layer.

Это non-goals, не defects.

---

# 12. Следующий шаг

Design-phase feature expansion **остановлен**. Новые capability не следует добавлять без новой реальной requirement/review.

Перед coding v0.1:

```text
docs/AGENTS.md
→ this current.md
→ v0.1 foundation Design/ADR
→ versions/v0.1/README.md
→ versions/v0.1/implementation-sequence.md
→ testing/release gates
```

Дальше реализация идёт только по v0.1 scope до factual acceptance.
