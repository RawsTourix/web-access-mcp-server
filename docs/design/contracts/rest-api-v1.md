# Exact REST API v1 contract

## Статус

Каноническая freeze-candidate спецификация public REST `/api/v1` Web Access.

Семантика facade принадлежит `../rest-api.md`; application semantics — component design; общие transport-facing модели — `common-models.md`. Этот документ фиксирует endpoint tree, request DTO, bounds и response projection для stable v1 line.

Generated FastAPI OpenAPI в v0.8 обязан соответствовать этому contract или design должен быть явно изменён до freeze.

---

# 1. Общие правила

Base application prefix:

```text
/api/v1
```

Operational endpoints:

```text
/health/live
/health/ready
/metrics
```

Rules:

- JSON field names `snake_case`;
- JSON request objects reject unknown fields;
- application JSON responses use `PublicOperationResult` unless endpoint is explicitly a resource stream;
- timestamps RFC 3339 UTC;
- large binary/text payload is streamed through Content data endpoint, never giant base64 JSON;
- authentication uses `Authorization: Bearer ...` through `AuthProvider`;
- `PrincipalContext` comes only from trusted authentication, never a caller-supplied owner field;
- `Content`, `BrowserSession`, `Job` resource access is owner/scope checked server-side;
- public REST never exposes SQL keys, Redis keys, ContentStore paths, Browser Worker route data, Playwright/CDP IDs or provider credentials.

Transport maximum JSON body is deployment-configured under a hard ceiling; endpoint item/string limits below remain authoritative contract limits.

---

# 2. Common headers

## Request

Supported correlation input:

```text
traceparent           standard W3C trace context when valid
X-Request-ID          optional caller correlation string, max 128 chars
Idempotency-Key       only endpoints explicitly declaring support
```

Caller `X-Request-ID` is diagnostic, not `operation_id`.

## Response

JSON operations return diagnostic headers where available:

```text
X-Request-ID
X-Operation-ID
traceparent
```

Body remains canonical source for `operation_id`.

---

# 3. Authentication/scopes

Exact scope names may be prefixed in implementation, but public capability groups are:

```text
search:read
retrieval:read
content:read
content:write
browser:read
browser:write
jobs:read
jobs:write
admin:read
admin:write
```

A deployment may map external credentials/roles to these stable internal capabilities through `AuthProvider`.

Dynamic policy cannot grant a capability absent from authenticated principal scopes.

---

# 4. Error/status mapping baseline

```text
succeeded                         → 200/201/204 according endpoint
partial batch                     → 200 with outcome=partial
validation                        → 422
unauthenticated                   → 401
permission/policy                 → 403
resource not found               → 404
revision/idempotency conflict     → 409
rate limited                      → 429
upstream/provider gateway error   → 502
capacity/dependency unavailable   → 503
upstream/request deadline         → 504 where appropriate
unknown mutating outcome          → non-2xx + outcome=unknown
```

Expected application errors use normalized body, not raw framework exception JSON.

---

# 5. Search endpoints

## 5.1 `POST /api/v1/search`

Purpose: rich request-bound Search batch.

Request:

```text
queries: array[RestSearchQuery] required, 1..32
```

`RestSearchQuery`:

```text
query: string required, trim-non-empty, 1..4096
provider: string default "default", 1..64
page: integer default 1, 1..100
limit: integer default 10, 1..50
language: string | omitted, 1..64
region: string | omitted, 1..64
safe_search: off | moderate | strict | omitted
time_range: day | month | year | omitted
```

Unlike MCP, provider/options may differ per query item.

`provider` is a stable provider ID resolved through registry; unknown/disabled provider returns per-item repairable rejection.

Response data:

```text
items[] in request order
└── BatchItemResult<SearchQueryData>
```

Search result item fields follow common Search design: rank/title/url/snippet/host/published_at + bounded provenance/cache/pagination metadata.

## 5.2 `GET /api/v1/search/providers`

Read-only provider discovery.

Response data:

```text
providers[]:
  provider_id
  name
  enabled
  billable
  capabilities:
    pagination
    language
    region
    safe_search
    time_range
  readiness: ready | degraded | unavailable
```

No credentials/provider raw config.

---

# 6. Retrieval endpoint

## `POST /api/v1/retrieval/fetch`

Request:

```text
items: array[RestFetchItem] required, 1..32
processing_level: store_only | inspect | native default native
```

`RestFetchItem`:

```text
url: full HTTP(S) URL required, 1..8192 chars
```

No arbitrary method/body/headers/proxy/DNS/redirect policy supplied by client.

`processing_level`:

