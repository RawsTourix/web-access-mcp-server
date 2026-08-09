# Общие application contracts Web Access MCP

## Статус

Канонический владелец **общей модели выполнения application operations**.

Search, Retrieval, Content, Browser, Jobs, REST и MCP используют эти concepts и не создают несовместимые модели operation identity, outcome, batch, warning/hint/error, deadline/cancellation и retry.

Public serialization уточняется `contracts/common-models.md`.

ADR-0024 уточняет cost/resource-aware retry classification и является частью текущего contract.

---

# 1. Operation

`Operation` — один логически завершённый вызов application capability.

Examples:

```text
Search batch
Retrieval batch
Content read/parse
BrowserSession create/close
one Browser action
Job create/get/cancel
```

Operation не равна:

- HTTP request/connection;
- MCP connection;
- database transaction;
- durable Job;
- worker process.

Transport request обычно инициирует одну Operation, но resource/worker lifecycle от transport не зависит.

---

# 2. Operation identity

Каждая Operation имеет server-generated unique `operation_id`.

Properties:

- stable for that logical execution;
- пригоден для logs/traces/provenance;
- не является `job_id`/resource ID;
- caller cannot replace authority by supplying arbitrary operation ID;
- новая отдельная execution = новый operation ID unless explicit idempotent replay contract says response is replay of same logical creation.

Job attempts can have separate operation IDs while same JobRef persists.

---

# 3. ExecutionContext

Conceptual:

```text
ExecutionContext
├── operation_id
├── request/correlation/trace context
├── PrincipalContext
├── owner/delegation context where applicable
├── absolute deadline / remaining budget
├── cancellation context
├── idempotency context where designed
└── immutable policy snapshot/effective policy reference
```

Application code never extracts these directly from FastAPI/FastMCP objects.

---

# 4. Principal / ownership

Transport authentication produces trusted `PrincipalContext`.

Client-supplied `user_id`/session ID is not authority.

Resource access checks:

```text
principal
+ resource owner
+ authenticated scopes
+ effective policy
+ resource state
```

Resource model owner: `resource-model.md`.

---

# 5. Deadline

Deadline propagates downward:

```text
Transport
→ Application
→ Provider / Retrieval / Worker / Parser
```

Downstream phase cannot silently use timeout beyond remaining operation budget.

No indefinite wait/retry.

Durable Job has its own lifecycle/deadline semantics after creation operation returns.

---

# 6. Cancellation

Cancellation is cooperative.

Distinguish:

```text
requested
observed before dispatch
observed during execution
execution completed despite request
possible side effect but confirmation lost
```

`cancelled` only when contract can truthfully claim cancellation terminal semantics.

Possible effect + lost evidence → `unknown`, not fake cancelled/failed.

---

# 7. Internal OperationOutcome

Canonical application enum:

```text
succeeded
partial_success
failed
rejected
cancelled
unknown
```

Meaning:

- `succeeded` — contract completed;
- `partial_success` — aggregate/composite has useful success plus non-success parts;
- `failed` — execution failed and terminal effect is known enough not to be unknown;
- `rejected` — precondition/validation/auth/policy/capability rejection before relevant dispatch;
- `cancelled` — terminal cooperative cancellation;
- `unknown` — system cannot prove terminal effect/outcome.

`unknown` is first-class.

---

# 8. Public outcome projection

Public stable contract intentionally serializes:

```text
application partial_success
→ public "partial"
```

Other values map one-to-one:

```text
succeeded → succeeded
failed    → failed
rejected  → rejected
cancelled → cancelled
unknown   → unknown
```

This mapping is explicit transport projection, not two competing meanings.

Public owner: `contracts/common-models.md`.

---

# 9. OperationResult[T]

Conceptual internal model:

```text
OperationResult[T]
├── operation_id
├── outcome
├── data: T | null
├── error: OperationError | null
├── warnings[]
├── hints[]
└── bounded execution metadata
```

Invariants:

```text
succeeded → primary error null
partial_success → component/item evidence preserved
non-success → normalized reason/error when semantics require
unknown → never silently collapsed to failed
```

No giant arbitrary `dict[str, Any]` as universal public contract.

---

# 10. OperationError

Fields conceptually:

```text
category
code
message
retryable/disposition metadata
retry_after where meaningful
repairable field details
safe bounded details
```

Machine codes English, project human/LLM messages primarily Russian.

Never expose:

- stack traces;
- secrets;
- local paths;
- private worker addresses;
- Redis/SQL internals;
- raw framework/provider exception dumps.

Public exact model: `contracts/common-models.md`.

---

