# REST API facade design

## Статус документа

Этот документ является каноническим владельцем **REST projection application capabilities** Web Access MCP.

REST является богатым программным facade поверх общего application backend.

Он не является владельцем Search/Retrieval/Content/Browser/Jobs logic и не должен превращаться в raw proxy конкретных infrastructure libraries.

---

# 1. Purpose

REST API предназначен для:

- других микросервисов;
- Web UI;
- automation clients;
- административных/операторских interfaces;
- integration/debugging;
- полнофункционального программного доступа к backend capabilities.

REST должен предоставлять больше детализации и control, чем MCP, но сохранять стабильные application abstractions.

---

# 2. Base path и versioning

Application REST API публикуется под versioned prefix:

```text
/api/v1
```

Operational endpoints вроде liveness/metrics могут находиться вне application API namespace.

Breaking public contract требует новой API major version (`/api/v2`) или другого явно документированного migration mechanism.

Изменение application build version само по себе не меняет REST major version.

---

# 3. Backend-first invariant

Route выполняет только:

```text
HTTP request
→ transport validation/auth
→ mapper
→ Application Service
→ OperationResult
→ REST mapper
→ HTTP response
```

Router не должен:

- обращаться к SQLAlchemy repository напрямую;
- вызывать Redis;
- создавать HTTPX/Playwright clients;
- выполнять parser logic;
- реализовывать hidden retries/fallbacks.

---

# 4. Transport schemas отделены от application models

REST использует собственные Pydantic request/response schemas.

Например:

```text
REST SearchRequest
→ mapper
→ Application SearchBatchRequest
```

Schema reuse допускается только если transport и application semantics действительно полностью совпадают.

---

# 5. JSON control plane

Большинство REST control operations используют:

```text
application/json
```

Large Content binary/text payload выдаётся отдельными streaming/download endpoints, а не giant JSON/base64.

Uploads используют multipart/streaming endpoint только если upload capability включена соответствующей версией.

---

# 6. Общий response envelope

JSON application operations должны иметь согласованную форму, отражающую `OperationResult`.

Концептуально:

```json
{
  "operation_id": "...",
  "outcome": "succeeded",
  "data": {},
  "error": null,
  "warnings": [],
  "hints": [],
  "meta": {}
}
```

Не каждый binary stream endpoint обязан оборачивать bytes в JSON; metadata/error path для него проектируется отдельно.

---

# 7. HTTP status и application outcome

HTTP status является projection, а canonical application outcome остаётся в response body для JSON operations.

Общие правила:

- `succeeded` → 2xx;
- `partial_success` batch → обычно `200 OK` с `outcome=partial_success`;
- validation rejection → `422 Unprocessable Entity`;
- authentication → `401`;
- permission/policy denial → `403`;
- resource not found → `404`;
- conflict/stale revision/idempotency conflict → `409`;
- caller rate limit → `429`;
- capacity/service dependency unavailable → `503` там, где это отражает semantics;
- upstream gateway/provider failure → `502/503/504` по нормализованной причине;
- `unknown outcome` после internal/worker response loss → non-2xx с body, явно содержащим `outcome=unknown`.

Полная mapping table фиксируется implementation contract и тестируется.

---

# 8. Почему batch partial success возвращает 200

`207 Multi-Status` не используется как основной generic batch status.

Причины:

- canonical per-item outcomes уже находятся в typed body;
- `207` исторически связан с WebDAV semantics и усложняет generic clients;
- HTTP transport успешно доставил application batch result.

Client обязан читать aggregate/per-item outcomes.

---

# 9. Error response

REST error сохраняет application error taxonomy.

Концептуально:

```json
{
  "operation_id": "...",
  "outcome": "rejected",
  "data": null,
  "error": {
    "code": "validation_error",
    "category": "validation",
    "message": "Некорректные параметры запроса.",
    "details": []
  },
  "warnings": [],
  "hints": []
}
```

Raw FastAPI/Pydantic/SQLAlchemy/HTTPX/Playwright exception не является public schema.

---

# 10. FastAPI validation mapping

Transport-level malformed JSON/path/query schema errors должны быть преобразованы в согласованный REST validation envelope, а не оставаться отдельным несовместимым FastAPI default error format.

При этом field locations сохраняются настолько, чтобы programmatic client мог исправить request.

---

# 11. Request/operation identity

