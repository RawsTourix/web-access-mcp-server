# v0.7 — Distributed Operations & Policy Hardening

## Статус

`ready for implementation`

v0.7 не добавляет новую web capability. Она делает уже реализованные Search/Retrieval/Content/Browser/Jobs управляемыми и предсказуемыми в multi-replica/multi-principal production deployment.

---

# 1. Цель

После v0.7 operator должен уметь безопасно:

- менять non-secret runtime policies без redeploy;
- ограничивать principal capabilities/quotas;
- ограничивать billable provider usage;
- управлять retention;
- наблюдать provider/worker/queue/resource state;
- draining workers;
- запускать строго typed maintenance actions;
- получать durable security/operator audit;

при этом replicas должны использовать совместимые revisioned policy snapshots и не расходиться по durable quota/accounting state.

---

# 2. Prerequisites

- v0.1–v0.6;
- `../../policy-and-operations.md`;
- `../../security.md`;
- `../../observability.md`;
- `../../deployment.md`;
- `../../persistence.md`;
- `../../search.md`;
- `../../browser.md`;
- `../../jobs.md`;
- ADR-0019 dynamic policy registry;
- ADR-0020 durable quota/accounting.

---

# 3. Explicit non-goals

- end-user account product;
- password/email authentication;
- OAuth/OIDC provider implementation;
- general RBAC/group expression engine;
- billing/invoice system;
- secret-management UI;
- MCP admin tools;
- arbitrary SQL/Redis/shell maintenance;
- scheduler/workflow engine;
- architecture rewrite to distributed — distributed assumptions already exist.

---

# 4. New durable tables

## Policy

```text
policy_revisions
current_policy
```

## Usage

```text
principal_usage
provider_usage_periods
provider_usage_reservations/events
```

## Audit

```text
audit_events
```

Exact schema follows ADR-0019/0020.

---

# 5. Bootstrap policy

On empty deployment, policy bootstrap is explicit.

Priority:

```text
validated bootstrap policy file/config
→ create revision 1
```

If absent, service may use a compiled conservative development/default snapshot only in allowed local/dev profile.

Production profile should require explicit accepted bootstrap policy rather than silently inheriting developer quotas.

Bootstrap policy contains no secrets.

---

# 6. Policy snapshot

Every Operation receives immutable effective policy with:

```text
policy_revision
capabilities
principal quotas
provider policy
retention policy
operational limits
```

Auth scopes remain maximum authority.

Policy can restrict; it cannot mint missing scope.

---

# 7. Policy refresh

Initial targets:

```text
revision poll <= 5 s
high-risk stale grace <= 30 s
```

Optional Redis invalidation accelerates refresh, but PostgreSQL revision check remains correctness path.

Replica with incompatible/too-stale high-risk policy becomes capability-degraded/fail-closed according policy class.

---

# 8. Policy update API

Admin-only typed revision update with optimistic concurrency:

```text
expected_revision
validated patch/new policy
```

Transaction:

```text
new immutable revision
+
current pointer CAS
+
AuditEvent
```

Rollback creates a new revision; history remains monotonic.

---

# 9. Initial capability policy classes

```text
search
retrieval
content.read
content.parse
browser.read
browser.interact
jobs.read
jobs.create
admin
```

Provider/job/parser-specific subpolicy may refine limits but does not create arbitrary permission language.

---

# 10. Principal durable quota accounting

`principal_usage` tracks transactionally materialized:

```text
active_browser_sessions
nonterminal_jobs
active_job_attempts
retained_content_bytes
```

Counters reconcile against authoritative resources.

No Redis reset can reset durable usage.

---

# 11. Browser principal quota

BrowserSession create reserves principal slot in DB transaction before worker create.

Slot released exactly once on terminal `failed/closed/lost/expired` transition.

Worker physical capacity remains separate.

Initial bootstrap/local policy may use a conservative value such as 2 active sessions/principal; production policy explicit.

---

# 12. Job principal quota/fairness

Enforce:

- non-terminal Jobs/principal;
- active JobAttempts/principal;
- per-job-type active limit;
- global backlog thresholds.

Queue order alone does not grant unlimited worker share.

If active execution quota reached, worker claim does not execute body and job remains eligible for bounded later wake-up.

---

# 13. Content logical storage quota

Charge logical `size_bytes` of owner’s available retained ContentObjects.

Physical S3/filesystem dedup does not affect owner quota.

Before `creating → available`:

```text
lock PrincipalUsage
→ quota check
→ Content available + usage increment same transaction
```

Expiry/delete releases exactly once.

---

# 14. Billable provider budgets

Search paid providers use durable unit budgets.

Baseline unit for Yandex-like search adapter can be:

```text
search_request = 1 billable unit per actual admitted upstream request
```

Policy limits units per UTC-normalized period.

No hardcoded ruble price inside provider adapter.

---

# 15. Billable reservation/finalization

Before paid upstream call:

```text
idempotent usage_attempt_id
→ transaction reserve units
→ upstream call
→ finalize consumed/released according send evidence
```

If request may have been sent/billed but response outcome unknown, baseline is conservative consumption rather than automatic refund.

Retry requires new budget reservation.

---

# 16. Retention policy

v0.7 formalizes at least:

```text
transient
job_result
```

and internal/system classes where necessary.

Existing v0.3 defaults become policy defaults rather than scattered constants.

No arbitrary infinite client retention baseline.

Retention/cleanup admin surface can inspect policy and trigger bounded maintenance, not delete arbitrary physical storage key.

---

# 17. Operator REST surface

REST-only, `admin` scope.

Conceptual groups:

