# Exact Browser REST API v1 contract

## Статус

Канонический exact contract для public REST Browser namespace Web Access v1.

Semantic owner:

- `../browser.md`;
- `../rest-api.md`;
- Browser ADR-0001/0009..0014;
- ADR-0024;
- ADR-0025.

Этот документ является более специфичным, чем ранняя Browser-секция `rest-api-v1.md`; при различии Browser DTO/routes приоритет имеет этот contract.

Common models: `common-models.md`.

---

# 1. Namespace/auth

Base:

```text
/api/v1/browser
```

Scopes:

```text
browser:read
browser:write
```

Read endpoints require read capability; session/page/action mutations require write/interact policy.

All BrowserSession/Page/Content resources owner-authorized.

No Browser Worker IDs/routes exposed in ordinary public Browser API.

---

# 2. BrowserSession create

## `POST /api/v1/browser/sessions`

Request:

```text
locale: string omitted | 1..64
timezone: string omitted | 1..128
viewport: object omitted
  width: integer 320..3840
  height: integer 240..2160
idle_ttl_seconds: integer omitted, 60..900
max_lifetime_seconds: integer omitted, 300..3600
```

Cross-field:

```text
idle_ttl_seconds <= max_lifetime_seconds
```

Values are further capped by EffectivePolicy/global/runtime ceilings.

No URL, proxy, executable path, user_data_dir, extension, launch args, CDP endpoint or raw Playwright kwargs.

Optional `Idempotency-Key` supported only after exact creation-replay persistence is implemented; v0.4 may omit it until v0.8 stabilization, but v1 target semantics follow general REST idempotency contract.

Response `201`:

```text
session: BrowserSessionRef
page: PageRef
```

No hidden navigation.

---

# 3. BrowserSession read/close

## `GET /api/v1/browser/sessions/{session_id}`

Returns owner-safe lifecycle metadata + pages count/lifetime.

## `DELETE /api/v1/browser/sessions/{session_id}`

Idempotent logical close/release.

Terminal metadata retained according lifecycle/audit policy; already finalized ContentObjects remain valid.

No hard-delete metadata guarantee.

---

# 4. Page list/create/close

## `GET /api/v1/browser/sessions/{session_id}/pages`

Returns `PageRef[]`, bounded by session hard ceiling (v1 software baseline max 8).

## `POST /api/v1/browser/sessions/{session_id}/pages`

Creates exactly one blank page; response `201`.

No URL input.

## `DELETE /api/v1/browser/sessions/{session_id}/pages/{page_id}`

Idempotent page close.

Last live page → `409 last_page_close_rejected`; use session close to end BrowserSession.

No automatic replacement page.

---

# 5. Navigation

## `POST /api/v1/browser/sessions/{session_id}/pages/{page_id}/navigate`

Request:

```text
destination: discriminated union required
expected_session_revision: integer omitted >=0
dialog_policy: DialogPolicy omitted
```

Destination:

```json
{"type":"url","url":"https://example.com"}
{"type":"back"}
{"type":"forward"}
{"type":"reload"}
```

REST URL `1..8192` chars; runtime only HTTP(S) for direct URL.

Result:

```text
action_id
page: PageRef
page_generation
navigation summary
popup_pages[]
download_refs[]
dialogs[]
```

No automatic retry after dispatch uncertainty.

---

# 6. Snapshot

## `POST /api/v1/browser/sessions/{session_id}/pages/{page_id}/snapshot`

Request:

```text
max_inline_chars: integer 1000..100000, default 100000
```

Result:

```text
snapshot: SnapshotRef
page: PageRef
semantic_view <= requested/hard bound
elements: SemanticElement[] <= backend hard ref ceiling
full_content: ContentRef | null
truncated: bool
```

No CSS/XPath/private locator recipes.

Snapshot is read-only and **does not scroll**.

---

# 7. Rendered Content

## `POST /api/v1/browser/sessions/{session_id}/pages/{page_id}/content`

Request:

```text
processing_level: store_only | inspect | native, default native
```

Produces rendered HTML/raw ContentObject + requested L0/L1 representations.

Result bounded by ContentRefs/preview; giant DOM not inline.

Operation creates Content resources and is not generic blind-retry-safe after ambiguous response loss.

---

# 8. Screenshot

## `POST /api/v1/browser/sessions/{session_id}/pages/{page_id}/screenshot`

Request:

```text
target: union default page/full_page=false
format: png | jpeg default png
quality: integer omitted
```

Target:

```json
{"type":"page","full_page":false}
```

or

```json
{"type":"element","element_ref":"el_..."}
```

Rules:

- JPEG quality 1..100, default 85;
- quality forbidden for PNG;
- element target has no `full_page`;
- server enforces artifact pixel/byte/resource ceilings.

Result image `ContentRef`, dimensions and page generation.

---

# 9. Action common rules

Action base:

```text
/api/v1/browser/sessions/{session_id}/pages/{page_id}/actions
```

Common optional fields where declared:

```text
expected_session_revision: integer >=0
dialog_policy: DialogPolicy
```

Element interactions use `element_ref` from current compatible snapshot.

No public:

- CSS/XPath;
- arbitrary coordinates for targeting;
- `force`;
- JavaScript predicate/evaluate;
- server filesystem path;
- raw Playwright options.