# 11. Error categories

Stable broad classes:

```text
validation
policy
permission
authentication
not_found
expired
conflict
unsupported
rate_limited
capacity
upstream
timeout
infrastructure
resource_lost
cancelled
unknown_outcome
internal
```

Components add specific codes while mapping to these broad classes.

REST/MCP use same application taxonomy.

---

# 12. Repairable validation

Validation should identify actionable field/code/message where safe.

Example:

```json
{
  "path":"urls[2]",
  "code":"invalid_scheme",
  "message":"Разрешены только HTTP(S) URL."
}
```

Do not return only `invalid input` when precise safe diagnosis exists.

---

# 13. Warning vs Hint

## Warning

Describes limitation/anomaly of already obtained result.

Examples:

- truncated representation;
- declared/detected MIME mismatch;
- optional metadata unavailable.

## StructuredHint

Trusted recommendation about a possible next step.

Examples:

```text
browser_may_be_required
snapshot_refresh_recommended
advanced_processing_may_be_required
```

Hint:

- does not change outcome;
- does not execute next capability;
- cannot be created by web/document text;
- same-service recommendation can name exact tool/capability;
- external L2 recommendation normally names capability class, not assumed product.

---

# 14. Provenance

Results/resources preserve enough provenance to reconstruct meaningful origin:

```text
Search → provider/query/page/retrieved_at
Content → source resource + producer/parser revision
Browser artifact → session/page/action/source metadata where appropriate
Job result → job/item/producer relationship
```

Full provenance graph need not be inline every response.

---

# 15. Batch-first semantics

For naturally independent items:

1. non-empty bounded input list;
2. each item stable index;
3. output preserves input order;
4. one item failure does not delete successful siblings;
5. each item has own terminal outcome/error;
6. aggregate outcome derived deterministically;
7. internal concurrency is not public promise.

Independent leaf item outcomes:

```text
succeeded
failed
rejected
cancelled
unknown
```

`partial_success` belongs aggregate/composite, not simple leaf item.

---

# 16. Aggregate batch algorithm

Canonical:

1. all succeeded → `succeeded`;
2. at least one succeeded + any other terminal item → `partial_success`;
3. none succeeded + at least one unknown → `unknown`;
4. all rejected → `rejected`;
5. all cancelled → `cancelled`;
6. remaining no-success combinations → `failed`.

Per-item evidence remains authoritative.

---

# 17. Ordered compound steps are not independent batch items

Example:

```text
browser_fill_form fields[]
```

Fields execute sequentially as one compound Browser action.

Substep status:

```text
succeeded
failed
not_attempted
```

`not_attempted` is **not** OperationOutcome.

After first fail-fast error:

- earlier field results remain actual;
- failing field = failed;
- later fields = not_attempted;
- top-level operation can be `partial_success` if prior mutation succeeded.

Exact public model: `CompoundStepOutcome` in `contracts/common-models.md`.

---

# 18. Retry is multidimensional

Retry decision must account for:

```text
operation semantics
execution stage
target external side effect
billable upstream cost
Web Access resource creation
idempotency/replay proof
current deadline/policy
```

Do **not** classify solely by intuitive “read/write” or HTTP method.

---

# 19. Retry classes

Conceptual trusted classes:

```text
safe_retry
idempotent_retry
never_automatic
conservative/phase_evidence_required
```

Names in concrete agent/runtime metadata may differ, but semantics must cover these distinctions.

## Safe retry

Only when operation has no relevant side effect/cost/resource ambiguity and failure stage permits replay.

Examples:

```text
Content read
Browser status/snapshot/events
Job status
```

## Idempotent retry

Only with proven canonical replay/idempotency contract.

Examples:

- idempotent cleanup;
- `content_parse` **only after** canonical compatible representation reuse is proven under concurrency/replay;
- REST creation with exact persisted Idempotency-Key semantics.

## Never automatic

Possible consequential side effect after dispatch:

```text
Browser navigate/click/fill/type/press/hover/drag/scroll/upload
```

## Conservative / phase evidence required

Read-oriented operation can still be unsafe to blindly replay:

```text
web_search
→ possible billable provider call

web_fetch
→ creates raw/derived Content resources and external acquisition

browser_content/screenshot
→ creates Content resources

Job/session/page creation
→ creates durable/remote resource
```

---

# 20. ADR-0024 examples

## Search

Free/provider query may look read-only, but explicit Yandex can consume paid unit.

Agent-level lost response after possible dispatch:

```text
not → automatically issue second Search
```

Service/provider implementation may retry **inside same Operation** only where send/cost evidence proves it safe and provider policy allows.