```text
store_only → safe Retrieval + raw ContentObject
inspect    → raw + L0 Inspection
native     → raw + L0 + available request-bound L1
```

Response data per item:

```text
requested_url
final_url
http_status
redirect_chain bounded
wire_bytes
entity_bytes
content_encoding | null
raw_content: ContentRef
inspection | null
native_content: ContentRef | null
available_representations[]
preview | null
```

Batch preserves order/partial success.

---

# 7. Content resource endpoints

## 7.1 `GET /api/v1/content/{content_id}`

Returns owner-authorized metadata.

Path `content_id`: opaque string max 128.

Response data:

```text
content: ContentRef
state
representation_kind
media_type | null
detected_format | null
source_filename | null
inspection
provenance
available_representations[]
retention:
  expires_at | null
```

Internal storage/staging keys excluded.

## 7.2 `GET /api/v1/content/{content_id}/data`

Streams immutable ContentObject bytes.

Properties:

- owner/scope checked before stream;
- `Content-Type` from safe stored metadata;
- safe `Content-Disposition` when filename present;
- HTTP Range may be supported for available immutable object;
- invalid/unsupported Range returns standard `416`;
- no JSON envelope on successful byte stream;
- errors before stream use normalized REST JSON envelope.

## 7.3 `GET /api/v1/content/{content_id}/representations`

Returns direct known relations/derived representations visible to owner.

Response data:

```text
source: ContentRef
representations: array[ContentRepresentationSummary]
```

Each summary includes target ContentRef, relation/provenance and representation kind; no parser private path.

## 7.4 `POST /api/v1/content/inspect`

Batch L0 inspection for existing objects.

Request:

```text
content_ids: array[ContentId] required, 1..32, uniqueItems=true
```

Response per item:

```text
content: ContentRef
inspection
```

No L1 processing.

## 7.5 `POST /api/v1/content/native-parse`

Request-bound L1 parse.

Request:

```text
content_ids: array[ContentId] required, 1..32, uniqueItems=true
reuse_existing: bool default true
```

Response per item:

```text
source: ContentRef
representations: ContentRef[]
reused: bool
parser_capability | null
```

No client-supplied library/parser implementation ID and no L2.

---

# 8. BrowserSession resource

## 8.1 `POST /api/v1/browser/sessions`

Creates one BrowserSession.

Supports `Idempotency-Key` for **creation identity only** when implementation can persist deterministic replay of the create result. Same key + same canonical request returns same logical create result; same key + different request → `409`.

Request:

```text
locale: string | omitted, 1..64
timezone: string | omitted, 1..128
viewport: object | omitted
  width: integer 320..3840
  height: integer 240..2160
idle_ttl_seconds: integer | omitted, 60..900
max_lifetime_seconds: integer | omitted, 300..3600
```

Policy may cap caller values below these hard contract ceilings.

No proxy, launch args, persistent profile, extension, executable path, CDP endpoint or arbitrary Playwright kwargs.

Response status `201` on new resource.

Response data:

```text
session: BrowserSessionRef
page: PageRef
```

No URL navigation during create.

## 8.2 `GET /api/v1/browser/sessions/{session_id}`

Returns session lifecycle/status and safe page count.

## 8.3 `DELETE /api/v1/browser/sessions/{session_id}`

Idempotent logical close/release.

Response may be `200` with terminal resource state; endpoint does not hard-delete durable metadata immediately.

---

# 9. Browser pages

## 9.1 `GET /api/v1/browser/sessions/{session_id}/pages`

Returns bounded page list, max server-side session ceiling (initially 8).

## 9.2 `POST /api/v1/browser/sessions/{session_id}/pages`

Creates one blank page.

Supports `Idempotency-Key` only if resource creation replay semantics are implemented exactly as §8.1.

Response `201` with `PageRef`.

## 9.3 `DELETE /api/v1/browser/sessions/{session_id}/pages/{page_id}`

Idempotent page close.

Closing last live page → `409`/structured `last_page_close_rejected`.

---

# 10. Browser navigation

## `POST /api/v1/browser/sessions/{session_id}/pages/{page_id}/navigate`

Request:

```text
destination: discriminated union required
expected_session_revision: integer | omitted, >=0
dialog_policy: DialogPolicy | omitted
```

Destination:

```json
{"type":"url","url":"https://example.com"}
{"type":"back"}
{"type":"forward"}
{"type":"reload"}
```

REST URL max `8192` chars.

No automatic Browser retry after uncertain dispatch.

Response contains `action_id`, PageRef/page_generation and popup/download/dialog summaries.

---

# 11. Browser snapshot/content/artifacts