REST может принимать/generate transport `request_id`, но application `operation_id` создаётся trusted server-side execution layer.

Client не может подменить `operation_id` произвольным значением.

W3C trace context может приниматься согласно observability/security policy.

---

# 12. Correlation headers

Предварительно REST response должен позволять диагностировать:

- request ID;
- operation ID;
- trace ID при наличии.

Exact header names (`X-Request-ID`, `traceparent` и т.п.) фиксируются implementation style guide.

IDs также доступны в structured JSON там, где это удобно.

---

# 13. Authentication boundary

REST dependency layer преобразует authentication credential в trusted `PrincipalContext`.

Router/application не парсят credentials самостоятельно.

Точная authentication technology пока открыта.

Public resource access всегда проверяет owner/policy application layer.

---

# 14. API namespaces

Предлагаемая логическая структура:

```text
/api/v1/search
/api/v1/retrieval
/api/v1/content
/api/v1/browser
/api/v1/jobs
/api/v1/admin      (authorized/operator surface, если нужен)
```

Health/metrics рассматриваются отдельно.

---

# 15. Search REST

Canonical endpoint direction:

```text
POST /api/v1/search
```

POST выбран, потому что Search является structured batch operation, а не простой URL query string endpoint.

Request может предоставлять более богатый control, чем MCP:

- queries[];
- explicit provider per item;
- page/limit;
- language;
- region;
- safe_search;
- time_range;
- будущие stable options.

---

# 16. Search response

Возвращает batch result с:

- per-query outcome;
- resolved provider;
- result items;
- pagination metadata;
- cache/freshness metadata;
- billable/provider usage metadata в допустимом объёме;
- warnings/hints.

Provider credentials/internal protocol fields не возвращаются.

---

# 17. Search provider discovery/status

Для программного клиента полезна отдельная read-only capability:

```text
GET /api/v1/search/providers
```

Она может возвращать:

- provider_id/name;
- enabled/configured;
- common capabilities;
- billable marker;
- safe readiness/status summary.

Detailed operational diagnostics могут требовать admin permission и находиться в admin/diagnostics namespace.

---

# 18. Retrieval REST

Canonical direction:

```text
POST /api/v1/retrieval/fetch
```

Request принимает batch known URLs + разрешённые application options.

Он **не принимает unrestricted arbitrary HTTP headers/method/body**.

REST богатый, но не превращается в generic SSRF-capable HTTP proxy.

---

# 19. Retrieval response

Per item возвращает:

- requested/final URL;
- redirect metadata;
- HTTP status;
- safe response metadata;
- byte information;
- raw ContentRef при наличии;
- Content Inspection/Native representation summary, если composed operation request это включает;
- warnings/hints/errors.

---

# 20. Retrieval processing level

REST может явно предоставлять Content processing option:

```text
store_only
inspect
native
```

Это позволяет программному клиенту использовать backend более точно, чем MCP default.

Option остаётся common application concept и не раскрывает parser internals.

---

# 21. Content metadata endpoint

Canonical resource access:

```text
GET /api/v1/content/{content_id}
```

Возвращает:

- owner-authorized metadata;
- lifecycle;
- representation kind/media type;
- size/hash в допустимом объёме;
- inspection;
- provenance/source refs;
- available derived representations;
- retention/expiration metadata, если client-visibility предусмотрена.

---

# 22. Content bytes/download endpoint

Canonical direction:

```text
GET /api/v1/content/{content_id}/data
```

Response stream использует фактический media type и safe Content-Disposition policy.

Ownership/policy проверяется до выдачи.

Local storage path не раскрывается.

---

# 23. HTTP Range для stored Content

REST stored-content endpoint может поддерживать standard HTTP Range для больших immutable ContentObjects, если ContentStore adapter позволяет корректную bounded random access/streaming semantics.

Это transport capability **stored Content**, а не Retrieval Range request к внешнему сайту.

Exact Range support фиксируется implementation после ContentStore выбора.

---

# 24. Content representations

Canonical direction:

```text
GET /api/v1/content/{content_id}/representations
```

или representation list в metadata response.

Не следует создавать отдельный endpoint на каждый формат файла.

---

# 25. Native Parsing REST

Для повторной обработки уже существующего raw ContentObject требуется explicit operation, например:

```text
POST /api/v1/content/native-parse
```

с batch items/content refs и typed processing options.

