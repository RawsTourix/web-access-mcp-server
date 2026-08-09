# v0.7 — Implementation sequence

## Назначение

Обязательный порядок реализации distributed policy/operator hardening поверх accepted v0.1–v0.6.

Ключевой принцип:

> Сначала durable policy/quota/audit correctness и multi-replica behavior. Только затем protected Admin REST. MCP operator tools не создаются.

Exact public targets:

- `../../contracts/policy-models.md`;
- `../../contracts/admin-api-v1.md`;
- ADR-0019/0020/0023.

---

# P0 — Preconditions

До кода:

- v0.1–v0.6 gates green;
- multi-replica test profile;
- Redis/PostgreSQL failure injection;
- static hard ceilings inventoried;
- current auth scopes/principals tested;
- no admin MCP tools;
- exact policy/admin contract fixtures prepared as schema tests.

**Gate:** baseline stable before policy migration.

---

# P1 — Exact typed policy models

Implement immutable typed models exactly from `contracts/policy-models.md`:

```text
GlobalPolicyDocument
GlobalCapabilityPolicy
GlobalSearchPolicy
GlobalRetrievalPolicy
GlobalContentPolicy
GlobalBrowserPolicy
GlobalJobsPolicy
GlobalAuditPolicy
PrincipalPolicyOverride + typed sub-overrides
EffectivePolicy
PolicySnapshot metadata
```

Rules:

- unknown fields forbidden;
- no secrets/endpoints/credentials;
- task capabilities exact 8-value enum;
- `admin` rejected as dynamic task capability;
- global default<=maximum;
- override<=global maximum<=static hard ceiling;
- provider/job registry cross-validation;
- no arbitrary policy dictionary/expression language.

Unit/schema tests before persistence.

---

# P2 — Policy persistence/revision model

Migration baseline:

```text
policy_revisions
current_policy
```

Implement ADR-0019:

- immutable complete logical snapshot/state per revision;
- schema version;
- current pointer CAS;
- bootstrap policy;
- rollback-as-new-revision;
- principal override state addressable without requiring public giant whole-policy update.

Implementation may store JSONB complete snapshot according ADR baseline while application exposes global/override views.

No REST yet.

---

# P3 — Policy effective composition/cache

Implement:

```text
PrincipalContext task scopes
+ current GlobalPolicy
+ exact principal override
→ EffectivePolicy
```

Control Plane:

- startup load;
- immutable atomic swap;
- revision poll <=5s target + jitter;
- optional Redis invalidation;
- last-known-good;
- high-risk task stale grace/fail-closed;
- bounded per-principal effective cache invalidated by top-level revision.

Admin authority is not read from EffectivePolicy.

Multi-replica tests including lost invalidation/DB outage.

---

# P4 — Admin authority boundary

Implement ADR-0023 before Admin REST:

```text
admin:read/admin:write
→ trusted AuthProvider scopes
→ deployment/network policy
```

Tests:

- dynamic policy enables zero task capabilities;
- authorized admin still can GET/PUT/rollback policy;
- non-admin cannot;
- policy schema rejects `admin` capability;
- static deployment disable behavior explicit/tested where profile supports it.

No universal hardcoded break-glass secret.

---

# P5 — Audit foundation

Migration `audit_events`.

Append-only application service/repository.

Required admin mutation transaction helper:

```text
mutation + AuditEvent → same commit
```

Audit append failure rolls back required mutation.

Redaction tests: no bearer/API secrets/page text/form values.

---

# P6 — Durable usage/accounting schema

Migration according ADR-0020:

```text
principal_usage
provider_usage_periods
provider_usage_reservations/events
```

Track at least:

```text
active_browser_sessions
nonterminal_jobs
active_job_attempts
retained_content_bytes
retained_content_objects
```

Implement lock/CAS ordering and concurrent race tests before component integration.

---

# P7 — Browser quota integration

BrowserSession create:

```text
EffectivePolicy
→ durable principal slot reservation
→ worker placement/capacity
→ session create
```

Release slot exactly once on terminal logical state.

Tests:

- concurrent last slot across API replicas;
- worker create failure;
- close/expire/lost;
- duplicate terminal transition;
- UsageReconciler drift repair.

---

# P8 — Job quota/fairness integration

Job create uses nonterminal quota.

Job claim uses active-attempt quota.

Per-job-type/global caps from exact policy.

Tests:

- principal A sustained backlog vs principal B small jobs;
- quota deferral without busy-loop;
- worker crash/lease and quota accounting;
- global backlog=0 rejects new Job creation.

---

# P9 — Content logical storage quota

Integrate before logical `creating → available` where retained quota applies.

Charge logical ContentObject size/count per owner.

Tests:

- concurrent finalize last bytes/object slot;
- same physical hash/different owners;
- derived representation;
- reuse;
- expiry/delete release exactly once;
- quota rejection leaves cleanup to normal staging reconciler.

---

# P10 — Billable provider budget

Integrate `BudgetPort` in paid Search path.

Implement:

- UTC period rows;
- provider units;
- idempotent `usage_attempt_id` reservation;
- finalize consumed/released by send evidence;
- conservative unknown accounting;
- retry = separate reservation;
- principal override units <= global maximum;
- cache hit = zero upstream budget reservation.

Race/double-spend tests across replicas.

---

# P11 — Redis flow policy integration

Map existing distributed limiters to EffectivePolicy:

- Search rate/concurrency;
- Retrieval rate/concurrency;
- Browser create rate;
- Job create rate where appropriate;
- request-bound flow controls.

Redis failure class explicit; security/cost critical admissions conservative.

No duplicate per-transport limiter logic.

---

# P12 — Retention policy migration