Mutating action response loss may produce `unknown`; client does not blind retry.

---

# 10. Click

## `POST .../actions/click`

Request:

```text
element_ref
button: left | middle | right default left
click_count: integer 1..2 default 1
modifiers: unique array[Alt|Control|Meta|Shift], 0..4
expected_session_revision omitted
dialog_policy omitted
```

Result action/page_generation + bounded popup/download/dialog summaries.

---

# 11. Fill form

## `POST .../actions/fill-form`

Request:

```text
fields: FormFieldInput[] 1..64
expected_session_revision omitted
dialog_policy omitted
```

`FormFieldInput.value`:

```json
{"type":"text","text":""}
{"type":"select","values":["..."]}
{"type":"checked","checked":true}
```

REST bounds:

- text 0..65536 chars;
- select values 1..100;
- each select value 0..4096 chars.

Execution is **sequential fail-fast**:

```text
fields before first error → actual outcomes
first failing field → failed
later fields → not_attempted
```

No submit.

---

# 12. Type

## `POST .../actions/type`

```text
element_ref
text: string 1..65536
delay_ms: integer 0..1000 default 0
expected_session_revision omitted
dialog_policy omitted
```

No implicit clear.

---

# 13. Press

## `POST .../actions/press`

Request:

```text
key: KeyInput
modifiers: unique array[Alt|Control|Meta|Shift] 0..4
element_ref omitted
expected_session_revision omitted
dialog_policy omitted
```

`KeyInput` identical semantic union to MCP contract:

```text
named key enum
or
single Unicode character/grapheme
```

Named keys:

```text
Enter Tab Escape Backspace Delete
ArrowUp ArrowDown ArrowLeft ArrowRight
Home End PageUp PageDown Insert Space
F1..F12
```

No free-form shortcut grammar; modifiers separate.

---

# 14. Hover

## `POST .../actions/hover`

```text
element_ref
expected_session_revision omitted
```

No coordinates.

---

# 15. Drag

## `POST .../actions/drag`

```text
source_element_ref
target_element_ref
expected_session_revision omitted
dialog_policy omitted
```

No coordinate-script fallback.

---

# 16. Scroll

## `POST .../actions/scroll`

Request:

```text
direction: up | down | left | right
viewport_units: number 0.1..3.0 default 0.8
element_ref omitted
expected_session_revision omitted
```

Without `element_ref` → page/document scrolling context.

With `element_ref` → exact ref validation + requested target must be scrollable on axis.

No silent fallback to page when target is invalid/non-scrollable.

Result:

```text
action_id
page_generation
scroll_state:
  x
  y
  viewport_width
  viewport_height
  at_start_x
  at_end_x
  at_start_y
  at_end_y
```

Scroll does not auto-snapshot.

---

# 17. Wait

## `POST .../actions/wait`

Condition union:

### Duration

```text
milliseconds 0..30000
```

### URL

```text
match exact|contains
value 1..8192
timeout_ms 100..120000 default30000
```

### Element state

```text
element_ref
state attached|visible|hidden|enabled|disabled
timeout_ms 100..120000 default30000
```

### Load state

```text
state domcontentloaded|load
timeout_ms 100..120000 default30000
```

No networkidle baseline, regex or JS predicate.

Timeout = structured non-success, not fake success.

---

# 18. Upload

## `POST .../actions/upload`

Request:

```text
element_ref
content_ids: unique ContentId[] 1..32
expected_session_revision omitted
```

All content owner-authorized/available.

If multiple files supplied, target input must support multi-file; otherwise reject without truncation.

No local path.

Temporary materialization remains session-private/bounded and cleaned after action lifecycle.

---

# 19. Events

## `GET /api/v1/browser/sessions/{session_id}/events`

Query:

```text
page_id optional
type filter optional:
  page|dialog|download|console|network|security|browser
after_sequence optional >=0
limit integer 1..500 default100
```

Response:

```text
events[]
next_sequence | null
gap_detected
```

Sensitive headers/bodies/secrets redacted.

No SSE baseline freeze; additive later review possible.

---

# 20. Downloads

No direct temp-path download endpoint.

Download created by action/navigation is finalized through Content boundary and returned as `ContentRef`/event.

Known direct downloadable HTTP URL normally uses Retrieval.

---

# 21. Retry/idempotency

Browser read operations:

```text
GET session/pages/events
snapshot
wait
```

can use safe read semantics subject to deadlines.

Resource/artifact creation:

```text
session/page create
rendered Content
screenshot
```

requires explicit idempotency contract before blind HTTP client retry.

Stateful mutating actions:

```text
navigate
click
fill/type/press
hover/drag/scroll/upload
```

never blindly retried after uncertain dispatch.

Internal action ledger/status recovery attempts to recover the same action before returning `unknown`.

---

# 22. OpenAPI acceptance

Generated Browser OpenAPI must prove:

- exact paths/methods;
- ElementRef opaque schemas;
- no CSS/XPath/raw JS fields;
- discriminated navigation/screenshot/form/key/wait unions;
- fail-fast form result includes `not_attempted`;
- scroll exact bounds;
- upload list bounds/multi semantics;
- expected revision fields where designed;
- dialog policy schema;
- resource/artifact response refs;
- Browser read/write security requirements;
- common unknown/error response projection.