Она может:

- вернуть существующий compatible derived object;
- создать новые derived representations;
- вернуть `processing_requires_job`/unsupported diagnostics.

Не нужны `/read-pdf`, `/read-docx`, `/read-xlsx` endpoints.

---

# 26. Content inspect REST

Если metadata endpoint недостаточно для batch use-case, допускается:

```text
POST /api/v1/content/inspect
```

с `content_ids[]`.

Наличие endpoint подтверждается практическим клиентским use-case; design не требует дублировать GET только ради симметрии.

---

# 27. Content upload/import

Будущая прямой upload capability может иметь direction:

```text
POST /api/v1/content
```

или dedicated upload endpoint.

Она должна:

- streaming ingest;
- size/security limits;
- owner assignment;
- filename as metadata;
- L0/L1 processing option;
- ContentRef result.

Upload не обязателен первой version и не должен блокировать core Retrieval/Browser design.

---

# 28. Browser session endpoints

Canonical resource direction:

```text
POST   /api/v1/browser/sessions
GET    /api/v1/browser/sessions/{session_id}
DELETE /api/v1/browser/sessions/{session_id}
```

`DELETE` означает idempotent application close/release BrowserSession, а не мгновенный hard-delete metadata.

Response terminal metadata может показывать `closed/expired/lost`.

---

# 29. Browser session creation request

REST может предоставлять typed stable settings:

- browser profile ID;
- approved locale/timezone/viewport options, если они входят в supported application contract;
- lifecycle hints/TTL class, если caller override разрешён policy.

REST не принимает raw `browser.new_context(**kwargs)`.

---

# 30. Browser pages

Canonical direction:

```text
GET    /api/v1/browser/sessions/{session_id}/pages
POST   /api/v1/browser/sessions/{session_id}/pages
DELETE /api/v1/browser/sessions/{session_id}/pages/{page_id}
```

Page create/close являются явными state transitions.

---

# 31. Browser navigation

Canonical direction:

```text
POST /api/v1/browser/sessions/{session_id}/pages/{page_id}/navigate
```

Request содержит stable navigation options, а не полный Playwright API.

Response отражает:

- final URL;
- page generation/revision;
- navigation outcome;
- popup/download events;
- warnings/hints.

---

# 32. Browser snapshot

Canonical direction:

```text
POST /api/v1/browser/sessions/{session_id}/pages/{page_id}/snapshot
```

POST допустим, хотя operation read-oriented, потому что snapshot:

- может иметь structured options;
- создаёт transient snapshot identity/ref mapping;
- не является простой immutable resource GET.

Response возвращает semantic snapshot + snapshot_id/refs или ContentRef при большом result.

---

# 33. Browser typed actions

REST предпочитает **отдельные semantic typed action endpoints**, а не unrestricted raw Playwright RPC.

Пример namespace:

```text
POST .../actions/click
POST .../actions/fill
POST .../actions/fill-form
POST .../actions/type
POST .../actions/select
POST .../actions/check
POST .../actions/press
POST .../actions/hover
POST .../actions/wait
```

Точный список фиксируется после Browser implementation schema review.

---

# 34. Почему не один `POST /actions`

Discriminated union endpoint технически возможен, но отдельные semantic endpoints дают:

- более ясный OpenAPI;
- разные retry/side-effect descriptions;
- точные schemas;
- проще authorization опасных actions;
- проще evolution отдельных action contracts.

Внутри application worker protocol actions всё равно могут использовать общий typed command envelope.

---

# 35. Browser ElementRef

Обычные interaction REST endpoints используют snapshot-scoped `element_ref`.

Advanced REST может позднее поддержать semantic locator request как отдельную capability, но baseline не должен заставлять clients передавать CSS/XPath.

`element_ref` всегда проверяется относительно session/page/snapshot generation.

---

# 36. Browser screenshot

Canonical direction:

```text
POST /api/v1/browser/sessions/{session_id}/pages/{page_id}/screenshot
```

Result — ContentRef, а не giant base64 JSON.

---

# 37. Browser diagnostics

Read-only endpoints:

```text
GET /api/v1/browser/sessions/{session_id}/console
GET /api/v1/browser/sessions/{session_id}/network
```

используют cursor/pagination:

```text
after
limit
page_id optional
```

Sensitive fields redacted.

---

# 38. Browser upload

