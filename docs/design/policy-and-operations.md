# Policy and operations design

## Статус документа

Канонический владелец cross-cutting **dynamic task policy, quotas/budgets, operator controls, durable admin audit и operational policy revisions** Web Access.

Точные models/endpoints:

- `contracts/policy-models.md`;
- `contracts/admin-api-v1.md`.

Связанные решения:

- ADR-0019 — revisioned policy registry;
- ADR-0020 — durable quota/billable accounting;
- ADR-0023 — admin control plane authority outside mutable task policy.

---

# 1. Purpose

Production Web Access должен позволять оператору без redeploy:

- ограничивать task capabilities;
- задавать per-principal quotas;
- управлять provider admission/billable budgets;
- управлять Content retention defaults;
- наблюдать provider/worker/job/storage state;
- draining workers;
- запускать только typed bounded maintenance;
- сохранять durable security/operator audit.

При этом policy и accounting должны оставаться согласованными между replicas и переживать Redis loss/restarts.

---

# 2. Static configuration vs dynamic policy

## Static/deployment configuration

Содержит:

- PostgreSQL/Redis/S3/provider endpoints;
- secrets/credentials;
- TLS/service identity;
- internal network addresses;
- software hard ceilings;
- binary/image/runtime paths;
- admin control-plane enable/network boundary;
- break-glass credential/recovery configuration.

Обычно требует rollout/restart.

## Dynamic non-secret task policy

Содержит typed:

- enabled task capabilities;
- Search provider/default/cache/budget policy;
- Search/Retrieval rate/concurrency defaults/maxima;
- Content logical quotas/retention defaults;
- Browser quotas/TTL defaults;
- Job quotas/fairness/backlog limits;
- per-principal overrides;
- Browser mutation audit mode.

Dynamic policy никогда не содержит secrets и не управляет собственным admin authorization.

---

# 3. Hard ceilings

Каждый safety-sensitive limit имеет hierarchy:

```text
software/deployment hard ceiling
≥ global dynamic maximum
≥ principal effective override/default
```

Admin mutation не может поднять значение выше hard ceiling текущей software/runtime revision.

---

# 4. Revisioned PolicySnapshot

PostgreSQL — authoritative source.

Любая policy mutation:

```text
expected current revision
→ validate typed change
→ materialize complete immutable logical state
→ insert revision N+1
→ CAS current pointer
→ required AuditEvent
→ commit
```

Rollback создаёт новую monotonic revision; старый revision number не становится current повторно.

Control Plane caches immutable snapshot and periodically checks current revision.

Redis invalidation может ускорять refresh, но не является correctness source.

---

# 5. Global policy + exact-principal overrides

Logical policy состоит из:

```text
GlobalPolicyDocument
+
0..N exact PrincipalPolicyOverride
```

No regex/expression/group policy language v1.

Public Admin REST не пересылает все overrides при каждом update:

- global defaults/maxima update отдельно;
- exact principal override CRUD отдельно;
- каждая mutation всё равно bumps top-level policy revision.

Baseline explicit override ceiling — 10,000 exceptions per logical policy state; principals without override use global defaults and не входят в этот count.

---

# 6. Task capability policy

