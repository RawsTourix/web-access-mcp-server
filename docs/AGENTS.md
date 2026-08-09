# AGENTS.md — правила работы с Web Access MCP

## Назначение

Обязательные правила для Codex/ChatGPT/другого coding agent.

Проект production-oriented. Coding agent должен **реализовывать принятую архитектуру и target version**, а не заменять её упрощённым MVP/shortcut.

---

# 1. Перед любой production-работой

1. Проверить фактический HEAD/status/diff.
2. Прочитать `docs/README.md` и `design/current.md`.
3. Определить target version + exact patch step.
4. Прочитать:
   - `design/principles.md`;
   - `design/dependency-rules.md`;
   - relevant component/cross-cutting Design;
   - **все current relevant accepted ADR**, включая поздние cross-version refinements;
   - relevant `design/contracts/*`;
   - target version README;
   - target implementation sequence/release checklist;
   - `design/testing.md`;
   - applicable `design/release-gates.md`.
5. Проверить acceptance prerequisites предыдущего шага/версии.

Краткий task prompt не заменяет repository design context.

---

# 2. Canonical owners

```text
application execution/outcome/retry/batch
→ design/application-contracts.md

resource ownership/lifecycle
→ design/resource-model.md

persistence/consistency
→ design/persistence.md

Browser semantics
→ design/browser.md + current Browser ADR

Jobs
→ design/jobs.md + Jobs ADR

Policy/quotas/operator semantics
→ design/policy-and-operations.md + ADR-0019/0020/0023

MCP semantic facade
→ design/mcp.md

exact MCP DTO/catalog
→ design/contracts/mcp-tools.md

REST semantic facade
→ design/rest-api.md

common REST exact baseline
→ design/contracts/rest-api-v1.md

Browser REST exact
→ design/contracts/browser-api-v1.md

dynamic policy exact
→ design/contracts/policy-models.md

Admin REST exact
→ design/contracts/admin-api-v1.md

common public models
→ design/contracts/common-models.md

compatibility
→ design/compatibility.md
```

Specific contract wins for its namespace, but cannot override lifecycle/security semantics Design/ADR.

---

# 3. Conflict precedence

```text
latest accepted/non-superseded ADR + canonical Design semantics
→ exact specialized public contract
→ target version README
→ implementation sequence
→ concept docs
```

Superseded ADR is history, not alternative implementation.

Examples:

- ADR-0012 direct ownership part superseded by ADR-0013;
- ADR-0022 count/retry wording refined by ADR-0024/0025;
- dynamic `admin` capability prohibited by ADR-0023.

---

# 4. Version boundaries

Canonical order:

```text
v0.1 → v0.2 → v0.3 → v0.4 → v0.5 → v0.6 → v0.7 → v0.8 → v0.9 → v1.0
```

`ready for implementation` is design status, not permission to skip previous acceptance.

Implementation sequence is mandatory patch order.

Do not add later roadmap capability «заодно».

---

# 5. Forbidden shortcuts

Без explicit accepted design change нельзя:

- помещать business logic в FastAPI/FastMCP handlers;
- запускать Playwright in-process в Control Plane request handler;
- хранить authoritative durable state only RAM/Redis;
- заменять outbox/claim/fencing прямым `DB commit → Redis enqueue`;
- доверять client `user_id` как identity;
- ослаблять SSRF/browser egress/parser/session isolation;
- автоматически запускать Browser/OCR/LibreOffice/provider fallback;
- добавлять generic raw HTTP/Playwright/JS/shell/Python public primitive;
- создавать `*_many` alias вместо batch-first schema;
- создавать MCP tool на каждый file parser;
- объединять direct call и durable Job creation в один MCP tool;
- смешивать read-only/mutating intents ради меньшего tool count;
- использовать CSS/XPath core MCP targeting вместо ElementRef;
- скрывать scroll внутри snapshot;
- давать Browser child DB/Redis/ContentStore/provider credentials;
- считать «read-oriented» operation automatically retry-safe, игнорируя cost/resource creation;
- добавлять dynamic `admin` task capability;
- отключать failing race/security/fault test ради green run.

---

# 6. Backend-first

```text
transport
→ application
→ domain/ports
← infrastructure adapters
```

REST/MCP вызывают общий application layer и не вызывают друг друга в baseline composition.

Provider/library/ORM/worker types не становятся public application model.

---

# 7. Exact public contracts

Всегда сначала читать `design/contracts/README.md`.

Exact current target:

```text
common public models
→ common-models.md

MCP 28-tool target
→ mcp-tools.md

normal REST
→ rest-api-v1.md

Browser REST
→ browser-api-v1.md

policy
→ policy-models.md

Admin REST
→ admin-api-v1.md
```

Rules:

- unknown input fields rejected;
- required/default/min/max/enums/list bounds machine-readable;
- unions/discriminators present in actual generated schema;
- runtime validation repeats/strengthens schema validation;
- omission/null/default not conflated;
- no private DB/Redis/provider/worker/Playwright fields;
- contract drift requires explicit Design/ADR/contracts change.

