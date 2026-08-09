# v0.7 — Distributed Operations & Policy Hardening

## Статус

`ready for implementation`

v0.7 не добавляет новую web capability. Она делает уже работающие Search/Retrieval/Content/Browser/Jobs управляемыми и предсказуемыми в multi-replica/multi-principal production deployment.

---

# 1. Цель

После v0.7 operator должен безопасно:

- менять non-secret task/resource policy без redeploy;
- задавать principal quotas;
- ограничивать billable provider usage;
- управлять Content retention defaults;
- наблюдать provider/worker/job/storage state;
- draining workers generation-safe;
- запускать только typed bounded maintenance;
- получать durable operator/security audit;

при этом replicas используют одну revisioned logical policy state, а durable quota/accounting correctness не зависит от Redis counters.

---

# 2. Prerequisites

- accepted v0.1–v0.6;
- `../../policy-and-operations.md`;
- `../../security.md`;
- `../../observability.md`;
- `../../deployment.md`;
- `../../persistence.md`;
- `../../search.md`;
- `../../browser.md`;
- `../../jobs.md`;
- `../../contracts/policy-models.md`;
- `../../contracts/admin-api-v1.md`;
- ADR-0019 dynamic policy registry;
- ADR-0020 durable quota/accounting;
- ADR-0023 admin control-plane authority.

---

# 3. Explicit non-goals

v0.7 не вводит:

- user account/password product;
- OAuth/OIDC implementation;
- arbitrary RBAC/expression policy language;
- billing/invoice system;
- secret-management UI;
- MCP admin tools;
- generic SQL/Redis/shell maintenance;
- scheduler/workflow engine;
- architecture rewrite single-node→distributed;
- dynamic policy control над собственным admin recovery API.

---

# 4. Dynamic policy model

Exact v1 model: `../../contracts/policy-models.md`.

Logical state:

```text
GlobalPolicyDocument
+
exact PrincipalPolicyOverride exceptions
→ immutable policy revision
```

Every mutation creates monotonic top-level revision.

Public admin API разделяет global policy и principal overrides, чтобы оператор не пересылал giant document со всеми exceptions.

Persistent implementation ADR-0019 materializes complete validated logical snapshot/state per revision.

---

# 5. Dynamic task capabilities

Exact v1:

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

Effective task permission:

```text
AuthProvider task scope
∩ global policy
∩ principal override restrictions
∩ ownership/resource policy
```

Policy can restrict, not mint absent task scope.

---

# 6. Admin authority

Согласно ADR-0023:

```text
admin:read / admin:write
```

принадлежат AuthProvider/deployment control plane и **не входят dynamic TaskCapabilityCode**.

Dynamic policy не может self-lockout policy read/update/rollback.

Admin API всё равно защищён:

- dedicated scopes;
- deployment/network boundary;
- exact typed DTO;
- software hard ceilings;
- optimistic revisions;
- audit.

Full deployment disable admin surface — static deployment decision with documented recovery path.

---

# 7. Durable policy state

PostgreSQL:

```text
policy_revisions
current_policy
```

Each revision includes schema version and complete validated logical state/normalized representation.

Update transaction:

```text
expected revision CAS
→ validate exact policy models + runtime registries + hard ceilings
→ create revision N+1
→ update current pointer
→ AuditEvent
→ commit
```

Rollback creates a new revision; history remains monotonic.

---

# 8. Policy distribution

Control Plane replica:

- loads valid current snapshot startup;
- immutable in-process reference;
- revision poll target <=5 s + jitter;
- optional Redis invalidation acceleration;
- lost invalidation recovered by DB poll;
- incompatible/invalid newer snapshot produces degraded/fail-safe state.

High-risk **task** admission stale grace baseline <=30 s.

---

# 9. Durable usage/accounting

New durable state covers:

```text
principal_usage
provider usage periods/reservations/events
audit_events
```

Materialized principal usage baseline:

```text
active_browser_sessions
nonterminal_jobs
active_job_attempts
retained_content_bytes
retained_content_objects
```

Counters reconcile against authoritative resources.

Redis reset cannot reset durable quota consumption.

---

# 10. Browser quota

BrowserSession creation needs:

```text
task scope/policy
→ durable principal session slot
→ Browser create rate
→ deployment/worker capacity
```

Principal slot acquired transactionally enough to avoid multi-replica oversubscription and released exactly once on terminal logical lifecycle.

Worker physical capacity remains separate.

---

# 11. Job quota/fairness

Enforce:

- nonterminal Jobs/principal;
- active JobAttempts/principal;
- per-job-type/global attempt policy;
- Job create rate;
- global backlog admission.

