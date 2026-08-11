# Roadmap Web Access MCP

## Статус

Канонический порядок реализации принятой архитектуры.

Roadmap не переопределяет Design/ADR/contracts. Version acceptance следует dependency chain.

---

# 1. Dependency graph

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

`v0.x` здесь не означает disposable MVP. Каждая версия должна быть production-oriented foundation следующей, без заведомого rewrite shortcut.

---

# 2. v0.1 — Service Foundation

## Цель

Production skeleton без premature web logic.

## Scope

- layered `src/web_access` package;
- FastAPI + FastMCP Control Plane;
- current application result/error/hint/outcome contracts;
- AuthProvider/PrincipalContext;
- PostgreSQL/SQLAlchemy async/Alembic/UoW;
- Redis lifecycle foundation;
- ContentStore port + filesystem adapter;
- structured observability;
- health/readiness;
- Docker Compose;
- CI/architecture/contract tests.

## Non-goals

Search/Retrieval/Browser/Jobs business capability.

**Status:** accepted.

Acceptance implementation HEAD:

```text
3e5df8775f99cf15a30e17b56db740c08b00233c
```

---

# 3. v0.2 — Search Runtime

## Scope

- Search domain/application/provider registry;
- SearXNG default free backend;
- optional direct Yandex Search adapter;
- common language/region model;
- explicit/default provider selection;
- batch-first Search;
- Redis cache/rate/concurrency;
- provider usage/readiness;
- REST Search;
- MCP `web_search`.

## Critical invariants

```text
Search result ≠ target page content
no hidden provider fallback
billable/read-oriented Search ≠ blind retry-safe
```

ADR-0024 applies to paid provider response-loss.

**Status:** accepted.

Acceptance repository HEAD:

```text
a6af55ba5e6b2781af580f335342e356a8fbe747
```

---

# 4. v0.3 — Retrieval & Content Core

## Scope

### Retrieval

- safe arbitrary HTTP(S) GET;
- SSRF/DNS rebinding/redirect/TLS protection;
- bounded streaming/decompression;
- deadlines/cancellation;
- batch-first retrieval.

### Content

- durable Content lifecycle/staged-finalized storage;
- L0 Inspection;
- initial L1 HTML/text/JSON/XML/CSV/PDF text;
- isolated risky parser executor;
- derived representations/provenance;
- bounded read/cursor;
- REST Retrieval/Content;
- MCP `web_fetch`, `content_get`, `content_parse`.

## Critical invariants

```text
L0/L1 only
no Browser/OCR/LibreOffice/VLM hidden fallback
web_fetch resource creation ≠ blind safe replay
content_parse idempotent only after canonical reuse proof
```

**Status:** ready for implementation. Next allowed milestone; not started.

---

# 5. v0.4 — Managed Browser Runtime

## Scope

- Browser Worker supervisor;
- one BrowserSession subprocess + dedicated Chromium per session;
- authenticated direct Control Plane→worker RPC;
- PostgreSQL owner/generation;
- Redis worker registry/route cache;
- lease/self-fencing;
- public-only Browser egress gateway;
- semantic snapshots/exact ElementRefs;
- serial action lane/action recovery/`unknown`;
- pages/popups/dialogs;
- explicit scroll for bounded/lazy UI exploration;
- fail-fast form fill;
- structured key press;
- multi-file ContentRef upload;
- screenshot/rendered/download artifacts through Content;
- TTL/reaper/drain/loss;
- exact Browser REST + MCP Browser subset.

## Critical invariant

Browser is expensive **explicit** capability, not hidden Retrieval mode.

Stateful action/result ambiguity never becomes blind retry.

**Status:** ready for implementation.

---

# 6. v0.5 — Native Content Expansion

## Scope

- SafePackageReader;
- parser isolation profiles;
- direct L1 OOXML (DOCX/XLSX/PPTX);
- ODF (ODT/ODS/ODP);
- EPUB/FB2/SVG textual structure;
- image technical metadata;
- optional audio technical metadata;
- S3-compatible ContentStore;
- common filesystem/S3 contract tests.

## Non-goals

OCR/VLM/LibreOffice conversion/transcription/legacy Office conversion.

**Status:** ready for implementation.

---

# 7. v0.6 — Durable Jobs Runtime

## Runtime

```text
PostgreSQL Job + JobItems + Outbox
→ arq wake-up
→ PostgreSQL Attempt claim/lease/fencing
→ typed Job handler
```

## Initial typed workloads

