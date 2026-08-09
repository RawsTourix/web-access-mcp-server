# Exact Admin/Operations REST API v1 contract

## Статус

Каноническое расширение `contracts/rest-api-v1.md` для protected operator/admin surface Web Access v1.

Semantic owner:

- `../policy-and-operations.md`;
- `../operational-readiness.md`;
- ADR-0019/0020.

Exact policy models:

- `policy-models.md`.

Все endpoints требуют authenticated admin/operator principal. Read endpoints требуют `admin:read`, mutations — `admin:write` (и могут дополнительно требовать deployment network policy).

No MCP projection baseline.

---

# 1. Общие правила

Base:

```text
/api/v1/admin
```

- unknown input fields rejected;
- all mutation requests include explicit typed input, never generic command string;
- all required admin mutations append `AuditEvent` transactionally with mutation where design requires it;
- no secrets/DSNs/bearer/API keys/raw Redis payloads/SQL exposed;
- large collections use opaque cursor pagination;
- admin responses are still bounded;
- `reason` required for security/operational mutations, `1..2048` chars;
- principal IDs are sensitive operational metadata and never metric labels.

---

# 2. Current global policy

## `GET /api/v1/admin/policy`

Returns `PolicySnapshot` metadata from `policy-models.md`:

```text
revision
schema_version
created_at
created_by
reason
global_policy
principal_override_count
```

Does **not** inline all principal overrides.

---

# 3. Update global policy

## `PUT /api/v1/admin/policy`

Request:

```text
expected_revision: integer >=1
global_policy: GlobalPolicyDocument
reason: string 1..2048
```

Semantics:

1. validate current revision CAS;
2. validate structural schema;
3. validate provider/job registries/static hard ceilings;
4. preserve existing principal overrides;
5. materialize new complete logical policy state;
6. insert new policy revision;
7. move current pointer;
8. append AuditEvent;
9. commit atomically.

Response:

```text
new PolicySnapshot metadata
```

Stale revision → `409 policy_revision_conflict`.

No PATCH/merge-patch v1 baseline. Full global section replacement keeps mutation deterministic.

---

# 4. Principal policy override list

## `GET /api/v1/admin/policy/principals`

Query:

```text
cursor: opaque <=2048 optional
limit: integer 1..100 default 50
principal_id_prefix: string 1..128 optional
```

Prefix filter is exact bounded identifier prefix matching for operator discovery, not regex/expression language.

Response:

```text
items[]:
  principal_id
  policy_revision
  updated_at
  updated_by
  disabled_capabilities
  override_sections: array[search|retrieval|content|browser|jobs]
next_cursor | null
```

No full override documents for entire page unless explicitly requested individually.

---

# 5. Read one principal override

## `GET /api/v1/admin/policy/principals/{principal_id}`

Returns:

```text
policy_revision
principal_id
override: PrincipalPolicyOverride
updated_at
updated_by
```

If no explicit override exists → `404 principal_policy_override_not_found`.

Effective global defaults can be inspected separately via `/admin/policy`.

---

# 6. Create/replace principal override

## `PUT /api/v1/admin/policy/principals/{principal_id}`

Request:

```text
expected_revision: integer >=1
override: PrincipalPolicyOverride
reason: string 1..2048
```

Cross-field:

```text
override.principal_id == path principal_id
```

Mutation creates a **new global policy revision N+1** even though only one principal override changed.

Validation ensures override cannot:

- enable globally disabled capability;
- mint absent auth scope;
- allow provider not globally enabled;
- exceed global maxima/static software ceilings;
- reference unknown provider/job type.

Response returns updated principal override metadata + new top-level policy revision.

Stale revision → 409.

---

# 7. Delete principal override

## `DELETE /api/v1/admin/policy/principals/{principal_id}`

JSON request body:

```text
expected_revision: integer >=1
reason: string 1..2048
```

Deleting override does not delete principal/account; it causes future EffectivePolicy to inherit global defaults after new policy revision.

Idempotency:

- existing override → remove + new revision;
- already absent → structured `already_absent` success with current revision, no synthetic extra revision required.

---

# 8. Policy revision history

## `GET /api/v1/admin/policy/revisions`

Query:

```text
cursor optional <=2048
limit 1..100 default 50
created_after timestamp optional
created_before timestamp optional
actor_principal_id optional 1..128
```