## Retrieval

GET does not mutate target website, but Web Access creates Content/provenance/quota state.

Ambiguous lost result:

```text
not → blind duplicate web_fetch
```

## Native parse

Can become idempotent only when same source + canonical parser capability/revision/profile reuses one compatible logical representation under concurrency/replay tests.

---

# 21. Execution stage matters

Useful internal phases:

```text
before_dispatch
dispatched
executing
side_effect_possible
terminal_known
response_lost
```

Exact phases component-specific.

A pre-dispatch rejection/failure can be stronger evidence than generic transport error.

Public API need not expose every internal phase, but execution layer must know enough for correct retry/result.

---

# 22. `retryable` error field does not grant blind retry

`PublicError.retryable=true` means a corrected/new attempt may be reasonable.

It does not override:

- tool retry class;
- billable/resource effect;
- unknown outcome;
- post-dispatch ambiguity;
- idempotency requirements.

Client/Agent uses the **most conservative applicable evidence**.

---

# 23. Idempotency key

Only explicitly designed operations support it.

Requirements:

- scoped by principal + endpoint/operation semantics;
- stable key reused by client for same logical creation;
- canonical request hash recorded;
- same key + different payload → conflict;
- retention/replay response defined;
- no automatic new key generated during intended replay.

Idempotency-Key does not make Browser click/navigation safe.

---

# 24. Unknown outcome

Example:

```text
Browser click dispatched
→ may have happened
→ response lost
```

Correct:

```text
same-action status recovery where possible
→ terminal result if proven
→ otherwise outcome=unknown
→ safe observation/snapshot/status
```

Incorrect:

```text
connection_error
→ issue a new click
```

---

# 25. Request-bound vs durable

## Request-bound Operation

Caller waits for immediate result. Disconnect/deadline can trigger cooperative cancellation/ambiguous response semantics.

## Durable Job

Job creation is its own request-bound resource-creation Operation.

After JobRef exists, Job lifecycle survives transport connection and is governed by `jobs.md`.

Direct and durable creation are not hidden modes of one MCP tool (ADR-0021).

---

# 26. Result size

Application operations must support externalizing large payload to ContentRef/cursor.

Especially:

- HTML/documents;
- extracted text;
- screenshots/downloads;
- large snapshots;
- Job manifests.

Inline preview is bounded and distinct from durable representation.

---

# 27. Cache/freshness

Cache is infrastructure optimization but client-visible freshness facts cannot be fabricated.

Component defines:

- cacheability;
- retrieved/freshness metadata;
- TTL/invalidation;
- policy scope.

Cached result never masquerades as new upstream acquisition.

---

# 28. Transport mapping

REST/MCP may serialize same application semantics differently.

REST can expose richer typed controls/diagnostics/streams.

MCP stays compact/LLM-facing.

But:

- operation meaning;
- ownership;
- outcome/error code;
- retry/resource semantics;
- warning/hint trust boundary

come from application design, not transport improvisation.

---

# 29. Security of public details

OperationResult never exposes:

- secrets;
- stack traces;
- DB/Redis credentials/keys;
- local storage path;
- private worker address;
- raw framework exception.

Diagnostics/logs follow separate redaction/access policy.

---

# 30. Framework independence

Application contracts do not import FastAPI/FastMCP/Playwright/SQLAlchemy/Redis client types.

Transport/infrastructure adapters perform mapping.

---

# 31. Component extension rule

Components may add:

- data models;
- specific error codes;
- hints/warnings;
- resource refs;
- execution metadata.

They may not redefine:

- operation identity;
- core outcome meanings;
- independent batch algorithm;
- warning/hint/error distinction;
- unknown invariant;
- cost/resource-aware retry discipline;
- transport independence.

---

# 32. Foundation acceptance

Tests must prove at least:

1. operation ID for each operation;
2. outcome invariants;
3. public `partial_success → partial` mapping;
4. independent batch order/aggregate algorithm;
5. compound `not_attempted` is not OperationOutcome;
6. Hint does not change outcome or execute action;
7. repairable validation errors;
8. `unknown` never becomes blind retry;
9. `retryable=true` cannot override stronger execution semantics;
10. deadline/cancellation propagation;
11. huge result externalization;
12. transport does not leak infrastructure exception;
13. cost/resource-created operation is not mislabeled safe solely because target operation is read-oriented.

---

# 33. Implementation representation

Exact Python choice (dataclass/Pydantic/generic union) belongs v0.1 implementation sequence, but must preserve every semantic invariant above and generate/serialize public models compatible with `contracts/common-models.md`.