Canonical direction может быть action endpoint:

```text
POST .../actions/upload
```

Request использует `content_id` + target element_ref.

REST не принимает path на filesystem сервера.

---

# 39. Browser downloads

Download, инициированный action, возвращается как ContentRef/event.

Дополнительный «скачай browser temp path» endpoint не нужен.

После persistence browser context может быть закрыт без потери ContentObject.

---

# 40. Browser event streaming

Для Web UI/monitoring потенциально полезен optional SSE stream:

```text
GET /api/v1/browser/sessions/{session_id}/events/stream
```

Но SSE не является source of truth и не обязателен initial implementation.

Baseline должен иметь polling/cursor-compatible resource/event access.

WebSocket не выбирается автоматически только потому, что Browser stateful.

---

# 41. Jobs lifecycle REST

Generic lifecycle endpoints:

```text
GET  /api/v1/jobs/{job_id}
POST /api/v1/jobs/{job_id}/cancel
GET  /api/v1/jobs/{job_id}/events
```

Owner Job list может быть:

```text
GET /api/v1/jobs
```

с cursor filters.

---

# 42. Job creation REST

Job creation должна быть **domain-specific typed operation**, а не generic arbitrary task endpoint.

Например будущий crawl может иметь:

```text
POST /api/v1/crawl/jobs
```

или другой component namespace.

Не следует делать:

```text
POST /api/v1/jobs
{"task":"python.function.name", "args":{}}
```

---

# 43. Job events

`GET /jobs/{id}/events` использует cursor/sequence pagination.

Optional SSE:

```text
GET /jobs/{id}/events/stream
```

может быть добавлен для web UI, но не является обязательным для canonical Job lifecycle.

---

# 44. Collection pagination

Для server-owned collections (Jobs, operational records, возможно Content list) используется cursor-based pagination.

Не следует путать её с provider page semantics Search.

Canonical collection response:

```text
items[]
next_cursor | null
```

Offset pagination допускается только если конкретный small reference list действительно этого требует.

---

# 45. Cursor opacity

Cursor opaque для клиента.

Он может содержать signed/encoded sort key, но client не строит логику на его внутренней структуре.

Cursor должен быть scoped к filters/order/version настолько, чтобы повторное использование с несовместимым query rejected.

---

# 46. Filtering/sorting

REST list endpoints используют allowlisted typed filters/sort fields.

Не поддерживается arbitrary SQL-like expression/filter string.

Это защищает persistence abstraction и security.

---

# 47. Idempotency-Key

REST может поддерживать `Idempotency-Key` только на operations с явно спроектированной idempotency semantics.

Кандидаты:

- durable Job creation;
- BrowserSession create;
- future Content upload/finalize.

Нельзя автоматически считать Browser click идемпотентным только из-за наличия HTTP header.

---

# 48. Browser action client retry

Mutating Browser endpoint documentation должна прямо предупреждать:

- connection loss может дать `unknown`;
- client не должен blindly retry action;
- verification snapshot/read operation предпочтительнее.

REST SDK/client helpers в будущем должны уважать эту semantics.

---

# 49. Conditional resource updates

Для mutable durable resources REST может использовать explicit `expected_revision` application field или HTTP conditional semantics (`If-Match`) там, где это действительно полезно.

Не следует добавлять ETag/If-Match повсеместно без component need.

Browser snapshot/element refs уже дают более специальную stale-target semantics.

---

# 50. Resource URLs

REST response может включать относительные API links на Content/Job/Browser resources как convenience.

Canonical identity всё равно ResourceRef, а не URL string.

Base URL/reverse proxy topology не должна попадать в persisted resource model.

---

# 51. OpenAPI

FastAPI-generated OpenAPI является частью REST contract и должен contract-test-иться.

Requirements:

- stable `operationId`;
- подробные descriptions;
- exact required/default/enum/min/max/list constraints;
- examples для сложных schemas;
- security schemes;
- error responses;
- не протекают infrastructure fields.

---

# 52. Язык REST documentation

OpenAPI descriptions/docstrings проекта преимущественно пишутся на русском, поскольку это основной язык проекта.

Identifiers/property names остаются английскими.

Это согласовано с MCP documentation policy.

---

# 53. Backward compatibility

В пределах `/api/v1` допустимы в основном additive/backward-compatible changes:

