# Policy and operations design

## Статус документа

Канонический владелец cross-cutting **runtime policy, quotas/budgets, operator/admin controls, durable security audit и operational configuration revision** Web Access MCP.

Документ дополняет:

- `security.md` — trust/security boundaries;
- `deployment.md` — process/infrastructure topology;
- `observability.md` — telemetry/health;
- component docs — domain-specific limits.

---

# 1. Purpose

Web Access должен быть управляемым как production multi-principal service без изменения кода для каждого operational лимита.

Нужно централизованно ответить:

- какие capabilities разрешены principal-у;
- сколько ресурсов он может занимать;
- какие provider/billable budgets действуют;
- какие retention policies используются;
- как operator безопасно меняет эти policies;
- как replicas видят одну revision;
- какие security-sensitive changes сохраняются durable audit trail.

---

# 2. Static configuration vs dynamic policy

Разделение обязательно.

## Static/deployment configuration

Через env/secrets/files/orchestrator:

- PostgreSQL/Redis endpoints;
- service credentials/secrets;
- S3 credentials/endpoints;
- Yandex API secret;
- TLS/service identity;
- hard safety ceilings;
- feature build/runtime availability;
- internal network addresses;
- parser/browser binary paths.

Обычно требует restart/rollout.

## Dynamic non-secret policy

Может храниться durable и изменяться operator-ом:

- capability allow/deny;
- per-principal rate/concurrency quotas;
- BrowserSession/resource quotas;
- Job admission/active limits;
- Search provider allowance/default/billable units budget;
- Content retention class/default;
- soft operational limits внутри hard ceiling;
- worker/provider enable/drain policy;
- maintenance/cleanup policy;
- shared cache policy;
- audit verbosity class.

Dynamic policy никогда не содержит raw secrets.

---

# 3. Hard ceiling vs policy limit

Каждая configurable safety-sensitive величина имеет два уровня:

```text
hard server ceiling
≥
operator policy limit
≥
per-principal effective limit
```

Admin API не может поднять значение выше hard ceiling текущей software revision.

Hard ceilings изменяются code/config release review, а не runtime user request.

---

# 4. PolicySnapshot

Application operations получают immutable effective `PolicySnapshot`/context.

Conceptually:

```text
policy_revision
global policy
principal policy
capability-specific limits
provider/retention settings
loaded_at
```

Одна Operation использует согласованный snapshot; policy не меняется посередине execution произвольно.

Long-running Job сохраняет relevant policy/revision at creation/attempt, но security revocation/cancellation may still override according explicit rule.

---

# 5. Capability policy

Baseline capability classes:

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

Auth scope является верхней границей.

Dynamic policy может дополнительно запретить capability, но не выдать scope, которого нет у authenticated PrincipalContext.

Effective permission:

```text
authenticated scopes
∩
operator policy
∩
resource ownership/policy
```

---

# 6. Quota categories

Quotas разделяются по semantics.

## Rate

Operations/time window or token-bucket units.

## Concurrent

Одновременно выполняемые operations/resources.

## Durable resource count

- active BrowserSessions;
- pending/non-terminal Jobs;
- retained ContentObjects where policy tracks count.

## Byte/storage

- Content bytes retained;
- per Job aggregate bytes;
- Browser temp/artifact bytes.

## Billable/provider units

- upstream billable calls/units;
- daily/monthly/custom period budgets.

Не сводить всё к одному `requests_per_minute`.

---

# 7. Rate/concurrency enforcement

Ephemeral distributed rate/concurrency limits используют Redis-backed primitives where already established.

Examples:

- Search provider token bucket;
- per-principal Retrieval rate;
- Browser create rate;
- concurrent request-bound operations.

Failure mode `fail_open/fail_closed` задаётся capability policy. Cost/security critical enforcement baseline fail-closed.

---

# 8. Durable resource quota

Для durable resources correctness не должна зависеть только от Redis counter.

PostgreSQL authoritative resource rows + transactional usage/reservation mechanism используются для:

- active BrowserSession count;
- non-terminal Job count;
- retained storage accounting where enforced.

Derived usage counters may accelerate admission but имеют reconciliation against source resources.

---

# 9. PrincipalUsage

v0.7 может использовать durable aggregate rows:

```text
principal_id
usage_revision
active_browser_sessions
nonterminal_jobs
retained_content_bytes
billable_units_by_period or separate ledger summary
updated_at
```