Response items use `PolicyRevisionSummary` from `policy-models.md`:

```text
revision
schema_version
created_at
created_by
reason
changed_sections[]
principal_ids_changed[] bounded
principal_ids_truncated
```

Newest-first stable ordering baseline.

---

# 9. Policy revision detail

## `GET /api/v1/admin/policy/revisions/{revision}`

Returns:

```text
revision metadata
global_policy
principal_override_count
changed_sections
```

Does not inline all historical principal overrides.

Optional query:

```text
principal_id: string 1..128
```

When provided, response additionally returns the override for that principal as it existed in that revision (or null).

This supports forensic/debug comparison without giant snapshot response.

---

# 10. Policy rollback

## `POST /api/v1/admin/policy/rollback`

Request:

```text
expected_revision: integer >=1
target_revision: integer >=1
reason: string 1..2048
```

Rollback:

- loads target logical policy state;
- validates it against current software/runtime registries;
- creates **new monotonic revision**;
- never reuses old revision number/current flag;
- writes AuditEvent atomically.

Incompatible target policy → structured rejection, no partial rollback.

---

# 11. Provider operational status

## `GET /api/v1/admin/providers`

Query:

```text
provider_id optional 1..64
```

Response item:

```text
provider_id
name
enabled_by_policy
configured
billable
readiness: ready | degraded | unavailable | disabled
readiness_code | null
rate_policy bounded summary
concurrency_policy bounded summary
budget:
  period | null
  consumed_units | null
  reserved_units | null
  default_limit | null
  maximum_limit | null
last_success_at | null
last_failure_at | null
```

No endpoint/API key/folder secret/raw upstream payload.

Provider enable/default/budget changes happen through typed global policy update, not a second competing configuration source.

---

# 12. Principal usage read

## `GET /api/v1/admin/usage/principals/{principal_id}`

Returns durable/materialized usage summary:

```text
principal_id
usage_revision
active_browser_sessions
nonterminal_jobs
active_job_attempts
retained_content_bytes
retained_content_objects
provider_period_usage[]
updated_at
```

Provider usage item:

```text
provider_id
period
after/before boundary timestamps
consumed_units
reserved_units
limit_units | null
```

This is operator diagnostics, not billing invoice.

---

# 13. Usage collection

## `GET /api/v1/admin/usage/principals`

Query:

```text
cursor optional
limit 1..100 default 50
min_active_browser_sessions optional >=0
min_nonterminal_jobs optional >=0
```

Returns bounded summaries + cursor.

No arbitrary sort/expression language.

---

# 14. Browser Worker status

## `GET /api/v1/admin/browser/workers`

Query:

```text
state optional ready|draining|fenced|lost
cursor optional
limit 1..100 default 50
```

Response:

```text
worker_id
worker_generation
state
runtime_revision
active_sessions
capacity
last_heartbeat_at
lease_expires_at | null
```

No internal credential.

---

# 15. Browser Worker drain

## `POST /api/v1/admin/browser/workers/{worker_id}/drain`

Request:

```text
expected_generation: integer >=1
deadline_seconds: integer 10..3600 default 300
reason: string 1..2048
```

Semantics:

- generation-safe;
- mark/advertise draining;
- no new sessions;
- existing sessions close according Browser drain contract;
- after deadline bounded terminate/kill remaining session subprocesses;
- AuditEvent required.

Stale generation → conflict.

No arbitrary PID/kill signal endpoint.

---

# 16. Job Worker status

## `GET /api/v1/admin/job-workers`

Response same operational principles:

```text
worker_id
worker_generation
state
runtime_revision
active_attempts
capacity
supported_job_types/revisions
last_heartbeat_at
```

Bounded list/cursor if needed.

---

# 17. Job Worker drain

## `POST /api/v1/admin/job-workers/{worker_id}/drain`

Request:

```text
expected_generation >=1
deadline_seconds 10..3600 default 300
reason 1..2048
```

No new claims after drain admission. Existing attempts follow Job lifecycle/cancellation/lease semantics; no silent result discard.

Audit required.

---

# 18. Job/outbox backlog

## `GET /api/v1/admin/jobs/backlog`

Returns aggregate bounded state:

