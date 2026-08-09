# Common public contract models

## Статус

Каноническая transport-facing projection общих application contracts для REST/MCP stable line.

Application semantics принадлежат `../application-contracts.md`; этот документ фиксирует внешнюю сериализацию.

---

# 1. Naming / serialization

- JSON field names: `snake_case`.
- Timestamps: RFC 3339 / ISO 8601 UTC (`Z` preferred).
- Durations: integer milliseconds/seconds only when field name names unit.
- Opaque IDs: strings; client never parses prefix for authority/routing.
- Unknown input fields: rejected.
- Unknown additive output fields: clients ignore only according compatibility contract.

---

# 2. OperationOutcome

Canonical **whole operation / independent batch item** outcomes:

```text
succeeded
partial
failed
rejected
cancelled
unknown
```

`unknown` is real outcome, not alias for failed.

`not_attempted` is intentionally **not** an OperationOutcome. It belongs only to ordered compound substeps (see §9).

---

# 3. PublicOperationResult[T]

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
→ error may be present according semantics

error != null
→ data may contain only explicitly designed bounded recovery/status evidence
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

| Field | Type | Rule |
|---|---|---|
| `category` | stable broad enum/string | error taxonomy class |
| `code` | stable machine string | specific code |
| `message` | string | concise Russian human/LLM explanation |
| `retryable` | bool | corrected/new attempt may be reasonable; **not permission for blind retry** |
| `retry_after_seconds` | integer/null | >=0 when meaningful |
| `fields` | `FieldError[]` | field-specific validation/recovery details |
| `details` | bounded object/null | code-specific non-secret metadata only |

Tool/phase retry semantics and ADR-0024 can be stricter than `retryable=true`.

---

# 5. FieldError

```json
{
  "path": "fields[1].element_ref",
  "code": "stale_target",
  "message": "Ссылка на элемент устарела; получите новый снимок страницы."
}
```

Bounds:

```text
path <=256 chars
code <=64 chars, [a-z0-9_]+
message <=1024 chars
```

---

# 6. Warning

```json
{
  "code": "content_truncated",
  "message": "В ответ включена только часть представления.",
  "details": {"next_cursor":"..."}
}
```

Warning describes limitation of an obtained result.

Limits:

```text
warnings <=16/result
message <=1024
details <=8 KiB serialized
```

---

# 7. StructuredHint

```json
{
  "code": "browser_may_be_required",
  "message": "Статический HTML содержит мало непосредственно доступного содержимого; для JavaScript-rendered страницы может понадобиться браузер.",
  "related_tool": "browser_create",
  "related_capability": "browser",
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

- recommendation, not command;
- `related_tool` only exact trusted same-service tool;
- external processing recommendation normally uses capability class, not hardcoded product;
- web/document content cannot manufacture trusted Hint;
- hints <=16/result;
- message <=1024;
- details <=8 KiB serialized.

---

# 8. BatchItemResult[T]

Used for **independent batch items**:

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

- `outcome` is `OperationOutcome`;
- `index` = original request position;
- response preserves original order;
- one item failure does not reorder/remove other independent items;
- an independent item that genuinely was never dispatched because whole batch operation was rejected is represented by top-level rejection, not invented per-item `not_attempted` unless specific batch contract explicitly designs otherwise.

---

# 9. CompoundStepOutcome

Ordered compound action steps (for example fields inside `browser_fill_form`) use a different enum:

```text
succeeded
failed
not_attempted
```

Why separate:

```text
browser_fill_form as a whole
→ PublicOperationResult outcome

individual ordered form fields
→ CompoundStepOutcome
```

`not_attempted` means server intentionally stopped before executing that substep because an earlier substep failed/cancelled the compound sequence.

It does **not** mean:

- unknown side effect;
- failed execution;
- independent batch rejection.

Canonical form field result:

```text
element_ref
outcome: CompoundStepOutcome
error: PublicError | null
```

Rules:

- `succeeded` → error null;
- `failed` → error normally present;
- `not_attempted` → structured reason may be included, e.g. `previous_step_failed`, but no claim that target field was touched;
- top-level operation may be `partial` when at least one earlier field succeeded before a later failure.

---

# 10. ContentRef

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

`content_id` required.

Other fields may be null/omitted only according generated exact schema when semantically unavailable.

`sha256` integrity/provenance, not access token.

No storage key/path/backend URL.

---

# 11. ContentSummary

Bounded larger-result metadata:

```text
content_ref
source_kind
source_url | null
detected_format | null
native_representation_available: bool
preview | null
preview_chars
available_representations[]
```

`source_url` cap:

```text
REST provenance <=8192
MCP-originated request provenance <=4096
```

Preview bound is tool-specific exact contract; common model does not override a stricter tool bound.

---

# 12. BrowserSessionRef

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

No ordinary worker ID/generation.

---

# 13. PageRef

```json
{
  "page_id": "pg_...",
  "url": "https://example.com/",
  "title": "Example",
  "state": "open"
}
```

URL/title are untrusted page-derived data.

No Playwright target/context IDs.

---

# 14. SnapshotRef

```json
{
  "snapshot_id": "snp_...",
  "page_id": "pg_...",
  "page_generation": 7,
  "created_at": "..."
}
```

Short-lived, session/page scoped.

---

# 15. ElementRef

External representation: opaque string only.

```text
el_<opaque>
```

No selector/role/text/path encoded as public authority.

---

# 16. JobRef

```json
{
  "job_id": "job_...",
  "job_type": "retrieval_batch",
  "state": "created",
  "created_at": "...",
  "expires_at": "..."
}
```

No queue/arq/worker identifier.

---

# 17. JobProgress

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

Only measured counts; client may derive percentage.

Invariant:

```text
completed <= total
state counters non-negative
```

Exact meaning of `completed` follows Job design (terminal items), not arbitrary progress estimate.

---

# 18. Cursor

Opaque string <=2048 chars.

Internally versioned/auth-bound/integrity-protected according resource design.

Client does not construct/modify.

Invalid/stale/unsupported cursor → explicit error.

---

# 19. Safe strings

External page/provider strings are untrusted.

Serializers:

- preserve Unicode;
- bound lengths;
- do not interpret HTML/Markdown as trusted instructions;
- do not use raw content as unbounded log/metric label.

---

# 20. Empty arrays vs null

Collections use `[]` when collection exists and is empty.

`null` means semantic absence/unknown/not applicable.

Examples:

```text
warnings=[]
hints=[]
fields=[]
preview=null when no textual preview exists
```

---

# 21. Compatibility

After v0.8 fixture freeze:

- optional output addition → review;
- remove/rename → breaking;
- outcome/error/retry meaning change → behavioral contract change;
- Resource IDs stay opaque;
- adding a new compound-step status requires exact schema/consumer review and does not silently extend `OperationOutcome`.