---

# 8. MCP rules

Current freeze candidate = **28 tools**.

- Russian agent-facing descriptions;
- every nested field described;
- one tool = one primary semantic intent/execution class;
- batch only for independent items or one designed compound action;
- large result → ContentRef/cursor;
- credentials never tool args;
- no selectors/raw JS/local paths/admin controls;
- `browser_scroll` explicit, no auto-scroll snapshot;
- `browser_fill_form` sequential fail-fast, later fields `not_attempted`;
- `browser_press` structured key + modifiers;
- `browser_upload` accepts bounded ContentId list for multi-file controls;
- FastMCP annotations + own-agent retry descriptors obey ADR-0024.

Actual FastMCP client schema tests mandatory.

---

# 9. Retry/cost/resource rules

Read `application-contracts.md` + ADR-0024.

Critical examples:

```text
web_search
→ may dispatch billable provider
→ no blind Agent-level replay after ambiguous result

web_fetch
→ creates Content resources
→ no blind duplicate acquisition

content_parse
→ idempotent only after canonical representation reuse proved

Browser mutating actions including scroll
→ no blind retry after dispatch uncertainty

cleanup/cancel
→ idempotent only according exact contract
```

`PublicError.retryable=true` does not override stronger operation semantics.

---

# 10. REST rules

REST is rich typed facade, not infrastructure console.

- use specialized exact contract by namespace;
- auth/owner/scope checks application-side;
- common result/error models;
- Content bytes stream, not base64 JSON;
- only designed Idempotency-Key operations;
- Browser HTTP method/header does not make mutation blind-retry-safe;
- Admin API requires `admin:read/admin:write` + deployment boundary;
- dynamic task policy cannot self-disable Admin control plane;
- no raw SQL/Redis/Playwright/provider leakage;
- generated OpenAPI contract-tested.

---

# 11. Security

Web input untrusted.

Never silently weaken:

- URL/DNS/redirect/TLS checks;
- Browser public-only egress;
- BrowserSession subprocess boundary;
- parser process isolation;
- package/decompression/input/output limits;
- owner/resource authorization;
- secret redaction;
- temp/path safety;
- quotas/backpressure;
- internal service auth.

Library incompatibility with security boundary = blocker/design issue.

---

# 12. Persistence/consistency

```text
PostgreSQL → authoritative durable structured state
Redis      → cache/coordination/flow/queue wake-up/route cache
ContentStore→ immutable large payloads
```

Repositories do not hidden-commit.

Crash windows require explicit state/reconciler/fault tests.

Content/Job/Browser use revision/CAS/fencing according design.

---

# 13. Browser rules

Canonical:

```text
Browser Worker supervisor
→ one BrowserSession subprocess
→ Playwright
→ dedicated Chromium
```

Per session:

- serial action lane;
- internal action ID/ledger/status recovery;
- exact ElementRef identity/stale validation;
- no fuzzy retargeting;
- explicit scroll;
- artifact handoff to Content;
- response-loss may become `unknown`;
- TTL/reaper independent of MCP connection.

Do not implement superseded direct Browser Worker ownership model.

---

# 14. Policy/Admin rules

Dynamic policy exact task capabilities:

```text
search
retrieval
content.read
content.parse
browser.read
browser.interact
jobs.read
jobs.create
```

No `admin` value.

Admin authority:

```text
AuthProvider admin:read/admin:write
+ deployment/network boundary
```

Policy can restrict task capability/quota/provider admission, not mint scopes or self-lock policy recovery.

Admin mutation is typed/bounded/audited; no generic command/SQL/Redis/shell endpoint.

---

# 15. Tests

For changed scope run applicable:

```text
unit
schema/contract
integration
migration
race/concurrency
fault injection
restart/recovery
security
browser lifecycle
soak/leak
load/backpressure
REST/OpenAPI
actual FastMCP schemas
e2e
```

Flaky failure is defect until explained. One green rerun is not evidence.

---

# 16. Documentation with code

- `design/current.md` changes only after factual verification;
- version status changes only from evidence;
- public contract divergence is reviewed Design/ADR/contracts change first;
- v0.8+ generated fixtures update only through compatibility process;
- no silent architecture rewrite in code comments.

---

# 17. Reference repositories

Useful implementation references:

```text
RawsTourix/kudago-nominatim-mcp-server
RawsTourix/internet-search-bot
```

Reuse proven patterns/contracts, not hidden runtime dependency/copy without design.

---

# 18. Completion report

Final coding-agent report includes:

- target version/patch;
- changed files;
- migrations/config/dependencies;
- exact test results;
- applicable race/security/fault/load evidence;
- unresolved defects/limitations;
- public contract impact;
- next step allowed by implementation sequence.

Do not state «готово» if applicable gate not checked.