```text
jobs_by_state
jobs_by_type
oldest_queued_age_seconds | null
outbox_pending_count
outbox_oldest_age_seconds | null
active_attempts
retry_wait_count
worker_capacity
admission_status
```

No raw Redis/arq messages.

---

# 19. Audit event list

## `GET /api/v1/admin/audit`

Query:

```text
cursor optional <=2048
limit 1..100 default 50
actor_principal_id optional 1..128
action_code optional 1..128
outcome optional
created_after/created_before optional timestamps
```

Response item:

```text
audit_id
timestamp
actor_principal_id
delegated_subject | null
action_code
resource_refs[] bounded
policy_revision | null
outcome
operation_id | null
request_id | null
metadata bounded/redacted
```

No page/document/form secret payload.

Audit API is read-only; no update/delete event endpoint.

---

# 20. Maintenance action model

Maintenance endpoints are **typed individually**.

Common mutation fields:

```text
reason: string 1..2048
dry_run: bool where meaningful
max_items: bounded integer where meaningful
```

No:

```text
POST /maintenance {"command":"..."}
```

---

# 21. Content reconciliation/GC

## `POST /api/v1/admin/maintenance/content-reconcile`

Request:

```text
max_items: integer 1..10_000 default 1000
dry_run: bool default false
reason: string 1..2048
```

Runs/requests one bounded reconciliation pass through existing Content lifecycle.

## `POST /api/v1/admin/maintenance/content-gc`

Request same bounds.

GC never accepts physical storage key from caller. It discovers eligible resources through application state/ref checks.

Mutating non-dry-run action audited.

---

# 22. Job/outbox reconciliation

## `POST /api/v1/admin/maintenance/jobs-reconcile`

Request:

```text
max_items 1..10_000 default 1000
dry_run bool default false
reason
```

May:

- detect stale attempts;
- re-materialize due wake-up/outbox state;
- finalize recoverable Job state;

only through canonical Job state machine.

No arbitrary re-run function.

---

# 23. Usage reconciliation

## `POST /api/v1/admin/maintenance/usage-reconcile`

Request:

```text
principal_id optional 1..128
max_principals 1..10_000 default 1000
dry_run bool default false
reason
```

Recomputes/reconciles materialized durable resource usage against authoritative rows.

Billable provider ledger is **not** blindly recomputed/refunded by generic resource reconciliation.

---

# 24. Provider status refresh

## `POST /api/v1/admin/maintenance/providers-refresh`

Request:

```text
provider_ids: array[ProviderId] 1..32 optional
reason: string 1..2048
```

Omitted provider_ids → all configured providers, bounded by registry max.

Refreshes capabilities/readiness metadata only; does not change credentials/policy and does not issue arbitrary search queries beyond explicitly designed provider health probes.

---

# 25. Eligible Job recovery/requeue

No generic force-rerun endpoint.

If operational recovery is needed, exact endpoint:

```text
POST /api/v1/admin/jobs/{job_id}/recover
```

Request:

```text
expected_revision: integer >=0
reason: string 1..2048
```

Application accepts only if current Job state is a **designed recoverable state** and canonical reconciler/job state machine agrees recovery is safe.

Succeeded items remain checkpointed; no blind full rerun.

If not eligible → structured conflict/rejection.

Audit required.

---

# 26. Admin status

## `GET /api/v1/admin/status`

Returns protected capability-aware summary:

```text
build/runtime revision
policy current revision/schema/age
PostgreSQL status
Redis status
ContentStore status
Search provider matrix
Browser worker capacity
Job worker/backlog capacity
maintenance/reconciler status
contract revisions
```

No secret/internal raw connection string.

---

# 27. Response limits

Admin diagnostics remain bounded:

- lists use cursor + `limit<=100` baseline;
- maps by known enum/job/provider state bounded by registry;
- metadata blobs have explicit serializer max;
- no full policy history snapshot bundle in one response;
- no raw logs/SQL/Redis dump.

---

# 28. OpenAPI/security gate

Generated OpenAPI must prove:

- every `/api/v1/admin/*` route has explicit admin security requirement;
- mutation request schemas have exact bounds and descriptions;
- no admin route appears in MCP tool catalog;
- policy DTO references `policy-models.md` equivalent generated schemas;
- worker drain generation required;
- maintenance actions are typed, not generic command;
- audit endpoint has no mutation methods;
- provider/usage responses redact secrets.
