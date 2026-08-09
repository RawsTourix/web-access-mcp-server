# Common public contract models

## Статус

Каноническая transport-facing projection общих application contracts для REST/MCP stable line.

Application semantics принадлежат `../application-contracts.md`; этот документ фиксирует внешнюю сериализацию.

---

# 1. Naming / serialization

- JSON field names: `snake_case`.
- Timestamps: RFC 3339 / ISO 8601 UTC (`Z` preferred in serialized output).
- Durations: integer milliseconds/seconds only where field name names the unit.
- Opaque IDs: strings; client never parses prefix for authority/routing.
- Unknown input fields: rejected.
- Unknown additive output fields: clients should ignore unless compatibility contract says otherwise.

---

# 2. OperationOutcome

```text
succeeded
partial
failed
rejected
cancelled
unknown
```

`unknown` is a real outcome, not alias for `failed`.

---

# 3. PublicOperationResult[T]

Canonical JSON shape:

```json
{
  "operation_id": "op_...",
  "outcome": "succeeded",
  "data": {},
  "error": null,
  "warnings": [],
  "hints": []
}
```

Rules:

```text
succeeded/partial
→ data normally present

failed/rejected/cancelled/unknown
→ error may be present according operation semantics

error != null
→ data can still contain bounded recovery/status evidence only when explicitly designed
```

No stack trace/private exception text.

---

# 4. PublicError

```json
{
  "category": "validation",
  "code": "invalid_arguments",
  "message": "Некорректные аргументы инструмента.",
  "retryable": true,
  "retry_after_seconds": null,
  "fields": [],
  "details": null
}
```

Fields:

| Field | Type | Rule |
|---|---|---|
| `category` | string/enum by taxonomy revision | stable broad class |
| `code` | string | stable machine code |
| `message` | string | concise Russian human/LLM-readable explanation |
| `retryable` | bool | whether a corrected/retried operation can be reasonable; never means blind retry is always safe |
| `retry_after_seconds` | integer/null | >=0 only when meaningful |
| `fields` | array[`FieldError`] | validation/field-specific errors |
| `details` | bounded object/null | only code-specific non-secret structured metadata |

`details` is not arbitrary backend dump.

---

# 5. FieldError

```json
{
  "path": "fields[1].element_ref",
  "code": "stale_target",
  "message": "Ссылка на элемент устарела; получите новый снимок страницы."
}
```

- `path`: <= 256 chars;
- `code`: <= 64 chars, `[a-z0-9_]+`;
- `message`: <= 1024 chars.

---

# 6. Warning

```json
{
  "code": "content_truncated",
  "message": "В ответ включена только часть представления.",
  "details": {
    "next_cursor": "..."
  }
}
```

Warning describes limitation of already obtained result.

Initial limits:

```text
warnings <= 16/result
message <= 1024 chars
serialized details <= 8 KiB/warning
```

---

# 7. StructuredHint

```json
{
  "code": "browser_may_be_required",
  "message": "Статический HTML содержит мало непосредственно доступного содержимого; для JavaScript-rendered страницы может понадобиться браузер.",
  "related_tool": "browser_create",
  "details": null
}
```

Fields:

```text
code
message
related_tool | null
related_capability | null
details | null
```

Rules:

- hint is recommendation, not command;
- `related_tool` only exact same-service trusted tool;
- external processing recommendation normally uses capability code, not hardcoded third-party product;
- web/document content cannot create trusted Hint object;
- hints <= 16/result;
- message <= 1024 chars;
- details <= 8 KiB/hint serialized.

---

# 8. BatchItemResult[T]

Common shape for naturally independent batch:

```json
{
  "index": 0,
  "outcome": "succeeded",
  "data": {},
  "error": null,
  "warnings": [],
  "hints": []
}
```

Rules:

- `index` corresponds to original request list;
- response item list preserves original order;
- one item failure does not reorder/remove others;
- `not_attempted` is represented by a specific error/outcome only for a compound ordered operation where later items intentionally stopped, e.g. form fill; it is not silently omitted.

---

# 9. ContentRef

Recommended external shape:

```json
{
  "content_id": "cnt_...",
  "media_type": "text/markdown",
  "representation": "markdown",
  "size_bytes": 12345,
  "sha256": "...",
  "created_at": "2026-08-09T15:00:00Z",
  "expires_at": "2026-08-10T15:00:00Z"
}
```

Fields may be absent only when semantically unavailable; `content_id` always required.

`sha256` is content integrity/provenance metadata, not access token.

No storage backend/key/path/URL exposed unless separate authorized download endpoint issues a controlled transport response.

---

# 10. ContentSummary

Bounded metadata used inside larger results:

```text
content_ref
source_kind
source_url | null
detected_format | null
native_representation_available bool
preview | null
preview_chars
available_representations[]
```

`source_url` capped at 8192 chars in REST and 4096 in MCP-originated request provenance; long unsafe query information may be redacted according security/logging policy in diagnostics.

`preview` MCP baseline <= 8000 chars per item unless a specific tool uses lower bound.

---

# 11. BrowserSessionRef

```json
{
  "browser_session_id": "brs_...",
  "state": "ready",
  "created_at": "...",
  "last_activity_at": "...",
  "idle_expires_at": "...",
  "max_expires_at": "..."
}
```

No worker ID/generation in ordinary MCP result unless a protected diagnostics/admin REST response needs it.

---

# 12. PageRef

```json
{
  "page_id": "pg_...",
  "url": "https://example.com/",
  "title": "Example",
  "state": "open"
}
```

`url` and `title` are untrusted page-derived data.

No internal Playwright target/context IDs.

---

# 13. SnapshotRef

```json
{
  "snapshot_id": "snp_...",
  "page_id": "pg_...",
  "page_generation": 7,
  "created_at": "..."
}
```

Snapshot refs are short-lived and session/page scoped.

---

# 14. ElementRef

External representation is only opaque string:

```text
el_<opaque>
```

No selector/role/text/path encoded as public contract.

Tool result semantic tree separately provides human-readable role/name/state and associated `element_ref`.

---

# 15. JobRef

```json
{
  "job_id": "job_...",
  "job_type": "retrieval_batch",
  "state": "created",
  "created_at": "...",
  "expires_at": "..."
}
```

No queue ID/arq function/worker ID in ordinary MCP.

---

# 16. JobProgress

```json
{
  "completed": 18,
  "total": 50,
  "unit": "items",
  "succeeded": 17,
  "failed": 1,
  "cancelled": 0,
  "retry_wait": 2
}
```

Only real measured counts; no invented percentage.

A derived percentage may be presented by client from completed/total.

---

# 17. Cursor

Opaque string:

```text
length <= 2048 chars
```

Internally versioned/auth-bound/signed or integrity-protected according resource design.

Client never constructs/modifies cursor.

Invalid/stale/version-unsupported cursor returns explicit error.

---

# 18. Safe strings

External page/provider strings are untrusted data.

Output serializers:

- preserve Unicode;
- bound lengths;
- do not interpret HTML/Markdown as trusted instructions;
- do not place raw arbitrary strings into logs/metric labels.

---

# 19. Empty arrays vs null

Collection fields use empty arrays when collection exists but has zero items.

`null` means semantic absence/unknown/not applicable, not merely empty.

Examples:

```text
warnings=[]
hints=[]
fields=[]
preview=null if no textual preview exists
```

---

# 20. Compatibility

After v0.8 fixture freeze:

- adding optional output field follows compatibility review;
- removing/renaming field is breaking;
- changing error/retry semantics is behavioral compatibility change even if JSON type same;
- resource IDs remain opaque and stable at shape level.