## 11.1 `POST .../snapshot`

Path:

```text
POST /api/v1/browser/sessions/{session_id}/pages/{page_id}/snapshot
```

Request:

```text
max_inline_chars: integer default 100000, 1000..100000
```

Backend hard generation budget remains lower/equal to version policy; larger representation externalized as ContentRef.

Response:

```text
SnapshotRef
semantic_view
SemanticElement[]
full_content | null
truncated
```

No selectors.

## 11.2 `POST .../content`

Path:

```text
POST /api/v1/browser/sessions/{session_id}/pages/{page_id}/content
```

Request:

```text
processing_level: store_only | inspect | native default native
```

Produces rendered HTML/raw ContentObject and optional L0/L1 representations.

## 11.3 `POST .../screenshot`

Same semantic target/format contract as MCP, with REST bounds:

```text
target: page(full_page bool) | element(element_ref)
format: png | jpeg default png
quality: 1..100 only JPEG, default 85
```

Returns ContentRef; never giant base64 JSON.

---

# 12. Browser action request common fields

All mutating browser action endpoints accept where applicable:

```text
expected_session_revision: integer | omitted, >=0
dialog_policy: DialogPolicy | omitted
```

Element actions use opaque `element_ref` from current snapshot.

No CSS/XPath, coordinates, JavaScript expression, `force`, filesystem path or raw Playwright options in public v1.

Application/worker action ledger generates `action_id` and performs internal status recovery. External client still treats lost HTTP response to mutating action as potentially `unknown`.

---

# 13. Browser action endpoints

Base:

```text
/api/v1/browser/sessions/{session_id}/pages/{page_id}/actions
```

## 13.1 `POST .../click`

Request:

```text
element_ref
button: left | middle | right default left
click_count: 1..2 default 1
modifiers: unique array[Alt|Control|Meta|Shift], max 4
expected_session_revision | omitted
dialog_policy | omitted
```

## 13.2 `POST .../fill-form`

Request:

```text
fields: 1..64 FormFieldInput
expected_session_revision | omitted
dialog_policy | omitted
```

`FormFieldInput.value` union identical to MCP but REST text upper bound `65536` chars and select values max `100`.

No automatic submit.

## 13.3 `POST .../type`

```text
element_ref
text: 1..65536 chars
delay_ms: 0..1000 default 0
expected_session_revision | omitted
dialog_policy | omitted
```

## 13.4 `POST .../press`

```text
key: 1..64 chars
element_ref | omitted
expected_session_revision | omitted
dialog_policy | omitted
```

## 13.5 `POST .../hover`

```text
element_ref
expected_session_revision | omitted
```

## 13.6 `POST .../drag`

```text
source_element_ref
target_element_ref
expected_session_revision | omitted
dialog_policy | omitted
```

## 13.7 `POST .../wait`

Condition union equivalent MCP with broader bounded timeouts:

```text
duration milliseconds: 0..30000
url/element/load timeout_ms: 100..120000, default 30000
```

No JS predicate/regex baseline.

## 13.8 `POST .../upload`

```text
element_ref
content_id
expected_session_revision | omitted
```

No server filesystem path.

---

# 14. Browser events

## `GET /api/v1/browser/sessions/{session_id}/events`

Query parameters:

```text
page_id optional
type repeated/CSV typed filter optional
  page|dialog|download|console|network|security|browser
after_sequence integer optional >=0
limit integer default 100, 1..500
```

Response:

```text
events[]
next_sequence | null
gap_detected
```

Sensitive headers/body/secrets redacted.

Optional SSE is not part of v1 frozen baseline unless later added additively through explicit contract review.

---

# 15. Durable Job creation endpoints

## 15.1 `POST /api/v1/jobs/retrieval-batches`

Supports `Idempotency-Key`.

Request:

```text
urls: array[HTTP(S) URL] required, 1..1000
```

Each URL max `8192` chars.

Result `201`:

```text
job: JobRef
```

Job type `retrieval_batch`.

## 15.2 `POST /api/v1/jobs/content-parse-batches`

Supports `Idempotency-Key`.

Request:

```text
content_ids: array[ContentId] required, 1..1000, uniqueItems=true
```

Result `201` JobRef, type `content_parse_batch`.

No generic public `{task,args}` endpoint.

---

# 16. Job lifecycle endpoints

## 16.1 `GET /api/v1/jobs/{job_id}`

Returns:

```text
JobRef
progress | null
attempt summary
aggregate outcome | null
result manifest ContentRef | null
terminal error | null
```

## 16.2 `POST /api/v1/jobs/{job_id}/cancel`