- optional response fields;
- новые endpoints;
- новые enum values только если clients должны быть готовы к extension и это явно отражено contract;
- новые optional request fields.

Breaking change требует migration/version strategy.

Enum evolution должна быть особенно осторожной для generated clients.

---

# 54. Deprecation

Deprecated REST fields/endpoints:

- помечаются в OpenAPI;
- имеют documented replacement;
- не удаляются без version/deprecation policy;
- не поддерживаются бесконечно только ради случайных ранних clients до первого stable release.

Pre-1.0 roadmap может допускать более быстрые изменения при явном version status.

---

# 55. Request size limits

Control Plane применяет transport-level request body limits до Pydantic parsing для больших payloads настолько, насколько это возможно.

JSON API не предназначен для giant base64 content.

Large uploads используют streaming/multipart Content endpoint.

---

# 56. Response size limits

Structured endpoints возвращают bounded JSON.

Большой Content/Browser snapshot/Job result выносится в ContentObject/resource refs.

REST может стримить Content separately.

---

# 57. Timeouts

Reverse proxy/server timeout должен быть согласован с application request-bound deadlines.

Нельзя позволять proxy обрывать response раньше configured application max deadline без понимания `unknown outcome` для Browser action.

Mutating endpoints требуют особенно аккуратной timeout configuration.

---

# 58. CORS

CORS не является `*` default для credentialed REST API.

Allowed origins/configuration определяются deployment/auth policy.

Server-to-server clients не требуют CORS.

---

# 59. CSRF

Если authentication позднее использует browser cookies, state-changing REST endpoints требуют CSRF protection.

Если используется bearer service/user token без ambient browser credential, threat model отличается.

REST design сохраняет возможность добавить CSRF без изменения application contracts.

---

# 60. Operational health endpoints

Предлагаемое направление:

```text
GET /health/live
GET /health/ready
GET /health/status
```

Где:

- live — минимальная process liveness;
- ready — orchestrator-facing readiness;
- status — detailed capability/dependency status, вероятно authorized или redacted public view.

Точные paths/status codes фиксируются deployment/implementation.

---

# 61. Metrics endpoint

Предварительно:

```text
GET /metrics
```

Operational endpoint не входит `/api/v1` application surface и защищается network/deployment policy.

---

# 62. Admin namespace

Operator-only capabilities, если они нужны, размещаются отдельно:

```text
/api/v1/admin/...
```

Примеры потенциально:

- detailed provider status;
- worker topology;
- parser registry/status;
- reconciliation trigger/status;
- configuration revision;
- retention maintenance.

Не следует смешивать admin controls с обычным MCP-facing application surface.

---

# 63. Dangerous admin operations

Manual cleanup/reconcile/disable provider и другие mutating admin actions требуют:

- отдельной permission;
- durable audit там, где policy требует;
- explicit confirmation/idempotency semantics;
- безопасного error model.

REST admin surface не появляется автоматически в первой версии.

---

# 64. Rate limit headers

Для REST caller rate limiting можно использовать стандартные/документированные rate-limit response headers, если выбранная policy это поддерживает.

Canonical application error всё равно содержит `rate_limited` semantics.

Точный header convention определяется implementation.

---

# 65. Retry-After

Для `429`/`503` REST должен возвращать `Retry-After`, если backend способен дать корректное время/интервал.

Нельзя придумывать точное retry time, если оно неизвестно.

---

# 66. Content-Disposition

Download endpoint строит safe `Content-Disposition` из sanitized metadata.

Caller-supplied filename не превращается в filesystem path/header injection.

---

# 67. Active content serving

HTML/SVG и другой active ContentObject не должен по умолчанию inline-render-иться на доверенном Web UI origin.

REST download/preview policy должна учитывать `Content-Security-Policy`, `Content-Disposition` и отдельный content origin при необходимости.

Detailed Web UI design отдельный.

---

# 68. Streaming events backpressure

Если SSE/WebSocket added:

- buffers bounded;
- slow client не блокирует Browser Worker/Job execution;
- reconnect использует sequence/cursor, если events durable;
- transient browser events могут быть потеряны согласно documented retention;
- stream не является ownership keepalive автоматически.

---

# 69. Client disconnect

Request-bound read operation может cooperative-cancel при disconnect.

Durable Job не отменяется.

Browser mutating action после disconnect следует общему `unknown outcome`/worker protocol, а не автоматически отменяется/повторяется.