Dynamic task capabilities v1:

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
∩ global enabled task capabilities
∩ principal override restrictions
∩ resource ownership/policy
```

Policy restricts; it cannot mint missing scope.

---

# 7. Admin control plane

Согласно ADR-0023, `admin` **не** является dynamic task capability.

Admin REST требует:

```text
trusted AuthProvider admin:read/admin:write
+
deployment/network policy
```

Dynamic task policy не может отключить policy read/update/rollback для уже authorized admin principal.

Если deployment хочет выключить admin HTTP surface целиком, это static deployment/network configuration с отдельным recovery path.

Так исключается self-lockout.

---

# 8. Policy staleness

Initial target:

```text
normal revision refresh <= 5 seconds
high-risk stale grace <= 30 seconds
```

Если replica не может обновить явно более новый current policy:

- сохраняет last-known-good кратковременно;
- health becomes degraded;
- после grace high-risk **task admissions** fail closed по class.

Admin control-plane recovery/read path не должен зависеть от dynamic task capability flag; DB/auth/network failures остаются реальными blockers.

---

# 9. Quota classes

Разные quota semantics не объединяются одним счетчиком:

```text
rate
concurrent request-bound execution
durable resource count
logical retained bytes/objects
billable provider units
Job global backlog/fairness
```

Redis flow limiters подходят rate/concurrency.

Durable resources/budgets учитываются в PostgreSQL transactionally.

---

# 10. Durable principal usage

Materialized `PrincipalUsage` может содержать:

```text
active_browser_sessions
nonterminal_jobs
active_job_attempts
retained_content_bytes
retained_content_objects
usage_revision
```

Counters — acceleration/materialization, не единственный source of truth.

UsageReconciler сверяет их с authoritative resources.

Admission + resource state update/counter reservation выполняются transactionally enough to prevent oversubscription across replicas.

---

# 11. Browser quotas

Browser create requires одновременно:

```text
auth/task policy
→ principal durable session quota
→ Browser create rate
→ global/worker physical capacity
```

Principal slot reserved durably before/with logical resource admission and released exactly once on terminal lifecycle (`failed/closed/lost/expired`).

Worker capacity is a separate physical limit.

---

# 12. Job quotas/fairness

Enforce:

- non-terminal Jobs/principal;
- active JobAttempts/principal;
- registered job-type/global attempt caps;
- create rate;
- global backlog admission.

Queue order alone cannot let one principal monopolize worker execution indefinitely.

If active-attempt quota unavailable, DB claim defers execution through durable retry/wake-up semantics rather than busy-looping.

---

# 13. Content logical quota

Quota charges logical owner-visible available ContentObjects, not physical deduplicated blob bytes.

Before final `creating → available` where quota applies:

```text
lock/check PrincipalUsage
→ Content availability transition
→ usage increment
→ same transaction where feasible
```

Expiry/delete releases exactly once.

Different owners referencing same physical hash still have independent logical quota.

---

# 14. Billable provider accounting

Billable Search providers use durable provider units, not hardcoded currency.

Flow around actual paid upstream attempt:

```text
cache miss
→ task policy/rate/capacity
→ durable budget reservation by usage_attempt_id
→ upstream send
→ finalize consumed/released according send evidence
```

If request may have been sent/billed but outcome is unknown, baseline is conservative consumption, not automatic refund.

Retry gets separate reservation.

Period boundaries UTC.

---

# 15. Retention policy

v1 dynamic Content policy includes bounded defaults for at least:

```text
transient
job_result
```

No per-principal arbitrary infinite TTL.

Principal overrides adjust logical storage quota but not introduce arbitrary retention classes in baseline.

Physical storage lifecycle remains Content design responsibility.

---

# 16. Admin REST responsibilities

Exact surface: `contracts/admin-api-v1.md`.

Categories:

```text
current global policy
principal overrides
policy revision history/rollback
provider status/budget summary
principal usage
Browser/Job worker status + generation-safe drain
Job/outbox backlog
AuditEvent read
bounded typed maintenance
protected status
```

No admin MCP tools.

No SQL/Redis/shell/raw provider secret console.

---

# 17. Typed maintenance

Only explicit actions are allowed, e.g.:

- Content reconciliation/GC bounded pass;
- Job/outbox reconciliation;
- Usage reconciliation;
- provider status refresh;
- eligible Job recovery through state machine;
- worker drain.

Every mutation has exact input bounds, admin auth and required audit where specified.

No generic command string.

---

# 18. Durable AuditEvent

Minimum trusted metadata:

```text
audit_id
timestamp
actor_principal_id
delegated_subject | null
action_code
resource refs / policy revision
outcome
operation/request correlation
bounded redacted metadata
```

Never persist:

- bearer/API secrets;
- full page/document content;
- password/form values;
- arbitrary giant request bodies.

Application audit semantics are append-only.

Required admin mutation + audit append commit atomically; audit failure aborts mutation.

---

# 19. Policy compatibility

Policy snapshot includes `schema_version`.

Software declares readable range.

New policy schema cannot become current before active deployment compatibility allows it.

Incompatible replica degrades/fails relevant capabilities rather than ignoring unknown security fields.

Exact v1 models: `contracts/policy-models.md`.

---

# 20. Worker policy propagation

Browser/Job Workers do not need independent arbitrary policy DB reads.

Control Plane sends bounded approved execution profile/limits with internal request/job creation.

Worker also enforces its own static hard safety ceilings and rejects impossible values.

This prevents dynamic policy from disabling worker safety boundary.

---

# 21. Failure semantics

PostgreSQL unavailable:

- no new durable policy revision/resource quota reservation/billable reservation;
- do not trust stale Redis counters as replacement.

Redis unavailable:

- policy source remains PostgreSQL;
- invalidation recovered by polling;
- rate/concurrency class follows explicit fail-open/fail-closed setting in implementation, with security/cost critical paths conservative.

Audit append failure on required mutation:

```text
rollback mutation
```

---

# 22. Observability

Track bounded:

- policy current revision/age/refresh failures;
- task capability/quota rejects by code;
- usage drift reconciliation;
- provider billable units/reservations;
- Browser/Job quota utilization;
- admin mutation outcomes;
- audit append failures;
- worker drain duration;
- retention/GC maintenance.

No principal IDs as unbounded metric labels.

---

# 23. Testing requirements

At minimum:

- concurrent policy CAS updates;
- exact-principal override update/delete;
- lost Redis invalidation + polling recovery;
- policy schema rolling compatibility;
- dynamic policy cannot contain/disable `admin` control-plane capability;
- admin auth/network boundary;
- Browser/Job/Content durable quota races;
- UsageReconciler drift repair;
- billable reservation double-spend/unknown outcome;
- policy lowering below consumed usage;
- audit transaction rollback;
- generation-safe worker drain;
- hot-principal Job fairness;
- maintenance input bounds;
- no secrets in policy/audit/diagnostics.

---

# 24. Non-goals

v1 policy/operations design does not introduce:

- user account product;
- OAuth/OIDC implementation;
- arbitrary RBAC/expression engine;
- billing/invoice system;
- secret manager UI;
- generic scheduler/workflow engine;
- arbitrary runtime code/config hot reload;
- MCP operator console;
- dynamic self-disable of admin recovery control plane.