Idempotent cancellation request.

Returns current `cancelling|cancelled|already_terminal` semantics.

## 16.3 `GET /api/v1/jobs/{job_id}/events`

Query:

```text
after_sequence optional >=0
limit default 100, 1..500
```

Returns bounded durable client-visible Job events.

## 16.4 `GET /api/v1/jobs`

Owner-scoped collection.

Query:

```text
state optional typed filter
job_type optional 1..64
created_after optional timestamp
created_before optional timestamp
cursor optional max 2048
limit default 50, 1..100
```

Response:

```text
items: JobRef[]
next_cursor | null
```

---

# 17. Dynamic policy/admin endpoints

These endpoints require operator/admin scopes and are not projected into core MCP.

## 17.1 `GET /api/v1/admin/policy`

Returns current immutable `PolicySnapshot`:

```text
revision
created_at
created_by principal-safe identifier
policy document
```

Policy document contains only registered typed non-secret sections. Unknown policy keys rejected.

Secrets/DSNs/API keys never stored here.

## 17.2 `PUT /api/v1/admin/policy`

Request:

```text
expected_revision: integer required >=0
policy: exact typed PolicyDocument required
reason: string required, 1..2048
```

Atomic compare-and-set update.

Stale revision → `409`.

Audit event required.

Dynamic policy cannot exceed software/deployment hard ceilings or grant missing auth scopes.

## 17.3 `GET /api/v1/admin/status`

Returns safe capability-aware operational summary:

```text
build/version
policy_revision
capabilities:
  search
  retrieval
  content
  browser
  jobs
backlogs/capacity bounded summaries
```

No credentials/internal URLs.

## 17.4 `GET /api/v1/admin/browser/workers`

Protected diagnostics list:

```text
worker_id safe opaque identifier
worker_generation
state ready|draining|fenced|lost
active_sessions
capacity
last_heartbeat_at
runtime_revision
```

No credential material.

## 17.5 `GET /api/v1/admin/jobs/backlog`

Returns aggregate Job/outbox backlog/age/capacity diagnostics, not raw arbitrary queue payload.

---

# 18. Operational endpoints

## `/health/live`

Process liveness only. Must not fail merely because PostgreSQL/Redis/SearXNG is degraded if process event loop can serve diagnostic traffic.

## `/health/ready`

Capability-aware readiness JSON.

Must distinguish at least:

```text
ready
degraded
not_ready
```

and include dependency/capability summaries without secrets.

Load balancer HTTP status policy is deployment-defined but must match readiness semantics.

## `/metrics`

Prometheus exposition format.

Protected/network-restricted according deployment; no high-cardinality URLs/principal IDs/content strings as labels.

---

# 19. Cursor/pagination contract

Collections use opaque cursor, max `2048` chars.

Cursor is scoped/versioned to query/filter/order; incompatible reuse rejected.

Canonical collection shape:

```text
items[]
next_cursor | null
```

Provider Search `page` is separate semantics and does not use collection cursor.

---

# 20. Idempotency-Key contract

Supported only on explicitly listed create endpoints.

Header:

```text
1..128 ASCII-visible chars
```

Server stores owner + endpoint + canonical request hash + logical response identity for retention window.

Rules:

```text
same principal + endpoint + key + same canonical request
→ replay same logical creation result

same key + different canonical request
→ 409 idempotency_key_conflict
```

Idempotency-Key does **not** make Browser click/type/press/navigation safe to blind retry.

---

# 21. OpenAPI contract gate

Generated OpenAPI is contract-tested for:

1. exact `/api/v1` paths/methods;
2. stable `operationId`;
3. security scheme/scopes;
4. required/default/enum/min/max/minItems/maxItems;
5. discriminated unions/cross-field rules;
6. normalized common error schemas;
7. Russian descriptions where project-owned documentation text applies;
8. no infrastructure/private fields;
9. streaming endpoint media types/Range docs;
10. admin endpoints protected by explicit operator scopes.

Golden OpenAPI fixture is frozen in v0.8 and compatibility-checked after that.

---

# 22. Explicitly excluded v1 REST primitives

Not part of stable public v1:

```text
arbitrary HTTP method/body/headers proxy
raw SQL/Redis access
raw SearXNG/Yandex request passthrough
raw Playwright/CDP RPC
CSS/XPath action endpoints
arbitrary JavaScript evaluate
server-local path upload/download
arbitrary job function execution
CAPTCHA/stealth controls
L2 OCR/VLM/LibreOffice processor API
BrowserSession live migration
```

If future need is real, it receives separate design/permission/version review.