Counters являются operational materialization, а не единственным source of truth.

Reconciler периодически сверяет их с authoritative resource/usage records.

Admission updates counter/resource in one transaction where possible.

---

# 10. Billable usage ledger

Для billable providers не хардкодить валютную цену в Search adapter.

Durable event/ledger records:

```text
principal_id
provider_id
provider/account revision
operation_id
usage_unit_type
units
attempt/retry metadata
timestamp
```

Policies могут ограничивать:

- calls/day;
- billable units/period;
- custom provider units.

Конвертация units → money может быть operator/reporting concern с отдельной pricing configuration, не correctness search path.

---

# 11. Budget reservation

Если provider billing unit начисляется при фактическом upstream attempt, budget must be checked/reserved immediately before upstream admission.

Flow:

```text
cache miss
→ rate/capacity
→ billable budget reservation
→ upstream attempt
→ usage finalize/account
```

Exact provider semantics may change order with rate reservation, but double-spend across replicas must be prevented by atomic DB/Redis policy appropriate to durable budget.

Budget reservation has idempotent operation/attempt identity.

---

# 12. Browser quota

At BrowserSession create:

- auth scope/policy;
- principal active-session quota;
- global deployment/worker capacity;
- Browser create rate.

Successful durable create reserves principal active resource slot transactionally enough to avoid oversubscription under concurrent API replicas.

Terminal/failed/expired/closed releases slot through lifecycle transaction/reconciler.

Worker capacity remains independent second limit.

---

# 13. Job quota/fairness

Job admission limits:

- pending/non-terminal Jobs/principal;
- items/job;
- bytes/job;
- global backlog;
- job type allowance.

Job execution fairness baseline:

- max active JobAttempts/principal;
- max active JobAttempts/job type;
- worker global capacity.

Queue order alone must not allow one principal to occupy all execution indefinitely.

If arq message arrives for principal over active execution quota, DB claim is deferred/rejected-to-retry without executing body; durable Job state remains queued/retry eligible.

Load tests verify no pathological hot-principal starvation.

---

# 14. Content retention classes

Retention becomes explicit policy concept.

Example semantic classes:

```text
transient
job_result
saved
system/audit (only where applicable)
```

Exact defaults operator-configurable inside hard ceilings/minimum obligations.

A client cannot arbitrarily request infinite retention without permission/policy.

Content representation children do not automatically outlive owner/source policy without explicit relation rule.

---

# 15. Operator/Admin REST

Admin surface is REST-only baseline.

MCP does not expose operator tools to ordinary LLM.

Protected by `admin` scope + deployment/network policy.

Categories:

```text
status/health detail
policy inspect/update
provider enable/status/budget
worker status/drain
Job/outbox/reconciler status
retention/cleanup status
usage/accounting reports
safe maintenance actions
```

No generic SQL/Redis/shell endpoint.

---

# 16. Dynamic policy update

Operator update uses typed validated request.

Canonical transaction:

```text
load current revision
→ validate against software hard ceilings/schema
→ optimistic expected revision check
→ write new policy revision/snapshot
→ append durable audit event
→ commit
```

Response returns new revision.

No last-write-wins blind overwrite without revision conflict handling.

---

# 17. Policy distribution

PostgreSQL is authoritative for dynamic policy.

Control Plane replicas maintain immutable cached latest snapshots.

Refresh strategy:

```text
bounded periodic revision check
+
optional Redis Pub/Sub/invalidation acceleration
```

Redis invalidation is optimization, not correctness source.

Replica eventually detects revision even if Pub/Sub message lost.

---

# 18. Policy staleness bound

Security/limit policy has explicit max staleness target.

Initial design target:

```text
normal replica refresh <= 5 seconds
```

Sensitive operator action can force direct revision check/refresh path where necessary.

Readiness/degraded state exposes replicas that cannot refresh policy beyond configured grace.

Last-known-good may continue only according policy class; revoked/high-risk capabilities can fail closed after staleness grace.

---

# 19. Policy compatibility

Policy row/snapshot includes:

```text
schema_version
minimum/compatible software revision where needed
revision
```

Software that cannot understand current policy revision/schema fails capability/readiness safely rather than ignoring unknown security fields.

Rolling deploy design must support overlap compatible revisions.