```text
/api/v1/admin/status
/api/v1/admin/policy
/api/v1/admin/policy/revisions
/api/v1/admin/providers
/api/v1/admin/workers
/api/v1/admin/jobs
/api/v1/admin/storage
/api/v1/admin/usage
/api/v1/admin/audit
```

Exact resource-oriented paths finalized in implementation OpenAPI.

No generic command endpoint.

---

# 18. Provider controls

Admin can inspect:

- configured/enabled providers;
- readiness/degraded reason;
- rate/capacity policy;
- billable usage/budget summary;
- default provider.

Can change only non-secret policy.

Credentials/endpoints remain deployment config.

Provider disable does not trigger hidden fallback.

---

# 19. Worker controls

Admin can inspect Browser/Job workers:

- ID/generation;
- state;
- heartbeat/lease;
- capacity/utilization;
- runtime revision.

Typed action:

```text
drain worker(expected generation)
```

No arbitrary kill PID.

Drain delegates to existing Browser/Job lifecycle contracts.

---

# 20. Maintenance controls

Allowed typed operations can include:

- trigger bounded Content reconciliation/GC pass;
- trigger Job/outbox reconciliation pass;
- refresh provider capability/status;
- re-enable/requeue eligible durable Job through state-aware application operation;
- rebuild/reconcile principal usage counters;
- worker drain.

Every mutating operator action audited.

---

# 21. AuditEvent

Minimum durable fields:

```text
audit_id
timestamp
actor_principal_id
delegated_subject | null
action_code
resource refs/policy revision
outcome
operation_id/request correlation
bounded metadata
```

Append-only application semantics.

Never persist secrets/full page content/password form values.

---

# 22. Audit transactional coupling

For required admin mutation:

```text
mutation + AuditEvent
```

must commit in same PostgreSQL transaction.

Audit append failure aborts mutation.

Read-only high-volume operations remain telemetry, not necessarily durable audit.

---

# 23. Usage reconciliation

Periodic UsageReconciler verifies:

- active BrowserSessions;
- non-terminal Jobs;
- active JobAttempts;
- retained Content bytes.

Repair drift with CAS and expose metric/audit warning.

Billable usage ledger has separate reconciliation/evidence rules and is not recomputed from resource rows.

---

# 24. Redis flow limits

Existing Search rate/concurrency model generalizes where needed to:

- principal Retrieval rate;
- Browser create rate;
- request-bound concurrent operations.

Redis failures obey explicit fail-closed/open class.

Durable resources/budgets never rely only on these counters.

---

# 25. Fairness load gate

Load test must include at least:

```text
principal A creates sustained Job backlog
principal B submits small Jobs concurrently
```

and prove active-attempt quotas prevent A from permanently consuming all worker execution capacity under configured fair policy.

Exact scheduling fairness is bounded/admission-based, not guaranteed strict round-robin.

---

# 26. S3 production hardening

v0.7 production profile finalizes:

- workload/static secret credential mode chosen by deployment;
- TLS/CA;
- bucket lifecycle for incomplete multipart/staging as defense in depth;
- retention/GC metrics;
- shared replica tests;
- backup/replication expectations documented operationally.

Application S3 contract unchanged from v0.5.

---

# 27. Health/readiness finalization

Detailed status includes capability matrix, e.g.:

```text
search.searxng ready/degraded
search.yandex ready/disabled/budget_exhausted
retrieval ready
content filesystem/s3 ready/degraded
browser ready/no_workers/egress_unavailable
jobs ready/queue_unavailable/no_workers/backlog_limit
policy current/stale/incompatible
```

Public liveness remains simple and non-sensitive.

Detailed status protected.

---

# 28. Rolling compatibility

Every replica exposes runtime/schema revisions.

Rolling deployment tests cover:

- old/new policy schema compatible overlap;
- old/new Job Worker handler revisions;
- Browser worker runtime compatibility;
- database migrations expand-first where needed;
- no incompatible policy made current before rollout support.

---

# 29. MCP behavior

No admin MCP tools.

Existing tools gain normalized quota/policy errors/hints where applicable:

```text
capability_disabled_by_policy
rate_limited
resource_quota_exceeded
storage_quota_exceeded
billable_budget_exceeded
job_backlog_limit
```

Descriptions remain task-oriented, not operator documentation.

---

# 30. Observability

Add:

- policy revision age/refresh failures;
- quota utilization/rejects;
- usage reconciliation drift;
- billable units/reservation states;
- audit append failures;
- admin operation outcomes;
- worker drain durations;
- retention/GC activity;
- fairness/backlog signals.

No principal ID as unbounded metric label.

---

# 31. Required tests

- policy concurrent updates/conflicts;
- lost invalidation/poll recovery;
- stale high-risk policy fail-safe;
- rolling policy schema compatibility;
- Browser/Job/Content quota races;
- counter drift reconciliation;
- billable reservation double-spend race;
- response-loss billing accounting;
- policy lowering below consumed usage;
- admin auth;
- audit atomicity;
- worker drain generation safety;
- hot-principal fairness;
- S3 production-profile contract;
- retention/GC races;
- detailed readiness redaction.

---

# 32. Definition of Done

v0.7 complete only if:

1. Dynamic policy revision works across replicas within bounded staleness.
2. Policy cannot bypass auth scope/hard ceilings.
3. Durable quotas survive Redis loss.
4. Concurrent resource creation cannot oversubscribe principal quota.
5. Content dedup does not distort/logically leak storage quota.
6. Billable provider budget cannot double-spend through replica race.
7. Admin mutations are audited transactionally.
8. No operator MCP tools exist.
9. Worker drain/status is typed and generation-safe.
10. Health/readiness is capability-aware.
11. Fairness load gate passes.
12. Applicable production/HA release gates green.