```text
retrieval_batch
content_parse_batch
```

Persistent JobItem checkpoints prevent rerunning already successful items after worker loss.

## MCP

ADR-0021:

```text
web_fetch / web_fetch_job
content_parse / content_parse_job
job_get / job_cancel
```

No argument-sensitive direct/durable mode.

## Non-goals

Crawl/durable Browser workflow/arbitrary task runner.

**Status:** ready for implementation.

---

# 8. v0.7 — Distributed Operations & Policy Hardening

## Scope

- revisioned PostgreSQL dynamic task policy;
- bounded replica staleness/refresh;
- exact task capability/default/max/principal override models;
- durable Browser/Job/Content quota accounting;
- billable provider unit reservation/accounting;
- Job fairness/backlog admission;
- retention defaults;
- protected Admin REST;
- policy revision history/rollback;
- provider/usage/audit diagnostics;
- generation-safe worker drain;
- typed bounded maintenance;
- transactional security/operator audit;
- usage reconciliation;
- capability-aware detailed readiness.

## Critical invariants

```text
dynamic policy restricts task authority, never mints scope
admin control plane authority lives in AuthProvider/deployment (ADR-0023)
dynamic policy cannot self-lock policy recovery
Redis is not durable quota/accounting truth
```

**Status:** ready for implementation.

---

# 9. v0.8 — REST/MCP & Agent Integration Stabilization

## Цель

Freeze external contract line before hardening.

## Exact target

```text
common public models
MCP 28-tool exact contract
normal REST v1
Browser REST v1
policy models
Admin REST v1
```

## Scope

- deterministic generated OpenAPI fixture;
- actual FastMCP schema/annotation fixture;
- public-model fixture;
- compatibility diff CI;
- ADR-0024 retry/resource/cost trusted mapping;
- own `internet-search-bot` builtin integration;
- BrowserSession cleanup/resource mapping;
- pretty progress metadata;
- generic MCP client acceptance;
- representative REST client acceptance;
- response-loss no duplicate paid/resource/stateful effects.

## Critical invariant

Do not freeze accidental framework schema. Actual runtime contract must first match reviewed `contracts/*` or design changes explicitly.

**Status:** ready for implementation.

---

# 10. v0.9 — Production Hardening

## Scope

- dependency/image reproducibility;
- migrations/restore drills;
- PostgreSQL + ContentStore backup/restore;
- Redis destructive recovery;
- Browser/Job/parser/Content soak;
- race/fault/chaos matrices;
- capacity/backpressure baselines;
- rolling upgrade/rollback;
- secret rotation;
- security/supply-chain scans;
- alert validation;
- operator runbook game days;
- production smoke;
- release evidence/known limitations.

## Critical invariant

Hardening cannot silently redesign v0.8 public contract or add features to make tests easier.

**Status:** ready for implementation.

---

# 11. v1.0 — Stable Web Access

## Stable promises

- REST `/api/v1` compatibility discipline;
- stable MCP semantic catalog/contracts;
- resource/lifecycle/ownership semantics;
- migration/upgrade discipline;
- production restore/operations evidence;
- own-agent + generic-client compatibility;
- additive-by-default evolution.

v1.0 is release declaration of a proven candidate, not feature big bang.

**Status:** release contract defined.

---

# 12. Почему порядок такой

```text
Foundation
→ first stateless capability (Search)
→ safe acquisition + Content boundary
→ stateful Browser built on Content
→ broader L1 formats/storage
→ durable Jobs wrapping existing operations
→ distributed policy/quota/admin
→ external contract freeze
→ production hardening
→ stable release
```

This prevents:

- Browser inventing temporary artifact model before Content;
- Jobs becoming a duplicate backend implementation;
- policy designing quotas for resources that do not yet exist;
- v1 contract freezing before runtime semantics are proven.

---

# 13. Roadmap change rule

Новая идея не добавляется автоматически.

Before roadmap change determine:

1. is it Web Access responsibility;
2. does it change current invariant/public contract;
3. does it need ADR/component design;
4. prerequisites;
5. can it be additive after v1.0.

Example:

```text
crawl
```

requires separate future design; it is not «another Retrieval flag».

---

# 14. Coding source of truth

```text
docs/AGENTS.md
→ current.md
→ target component/cross-cutting Design
→ current relevant ADR
→ relevant exact contracts
→ target version README
→ target implementation sequence
→ testing/release gates
```

Roadmap alone is insufficient for production implementation.
