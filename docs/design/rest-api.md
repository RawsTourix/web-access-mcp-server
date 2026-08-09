# REST API facade design

## Статус документа

Этот документ является каноническим владельцем **семантики и архитектурных правил REST facade** Web Access.

Точное freeze-candidate дерево `/api/v1`, DTO, bounds и request/response schemas принадлежит:

```text
contracts/rest-api-v1.md
```

Общие public result/error/resource shapes:

```text
contracts/common-models.md
```

Generated FastAPI OpenAPI в v0.8 должен соответствовать этим specs.

---

# 1. Purpose

REST — богатый typed programmatic facade общего application backend.

Он предназначен для:

- других сервисов;
- web/admin UI;
- automation clients;
- integrations;
- operator/admin workflows;
- diagnostics/resource access.

REST предоставляет больше control/detail, чем MCP, но не становится infrastructure/library proxy.

---

# 2. Backend-first invariant

Flow:

```text
HTTP request
→ transport auth/validation
→ mapper
→ Application Service
→ OperationResult/resource stream
→ REST projection
```

Router не должен напрямую:

- обращаться к SQLAlchemy repository/Redis;
- вызывать provider client;
- выполнять parser logic;
- управлять Playwright/session subprocess;
- создавать hidden retry/fallback semantics.

REST и MCP не вызывают друг друга; оба используют общий application layer.

---

# 3. REST DTO отделён от application model

REST schema проектируется для программного клиента.

Нормально:

```text
RestSearchQuery
→ mapper
→ Application SearchQuery
```

REST может иметь более широкий batch/timeout-safe control, pagination/admin resources и streaming semantics, чем MCP.

Нельзя переиспользовать ORM/provider/Playwright model как public DTO ради удобства.

---

# 4. Versioning

Stable application namespace:

```text
/api/v1
```

Breaking public contract после v1 freeze требует compatibility/deprecation/version strategy из `compatibility.md`.

Package/build version не равен REST API major version.

---

# 5. JSON operations и streams

Control/application operations обычно используют JSON `PublicOperationResult`.

Большой Content payload:

```text
GET content data
→ streaming bytes/text
```

а не base64/giant JSON.

Successful byte stream не оборачивается JSON envelope; ошибки до начала stream используют normalized REST error contract.

---

# 6. Result/error semantics

JSON operations сохраняют common application concepts:

```text
operation_id
outcome
data
error
warnings
hints
```

Canonical outcomes:

```text
succeeded
partial
failed
rejected
cancelled
unknown
```

Batch partial success обычно возвращается `200` + per-item outcomes; `207 Multi-Status` не является generic baseline.

Raw FastAPI/Pydantic/SQLAlchemy/provider/Playwright exception не выходит наружу.

---

# 7. Authentication/ownership

Transport credentials преобразуются в trusted `PrincipalContext` через `AuthProvider`.

Client не передаёт owner/user ID как authority.

Каждый resource access:

```text
Content
BrowserSession/Page
Job
```

проверяет ownership/scopes/policy application-side.

Admin/operator endpoints имеют отдельные protected scopes.

---

# 8. REST capability groups

Stable v1 facade покрывает:

```text
Search
Retrieval
Content
Browser
Jobs
Admin/Policy
Operational health/metrics
```

Exact routes — `contracts/rest-api-v1.md`.

---

# 9. Search REST

REST Search:

- batch-first;
- разрешает per-query stable options;
- provider выбирается явно/configured default;
- возвращает normalized results/cache/pagination/usage metadata;
- имеет provider discovery/status read capability;
- не читает target pages;
- не раскрывает Yandex/SearXNG raw protocol.

REST limits шире MCP, но bounded hard contract/policy limits остаются обязательными.

---

# 10. Retrieval REST

REST Retrieval:

```text
known HTTP(S) URLs
→ Safe Retrieval
→ optional explicit processing_level
```

Stable processing levels:

```text
store_only
inspect
native
```

REST не является unrestricted HTTP client. Public v1 не принимает arbitrary:

- method;
- request body;
- headers;
- proxy;
- DNS resolver;
- redirect allowlist;
- client-selected security bypass.

---

# 11. Content REST

REST предоставляет:

- Content metadata;
- immutable Content data stream;
- representation/provenance view;
- batch L0 inspection;
- request-bound L1 native parse.

Нет endpoints вида:

```text
/read-pdf
/read-docx
/read-xlsx
```

Parser registry остаётся backend detail/capability.

No L2 OCR/VLM/LibreOffice in v1 Web Access REST.

Direct arbitrary local filesystem path never accepted.

---

# 12. Browser REST

Browser REST — resource/action API поверх Browser application/runtime.

Stable concepts:

```text
BrowserSession
Page
Snapshot/ElementRef
Navigation
Typed Actions
Rendered Content
Screenshot
Events
Content-based Upload
```