Move current transient/job-result TTL defaults into typed GlobalContentPolicy.

Rules:

- values within static ceilings;
- existing resource lifecycle remains authoritative;
- no principal-specific arbitrary TTL;
- no infinite client retention;
- resource records policy/revision where required for deterministic cleanup behavior.

---

# P13 — Admin global policy REST

Implement exact:

```text
GET /api/v1/admin/policy
PUT /api/v1/admin/policy
```

Requirements:

- `admin:read/write`;
- expected top-level revision;
- exact GlobalPolicyDocument;
- reason required;
- preserve current principal overrides on global update;
- mutation+audit atomic;
- actual OpenAPI tests.

---

# P14 — Admin principal override REST

Implement:

```text
GET    /api/v1/admin/policy/principals
GET    /api/v1/admin/policy/principals/{principal_id}
PUT    /api/v1/admin/policy/principals/{principal_id}
DELETE /api/v1/admin/policy/principals/{principal_id}
```

Every effective change bumps top-level policy revision.

Tests:

- override inherit/defaults;
- allowed provider intersection;
- max-bound violation;
- duplicate/replace;
- delete→global defaults;
- 10k software override ceiling;
- auth/self-lockout safety.

---

# P15 — Revision history/rollback REST

Implement exact:

```text
GET  /api/v1/admin/policy/revisions
GET  /api/v1/admin/policy/revisions/{revision}
POST /api/v1/admin/policy/rollback
```

Rollback validates target against current runtime/static constraints and creates new monotonic revision + audit.

No history overwrite/current old revision reuse.

---

# P16 — Protected provider/usage/status REST

Implement bounded read endpoints from `contracts/admin-api-v1.md`:

- provider status/budget summary;
- principal usage single/list;
- admin capability/status summary;
- Job/outbox backlog.

No credentials/internal raw URLs/Redis messages.

Cursor/bounds exact.

---

# P17 — Worker status/drain

Implement Browser and Job Worker protected lists + generation-safe drain.

Drain request requires expected generation, bounded deadline, reason and audit.

Tests stale generation/restart/concurrent drain/rolling deployment.

No PID kill endpoint.

---

# P18 — Audit read REST

Implement bounded read-only audit list/filter endpoint.

No update/delete audit API.

Verify metadata redaction/cardinality.

---

# P19 — Typed maintenance REST

Implement only exact approved endpoints:

- Content reconcile;
- Content GC;
- Jobs/outbox reconcile;
- Usage reconcile;
- provider status refresh;
- eligible Job recovery.

Each mutation typed/bounded/audited.

No generic command/function/SQL/Redis string.

---

# P20 — UsageReconciler

Recompute/repair in bounded multi-replica-safe batches:

- active Browser slots;
- nonterminal Jobs;
- active attempts;
- retained logical Content bytes/objects.

Emit drift metrics/audit warning.

Do **not** blindly recompute/refund billable provider ledger.

---

# P21 — Capability-aware health/readiness

Finalize protected readiness matrix including:

- policy revision/schema/age;
- provider enabled/readiness/budget;
- Retrieval;
- ContentStore/parsers/reconciliation;
- Browser workers/egress/capacity;
- Jobs Redis/workers/backlog/outbox/reconciler.

Public liveness minimal.

---

# P22 — Rolling compatibility

Mixed old/new runtime tests:

- policy schema overlap;
- new schema cannot become current too early;
- Job handler revision;
- Browser worker revision;
- expand-first DB migrations;
- stale policy behavior;
- admin recovery during task-policy restrictive changes.

---

# P23 — Security/audit review

Verify:

- no secrets in policy/audit/status;
- policy cannot mint task scope;
- policy cannot contain `admin` task capability;
- admin scopes/network required;
- policy-control plane not self-lockable by dynamic policy;
- audit required mutation rollback;
- usage endpoints admin-only;
- principal IDs absent from unbounded metrics.

---

# P24 — Load/fairness/HA roast

Run:

- multi-replica quota races;
- policy update/override storm;
- hot principal fairness;
- Redis restart/lost invalidation;
- DB transient/failover cases;
- usage row contention;
- billable reservation contention;
- S3 shared profile;
- worker rolling drains;
- retention/GC concurrency;
- admin read pagination with large override/audit sets.

Measure before considering sharded usage counters or normalized policy storage optimization.

---

# P25 — Facade compatibility

REST actual OpenAPI must match:

```text
contracts/policy-models.md
contracts/admin-api-v1.md
```

MCP:

- no admin tools;
- existing task schemas unchanged except compatible normalized error/hint evolution;
- actual FastMCP schema tests remain green.

---

# P26 — Documentation/acceptance closure

Before v0.7 accepted:

- bootstrap policy example/documentation exact;
- policy schema/revision evidence;
- Admin OpenAPI reviewed;
- quota/accounting race evidence;
- admin self-lockout test evidence;
- audit redaction evidence;
- fairness/load evidence;
- current/version status updated factually;
- all required gates green.

---

# Forbidden shortcuts

Do not:

- store dynamic policy only in Redis;
- put secrets/endpoints in policy JSON;
- put `admin` in dynamic TaskCapabilityCode;
- use Redis counter as durable quota/accounting source;
- decrement quota without resource-state guard;
- charge cross-owner quota by deduplicated physical bytes;
- refund possibly billed call automatically after unknown response;
- let dynamic policy exceed static hard ceiling;
- expose admin as MCP tools;
- make admin update require dynamic `admin` flag;
- create generic maintenance command;
- overwrite revision history during rollback.

---

# Final acceptance

v0.7 completes only after Definition of Done from README and exact policy/admin contract, policy/quota/audit/HA/fairness/recovery gates all pass.
