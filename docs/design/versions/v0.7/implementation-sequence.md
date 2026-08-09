# v0.7 — Implementation sequence

## Назначение

Порядок реализации policy/operator hardening поверх уже работающих capabilities.

Ключевой принцип:

> Сначала durable policy/quota/audit foundation и multi-replica correctness. Только затем admin REST и operational controls.

---

# Patch P0 — Preconditions

- v0.1–v0.6 applicable gates green;
- multi-replica test profile available;
- Redis/PostgreSQL failure injection available;
- existing hard ceilings inventoried into one typed registry/settings layer;
- no admin MCP tools exist baseline.

---

# Patch P1 — Policy typed models

Implement typed immutable:

```text
PolicySnapshot
EffectivePolicy
CapabilityPolicy
PrincipalPolicy
SearchPolicy
RetrievalPolicy
ContentPolicy
BrowserPolicy
JobsPolicy
RetentionPolicy
```

Rules:

- no secrets;
- unknown fields forbidden;
- all soft limits <= static hard ceilings;
- policy cannot grant absent auth scopes.

Unit schema/invariant tests.

---

# Patch P2 — Policy persistence/revisions

Migration:

```text
policy_revisions
current_policy
```

Implement ADR-0019:

- complete immutable snapshot per revision;
- current pointer CAS;
- expected revision conflict;
- schema version;
- bootstrap policy;
- rollback-as-new-revision.

No REST yet.

---

# Patch P3 — Policy cache/refresh

Control Plane:

- startup load;
- immutable atomic swap;
- <=5s revision polling baseline;
- jitter;
- optional Redis invalidation optimization;
- last-known-good;
- high-risk stale grace/fail-closed.

Multi-replica tests with lost invalidation and DB outage.

---

# Patch P4 — Audit foundation

Migration `audit_events`.

Append-only application repository/service.

Required fields/redaction.

Add transactional helper that ensures required admin mutations + audit commit atomically.

No page/content secret payload.

---

# Patch P5 — PrincipalUsage/quota schema

Migration:

```text
principal_usage
provider_usage_periods
provider_usage_reservations/events
```

Implement ADR-0020 repositories/CAS/lock ordering.

Concurrent DB race tests before integrating capabilities.

---

# Patch P6 — Browser durable quota integration

BrowserSession create/terminal lifecycle integrates `active_browser_sessions` transactionally.

Test:

- concurrent last slot;
- worker create failure;
- close/expire/lost;
- double terminal transition;
- UsageReconciler drift repair.

Worker capacity unchanged/separate.

---

# Patch P7 — Job quotas/fairness

Job create uses nonterminal Job quota.

Job claim uses active JobAttempt quota.

Test hot-principal backlog vs second principal.

Ensure quota deferral doesn't busy-loop queue; use durable/controlled next wake-up.

---

# Patch P8 — Content logical storage quota

Integrate before `creating → available` Content transition.

Charge logical size per owner.

Tests:

- concurrent Content finalize;
- same physical hash different owners;
- derived representation;
- reuse;
- expire/delete;
- quota reject cleans staged/final orphan through normal reconciler.

---

# Patch P9 — Provider billable budget

Integrate `BudgetPort` in billable Search provider path.

Implement:

- period usage row;
- idempotent reservation;
- send evidence/finalize;
- conservative unknown accounting;
- retry separate reservation;
- lowering policy below usage.

Cache hits do not reserve.

No currency pricing in provider adapter.

---

# Patch P10 — General rate/concurrency policy integration

Map existing Redis flow limiters to EffectivePolicy for:

- Search;
- Retrieval;
- Browser creation;
- request-bound concurrency.

Each class explicitly fail-open/fail-closed.

No duplicate limiter implementations per transport.

---

# Patch P11 — Retention policy migration

Move scattered configurable TTL defaults into typed retention policy while preserving current behavior.

Ensure resources record retention class/revision where necessary.

Cleanup/GC still uses component lifecycle contracts.

No client infinite-retention capability.

---

# Patch P12 — Admin policy REST

Add admin-only:

- get current policy/revision;
- validate/update typed policy;
- revision history;
- rollback.

Mutation + audit transaction.

Expected revision required for update.

OpenAPI/authorization tests.

---

# Patch P13 — Admin status/usage REST

Expose protected bounded diagnostics:

- capability readiness;
- provider status/budgets;
- usage summaries;
- worker state/capacity;
- Job/outbox backlog;
- Content storage/reconciliation status.

No credentials/internal raw connection strings.

---

# Patch P14 — Worker drain operations

Typed generation-safe drain for Browser and Job workers.

Audit mutation.

Tests stale generation, concurrent drain/restart, rolling deployment.

No arbitrary PID kill endpoint.

---

# Patch P15 — Typed maintenance operations

Implement only approved bounded actions:

- trigger reconciliation pass;
- content GC dry-run/bounded run;
- usage reconciliation;
- provider status refresh;
- eligible Job recovery/requeue through state machine.

Each action:

- admin scope;
- explicit input bounds;
- audit;
- no generic command string.

---

# Patch P16 — UsageReconciler

Recompute/repair:

- active Browser slots;
- non-terminal Jobs;
- active attempts;
- retained logical Content bytes.

Bounded batches/multi-replica safe.

Drift metric/audit warning.

Billable ledger excluded from generic resource recount.

---

# Patch P17 — Capability-aware health/readiness

Finalize machine-readable capability matrix.

Protected detail endpoint includes policy revision/staleness, queue/worker/provider/storage states.

Public liveness remains minimal.

Tests degraded-but-alive scenarios.

---

# Patch P18 — Rolling compatibility tests

Mixed old/new replicas/workers:

- policy schema overlap;
- handler revision compatibility;
- Browser worker revision;
- expand-first migrations;
- stale/incompatible policy readiness.

No policy schema switch before all active required replicas support it.

---

# Patch P19 — Security/audit review

Verify:

- no secrets in policy/audit;
- policy cannot mint scope;
- admin endpoints network/auth protected;
- audit required mutation rollback on append failure;
- no unbounded principal identifiers in metrics;
- usage reports owner/admin scoped.

---

# Patch P20 — Load/fairness/HA roast

- multi-replica quota races;
- hot principal;
- policy update storm;
- Redis restart;
- DB failover/transient errors;
- usage row contention;
- billable reservation contention;
- S3 shared profile;
- worker rolling drains;
- retention/GC concurrency.

Measure hot usage-row contention before considering sharded counters.

---

# Patch P21 — Facade compatibility

REST/OpenAPI audit for new admin surface.

MCP existing tools only gain normalized policy/quota errors; no admin tools.

Actual FastMCP schema snapshot should remain stable except explicitly documented result error codes/hints.

---

# Patch P22 — Documentation/acceptance closure

- actual bootstrap policy documented;
- policy schema/revisions documented;
- admin OpenAPI reviewed;
- quota/accounting evidence recorded;
- audit examples/redaction tested;
- `current.md` updated;
- all v0.7 gates green.

---

# Forbidden shortcuts

Do not:

- store dynamic policy only in Redis;
- put provider/API secrets in policy JSON;
- use Redis counter as durable Browser/Job/storage quota source;
- decrement quota without resource state guard;
- charge physical deduplicated S3 bytes as cross-owner quota basis;
- refund paid usage automatically after unknown response;
- let admin policy exceed code hard ceiling;
- expose admin controls as MCP tools;
- create generic maintenance command shell;
- overwrite policy revision history during rollback.

---

# Final acceptance

v0.7 completes only after Definition of Done from README and policy/quota/audit/HA/fairness gates.