REST может иметь больше stable session options, batch/list diagnostics и optimistic revision checks, чем MCP.

Но public v1 не принимает:

- raw Playwright kwargs;
- browser executable/CDP endpoint;
- CSS/XPath core actions;
- coordinates scripts;
- arbitrary JavaScript evaluate;
- local server path.

---

# 13. Browser action semantics

Typed action endpoints сохраняют разные intents; не используется generic unrestricted `POST /actions {type,args}` как public v1 baseline.

Причины:

- ясный OpenAPI;
- разные side-effect/retry semantics;
- разные schemas;
- permission evolution;
- меньше raw framework leakage.

Internal worker protocol может использовать typed command union независимо от public REST shape.

---

# 14. Unknown outcome

Mutating Browser action может завершиться `unknown`, если после возможного side effect недостаточно evidence доказать terminal result.

REST documentation/client helpers обязаны считать это first-class state.

`Idempotency-Key` **не делает** click/type/press/navigation blind-retry-safe.

Verification read/snapshot обычно предпочтительнее повторного mutating call.

---

# 15. Content artifacts from Browser

Screenshot/download/rendered content становятся `ContentObject`/`ContentRef`.

REST не возвращает giant base64 screenshot/download temp path.

BrowserSession close не удаляет уже финализированный ContentObject автоматически.

---

# 16. Jobs REST

Public durable Job creation — только typed domain operations.

Baseline v1:

```text
retrieval batch job
content native-parse batch job
```

Lifecycle:

- get status/progress;
- cancel;
- read events;
- owner list.

Нет public:

```text
POST /jobs {"task":"python.function","args":...}
```

Queue/worker IDs не являются public Job API.

---

# 17. Admin/policy REST

v1 protected operator facade предоставляет только stable operational abstractions:

- revisioned non-secret policy snapshot/update;
- capability/status summary;
- Browser Worker capacity/status diagnostics;
- Job/outbox backlog summary.

Admin API не раскрывает secrets/DSN/internal Redis payloads и не становится SQL/Redis console.

Dynamic policy не может:

- выдать scope, которого нет у authenticated principal;
- превысить software/deployment hard ceiling;
- хранить credentials/secrets.

---

# 18. Operational endpoints

Liveness, readiness и metrics могут находиться вне `/api/v1`.

Liveness означает здоровье процесса/event loop, а не здоровье каждой внешней dependency.

Readiness — capability-aware:

```text
ready
degraded
not_ready
```

Redis/SearXNG/Browser Worker outage должен отражаться в конкретной capability, а не обязательно превращать весь сервис в один boolean `down`.

---

# 19. Pagination/cursors

Server-owned collections используют opaque cursor-based pagination.

Search provider page number — отдельная semantics.

Client не конструирует и не модифицирует cursor.

Cursor scoped/versioned к query/filter/order; incompatible reuse rejected.

---

# 20. Idempotency-Key

Idempotency поддерживается только там, где exact contract явно её определяет для **resource/job creation**.

Same principal + endpoint + key + same canonical request может replay logical create result.

Same key + changed request → conflict.

Не распространять эту semantics на mutating Browser interactions.

---

# 21. Request/response bounds

REST богаче MCP, но остаётся bounded:

- JSON body/item/string hard ceilings;
- typed filters/sorting;
- no SQL-like expressions;
- no giant inline Content;
- streaming for data;
- cursor pagination;
- bounded diagnostics.

Operator policy может быть строже, но не шире software contract hard ceiling без version/design change.

---

# 22. OpenAPI как contract artifact

FastAPI-generated OpenAPI является public executable contract.

В v0.8 он:

1. генерируется детерминированно;
2. проверяется против `contracts/rest-api-v1.md`;
3. сохраняется как golden fixture;
4. CI показывает meaningful diff;
5. contract change классифицируется compatibility policy.

Проверяется:

- paths/methods/operationIds;
- security;
- required/default/bounds/enums;
- discriminated unions;
- common errors;
- streaming media types;
- admin protection;
- отсутствие infrastructure leakage.

---

# 23. Язык документации

Project-owned OpenAPI descriptions/summary преимущественно русские.

Identifiers/field names/codes остаются английскими.

---

# 24. Explicit v1 exclusions

REST v1 не предоставляет:

```text
raw HTTP proxy
raw provider passthrough
raw SQL/Redis
raw Playwright/CDP
arbitrary JS/code execution
local server filesystem paths
generic arbitrary jobs
L2 processing
CAPTCHA/stealth controls
BrowserSession live migration
```

Эти ограничения зафиксированы также в `limitations.md`.

---

# 25. Exact contract

Любая реализация REST v1 должна дополнительно соответствовать:

```text
contracts/common-models.md
contracts/rest-api-v1.md
compatibility.md
```

Если code/framework limitation мешает exact contract, это design review issue, а не разрешение silently изменить public API.