Hot-principal backlog must not permanently consume all workers.

Quota-unavailable claim defers through durable scheduling, not busy loop.

---

# 12. Content logical storage quota

Charge logical owner-visible available ContentObjects, not deduplicated physical storage bytes.

Availability transition + usage accounting must prevent concurrent oversubscription.

Expiry/delete releases exactly once.

Same physical blob referenced by two owners counts independently for logical quota.

---

# 13. Billable provider budgets

Billable providers use durable **provider units**, not currency hardcoded in adapter.

Before actual paid upstream attempt:

```text
idempotent usage_attempt reservation
→ upstream send
→ consumed/released finalization based on evidence
```

Possible sent/billed + unknown response → conservative consumption.

Retry creates separate reservation.

Cache hit does not consume upstream unit.

---

# 14. Retention policy

v0.7 centralizes at least:

```text
transient
job_result
```

TTL defaults move from scattered settings into typed dynamic global policy within software ceilings.

Principal override changes storage quota, not arbitrary infinite/custom TTL in v1 baseline.

---

# 15. Admin REST

Exact namespace: `../../contracts/admin-api-v1.md`.

Includes:

```text
current global policy
principal override CRUD/list
policy revision history/detail/rollback
provider status/budget summary
principal usage
Browser Worker list/drain
Job Worker list/drain
Job/outbox backlog
audit list
bounded Content/Jobs/Usage/provider maintenance
protected status
```

No admin MCP tools.

No generic maintenance command.

---

# 16. Worker drain

Browser/Job worker drain:

- uses stable worker ID + expected generation;
- blocks new work;
- preserves component lifecycle semantics for active work;
- bounded deadline;
- audited;
- stale generation rejected.

No arbitrary PID kill public endpoint.

---

# 17. Typed maintenance

Only explicit bounded operations:

- Content reconcile/GC;
- Job/outbox reconcile;
- Usage reconcile;
- provider status refresh;
- eligible Job recover through state machine.

No raw storage key, SQL, Redis, shell or arbitrary function name input.

---

# 18. Audit

Required admin mutation + `AuditEvent` commit atomically.

Audit fields include actor/action/resource/policy revision/outcome/correlation + bounded redacted metadata.

Never store:

- auth/provider secrets;
- full page/document content;
- form/password values;
- arbitrary giant bodies.

Audit application semantics append-only.

---

# 19. Capability-aware health/readiness

Detailed protected status distinguishes examples:

```text
search provider ready/degraded/disabled/budget_exhausted
retrieval ready/degraded
content store/parser/maintenance state
browser ready/no_workers/egress_unavailable
jobs ready/queue_unavailable/no_workers/backlog_limit
policy current/stale/incompatible
```

Public liveness remains minimal/non-sensitive.

---

# 20. Rolling compatibility

Mixed old/new replicas/workers tests cover:

- policy schema readable overlap;
- policy cannot become current before rollout support;
- Job handler revisions;
- Browser runtime revisions;
- expand-first DB migrations;
- current revision refresh under mixed deployment.

---

# 21. MCP impact

No admin tools are added.

Existing task tools only gain normalized policy/quota outcomes/codes such as:

```text
capability_disabled_by_policy
rate_limited
resource_quota_exceeded
storage_quota_exceeded
billable_budget_exceeded
job_backlog_limit
```

MCP schemas cannot gain operator settings as arguments.

---

# 22. Required tests

At minimum:

- global policy CAS conflict;
- principal override create/replace/delete with revision bump;
- dynamic schema rejects `admin` task capability;
- authorized admin can recover from task policy disabling all task capabilities;
- lost Redis invalidation + polling refresh;
- stale/incompatible policy behavior;
- Browser/Job/Content quota races;
- UsageReconciler drift;
- billable double-spend/unknown accounting;
- policy lowering below current usage;
- audit atomic rollback;
- worker drain generation races;
- hot-principal fairness;
- maintenance bounds;
- admin auth/network restrictions;
- no secrets in policy/audit/status.

---

# 23. Definition of Done

v0.7 complete only if:

1. Exact policy/admin contracts implemented and OpenAPI-tested.
2. Policy revision works across replicas within bounded staleness.
3. Dynamic task policy cannot mint auth scope or self-disable admin recovery control plane.
4. Durable quotas survive Redis loss.
5. Concurrent resource creation cannot oversubscribe principal quota.
6. Billable provider budget cannot double-spend through replica race.
7. Admin mutations are audited transactionally.
8. No admin MCP tools exist.
9. Worker drain is typed/generation-safe.
10. Health/readiness is capability-aware.
11. Fairness/load gates pass.
12. Applicable production/HA release gates green.