Transport handler не должен уничтожать BrowserSession только потому, что HTTP client disconnected.

---

# 70. REST SDK friendliness

Schemas должны быть пригодны для generated/manual typed clients:

- discriminated unions там, где нужны;
- стабильные field types;
- explicit nullable vs optional;
- ISO timestamps;
- opaque strings IDs;
- enum codes;
- machine-readable errors.

Не следует возвращать shape, который меняется по provider library internals.

---

# 71. Null vs omitted

Request schemas должны явно определять semantics:

- field omitted;
- field `null`;
- empty list/string.

Если `null` и omitted означают одно и то же, лучше сделать это явным и не создавать лишнюю tri-state semantics.

MCP later может иметь ещё более простой contract.

---

# 72. Unknown fields

Public request models должны по умолчанию отвергать неизвестные поля (`extra=forbid` или эквивалент), чтобы typo не игнорировалась молча.

Backward-compatible extensions добавляются явно в schema.

---

# 73. Batch item IDs

REST может позволять caller-supplied opaque `item_id` в batch для удобной correlation, если это не усложняет application model.

`item_id` не является resource ID и не даёт idempotency автоматически.

Если поле не нужно первой реализации, input index остаётся canonical correlation.

---

# 74. Security tests REST

Необходимо проверять:

- auth/permission;
- cross-owner resource access;
- unknown fields rejection;
- request/body limits;
- CORS/CSRF policy;
- Content-Disposition/header injection;
- active content serving;
- error redaction;
- operator endpoint isolation;
- Idempotency-Key conflicts;
- client disconnect Browser behavior.

---

# 75. OpenAPI contract tests

CI должен получать фактический FastAPI OpenAPI schema и проверять:

- все public operations присутствуют ровно один раз;
- operationId уникален/stable;
- descriptions есть;
- required/default/enums/limits корректны;
- common error envelope присутствует;
- internal infrastructure fields отсутствуют;
- binary endpoints имеют корректные media types;
- deprecated markers/versioning корректны.

Тестируется actual generated OpenAPI, а не только Pydantic class definitions.

---

# 76. REST integration tests

Через реальный ASGI app/test client:

- Search batch;
- Retrieval→Content;
- Content metadata/data;
- Browser session/action/snapshot;
- Job lifecycle;
- partial success/error mapping;
- auth owner isolation;
- health degraded states;
- streaming/download.

---

# 77. Acceptance criteria REST facade

REST facade считается спроектированным/реализованным, если:

1. `/api/v1` использует общий application layer.
2. Нет business logic/repositories/providers внутри routers.
3. Search batch доступен через structured POST.
4. Retrieval не является unrestricted HTTP proxy.
5. Content имеет metadata + streaming data + native processing capabilities.
6. Browser sessions являются explicit REST resources.
7. Browser actions имеют typed semantic endpoints, а не raw Playwright RPC.
8. Screenshots/downloads/uploads используют ContentRefs.
9. Jobs имеют generic lifecycle endpoints, а creation остаётся domain-typed.
10. Collection pagination cursor-based.
11. Application outcomes/errors согласованно маппятся в HTTP.
12. Batch partial success сохраняется в typed body.
13. Request/response size bounded; giant content не base64-ится в JSON.
14. Auth/ownership выполняются server-side.
15. OpenAPI фактически contract-tested.
16. Unknown fields не игнорируются молча.
17. Operational/admin endpoints отделены от обычного application API.
18. REST может быть существенно богаче MCP без дублирования backend logic.

---

# 78. Open questions

До implementation REST facade необходимо закрыть:

1. Точная API auth technology/security scheme.
2. Exact common response/error Pydantic envelopes.
3. Exact HTTP status mapping `unknown`/upstream errors.
4. Exact endpoint names для Content native parse/inspect.
5. Browser action endpoint final catalog.
6. Job creation namespaces первых concrete job types.
7. Нужны ли SSE streams в первой REST версии.
8. Exact cursor encoding/signing.
9. Idempotency-Key endpoints/retention.
10. Content HTTP Range support первой версии.
11. Upload endpoint/streaming protocol первой версии.
12. Detailed health/admin access policy.
13. API compatibility/deprecation policy до/после `v1` stable release.
14. Need for generated REST client SDK и его language targets.

Эти вопросы уточняют transport UX и не меняют backend contracts.