---

# 20. Provider operation policy

Operator can:

- enable/disable provider;
- set default provider;
- set non-secret rate/capacity/budget limits;
- choose shared/principal cache policy;
- inspect health/usage.

Credentials/endpoints remain secret/deployment config unless separately designed secure secret manager integration.

Disabling provider does not automatically switch requests to another provider unless caller/default policy explicitly selects it in a future operation.

---

# 21. Worker drain operator action

Admin may request Browser/Job Worker drain by stable worker identity/generation.

Action:

- authenticated admin;
- generation checked;
- durable/ephemeral operator intent according runtime;
- worker advertises/enters draining;
- no new work;
- existing work follows component drain contract.

No kill arbitrary PID endpoint.

---

# 22. Maintenance actions

Allowed typed examples:

- trigger bounded reconciliation pass;
- trigger content GC dry-run/controlled batch;
- requeue eligible stuck Job through durable state transition;
- refresh provider capabilities;
- drain worker.

Each has explicit scope, limits, audit.

No generic `execute maintenance command` string.

---

# 23. Durable audit

Security/operator audit differs from telemetry/logs.

Audit event minimum:

```text
audit_id
timestamp
actor principal
optional delegated subject
action code
resource refs / policy revision
outcome
request/operation correlation
bounded structured metadata
```

Audit records never contain:

- raw bearer/API secrets;
- full page/document content;
- form password values;
- arbitrary giant request bodies.

---

# 24. What is audited

Baseline durable audit:

- admin policy changes;
- provider enable/disable/budget changes;
- worker drain/maintenance actions;
- security-sensitive retention/delete/save operations when added;
- repeated auth/authorization security events only if policy requires durable record (high-volume failures may remain telemetry/security pipeline rather than DB flood);
- potentially external-side-effect Browser actions at **metadata code/outcome level** when policy enables audit, without page text/target secrets.

Not every read-only Search/Content read becomes durable audit row.

---

# 25. Audit immutability/retention

Application has append-only semantics: ordinary API cannot update/delete individual audit event.

Database administrator still has infrastructure authority; append-only is application contract, not cryptographic WORM guarantee.

Audit retention/operator export policy explicit and may differ from normal Content/Job retention.

---

# 26. Quota errors/hints

Normalized errors distinguish:

```text
rate_limited
concurrency_limit
resource_quota_exceeded
storage_quota_exceeded
billable_budget_exceeded
job_backlog_limit
capability_disabled_by_policy
```

Retry-after only when system can calculate meaningful value.

No hidden fallback.

---

# 27. Observability

Metrics:

- policy revision age/refresh failures;
- quota rejects by bounded capability/code;
- usage counts;
- provider billable units;
- active Browser/Job quota utilization;
- admin action outcomes;
- reconciler drift corrections;
- audit append failures.

Principal IDs not unbounded metric labels.

---

# 28. Failure semantics

PostgreSQL unavailable:

- dynamic policy/owner/durable quota operations fail according component dependency;
- do not use stale mutable counters to create durable resource.

Redis unavailable:

- durable policy registry still exists;
- ephemeral rate/concurrency policies fail according explicit class;
- invalidation message loss handled by polling.

Audit append failure during required admin mutation:

```text
admin mutation transaction fails/rolls back
```

for actions where audit is transactional requirement.

---

# 29. MCP relationship

Ordinary MCP facade can return quota/policy errors and hints.

MCP does not get:

- admin policy update tools;
- provider credential controls;
- worker drain;
- audit browsing;
- raw quota registry.

This avoids mixing operator control with LLM task execution.

---

# 30. Testing requirements

- concurrent resource quota admission across API replicas;
- counter drift/reconciliation;
- rate/concurrency Redis failures;
- billable budget race/double reservation;
- policy optimistic conflict;
- lost Redis invalidation + polling refresh;
- rolling mixed software/policy revisions;
- admin authorization;
- audit transactional coupling;
- hot principal Job fairness;
- Browser session quota cleanup on worker loss;
- retention/GC race;
- no sensitive audit/log fields.

---

# 31. Non-goals

Этот design не вводит:

- user account product;
- OAuth/OIDC provider implementation;
- secret manager UI;
- billing/invoicing system;
- generic scheduler;
- general workflow engine;
- arbitrary runtime code/config hot reload;
- MCP operator console.
