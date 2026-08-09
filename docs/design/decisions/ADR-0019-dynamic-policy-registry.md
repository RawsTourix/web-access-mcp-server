# ADR-0019 — Dynamic operational policy: PostgreSQL source of truth + revisioned snapshots

**Статус:** accepted

## 1. Контекст

v0.7 требуется менять non-secret operational policy без rebuild/redeploy каждого replica:

- per-principal quotas;
- capability enable/disable;
- provider budgets/defaults;
- retention classes;
- worker/provider operational controls.

При этом нельзя:

- хранить secrets в policy DB;
- считать Redis Pub/Sub source of truth;
- давать replicas бесконечно использовать stale security policy;
- позволять blind last-write-wins admin updates;
- связывать application core с конкретным configuration backend.

---

## 2. Решение

Dynamic non-secret policy хранится в PostgreSQL как **versioned immutable revisions/snapshots**.

Conceptually:

```text
PolicyRevision
├── revision
├── schema_version
├── created_at
├── actor/audit coordinates
└── policy document/normalized rows
```

Current revision определяется durable pointer/current flag/CAS-protected row.

Control Plane читает immutable `PolicySnapshot` и кэширует его in-process.

---

## 3. Почему immutable revision

Mutation-in-place усложняет:

- audit;
- rollback;
- rolling replicas;
- operation provenance;
- optimistic concurrency.

Immutable revisions позволяют Operation записать:

```text
policy_revision = N
```

и понимать, под какой policy было принято решение.

---

## 4. Storage model

Implementation может использовать:

### Option A

```text
policy_revisions JSONB normalized document
+
current_policy pointer row
```

### Option B

normalized policy tables + top-level revision.

Baseline предпочтение v0.7:

```text
versioned JSONB policy snapshot
+
strict Pydantic schema
+
current revision pointer
```

потому что policy structure ограничена, typed и меняется чаще schema-wise, чем resource relational data.

Не использовать arbitrary untyped dict внутри application после load: snapshot валидируется в typed models.

---

## 5. Admin update

Admin request:

```text
expected_revision
new typed policy / patch
```

Flow:

1. authenticate `admin`;
2. load current;
3. validate expected revision;
4. apply typed patch to immutable model;
5. validate all hard ceilings/cross-field constraints;
6. INSERT new revision;
7. update current pointer CAS;
8. append required AuditEvent in same transaction;
9. commit.

Revision conflict → structured `policy_revision_conflict`.

---

## 6. Full replacement vs patch

REST may expose JSON Merge Patch-like or typed patch endpoints internally, but persistence always materializes **complete validated snapshot** per revision.

Это упрощает read/effective policy computation и rollback.

Client не хранит chain patches как source of truth.

---

## 7. Snapshot composition

Typed snapshot sections conceptually:

```text
capabilities
principal defaults/overrides
search/provider policies
retrieval policies
content/retention policies
browser quotas
jobs quotas/fairness
operational maintenance policy
```

Secrets/endpoints absent.

Hard safety ceilings from static `Settings` are applied during validation and are not copied as editable values.

---

## 8. Principal overrides

Policy supports:

```text
defaults
+
exact principal_id overrides
```

No arbitrary regex/expression policy language baseline.

Reason:

- deterministic;
- easy audit;
- no embedded policy scripting engine.

Future groups/roles may be added only with explicit identity design.

---

## 9. Effective policy

Operation starts:

```text
PrincipalContext
+
current PolicySnapshot
→ EffectivePolicy
```

Rules:

- auth scopes remain maximum permission;
- policy can restrict, not mint missing auth scopes;
- owner/resource checks remain separate;
- operation stores revision in context/provenance where relevant.

---

## 10. Replica refresh

Each Control Plane replica:

- loads current snapshot startup;
- periodically checks lightweight current revision;
- if changed, loads/validates new snapshot then atomically swaps immutable in-memory reference.

Initial target:

```text
revision poll interval <= 5 s
```

with jitter to avoid thundering herd.

Exact interval configurable inside staleness ceiling.

---

## 11. Redis invalidation

Optional Redis Pub/Sub/message can notify replicas:

```text
policy revision N available
```

Replica still reads authoritative PostgreSQL revision/content.

Lost Pub/Sub notification harmless because periodic poll recovers.

No policy body trusted from Pub/Sub message.

---

## 12. Last-known-good

If refresh of newer policy fails validation/read:

- replica keeps previous valid snapshot temporarily;
- emits degraded health/security alert;
- after policy-staleness grace high-risk new operations fail closed according policy class;
- replica never silently treats invalid newer policy as valid current.

Admin API reports incompatible revision.

---

## 13. Staleness grace

Initial operational target:

```text
normal refresh <= 5 s
max accepted stale age for high-risk admission = 30 s
```

Configurable stricter.

Examples high-risk:

- Browser create/interact after capability revoke;
- billable provider request after budget disable;
- new Job creation;
- admin mutation.

Long-running already admitted operation follows component cancellation/revocation semantics; not every policy update kills work instantly.

---

## 14. Rollback

Operator rollback creates a **new revision** whose content equals selected old policy (possibly after compatibility validation).

Current pointer moves forward to new revision number.

History remains append-only.

Не «делать старую revision снова current» без нового audit event.

---

## 15. Schema versioning

Policy snapshot has `schema_version`.

Software declares readable range.

Rolling deploy rule:

- new policy schema may become current only when active deployment software compatibility policy permits;
- incompatible replica marks readiness/capability failed rather than ignoring fields.

Schema migration utility can materialize new revision from old.

---

## 16. Cache and derived policy

Replica may precompute EffectivePolicy helpers/caches per principal, but invalidates by top-level revision.

Do not retain old principal effective policy after current revision change.

Bound cache size/cardinality.

---

## 17. Worker policy

Browser/Job Workers do not independently query arbitrary dynamic policy DB baseline unless their capability needs it.

Control Plane passes server-approved bounded execution limits/profile to internal request/job creation.

Worker retains hard local limits and refuses values above its runtime safety ceiling.

This prevents stale/compromised Control Plane request from disabling worker hard safety.

---

## 18. Secrets boundary

Policy API rejects known secret-bearing fields.

Provider credentials, DB DSN, bearer tokens, S3 secrets, internal worker credentials stay deployment/secret configuration.

Audit policy snapshots may be inspected/exported safely without secret redaction complexity beyond principal IDs/operational metadata.

---

## 19. Audit

Policy revision creation and rollback requires AuditEvent in same DB transaction.

Audit includes:

- actor;
- old/new revision;
- changed top-level sections/codes;
- outcome;
- operation/request ID.

Full snapshot may be queryable separately; audit row need not duplicate it.

---

## 20. Admin REST

Baseline endpoints conceptually:

```text
GET  /api/v1/admin/policy
PUT/PATCH /api/v1/admin/policy
GET  /api/v1/admin/policy/revisions
POST /api/v1/admin/policy/rollback
```

Exact path/method can be refined in v0.7 implementation while preserving typed revision semantics.

No MCP tools.

---

## 21. Tests

1. concurrent admin updates same expected revision → one succeeds;
2. hard ceiling violation rejected;
3. audit + revision atomic;
4. replica refresh after change;
5. lost Redis notification still refreshes by polling;
6. malformed current revision causes degraded/fail-safe behavior;
7. stale grace for high-risk action;
8. rollback produces new monotonic revision;
9. rolling compatible schema;
10. incompatible software revision fails readiness/capability;
11. secrets cannot be stored in dynamic policy schema;
12. effective auth scopes cannot be expanded by policy.

---

## 22. Consequences

Плюсы:

- dynamic operations without restart;
- deterministic revision/audit;
- no Redis correctness dependency;
- bounded staleness;
- rolling deploy compatibility;
- simple exact-principal overrides.

Минусы:

- extra DB reads/poll loop;
- policy schema/version maintenance;
- admin update complexity;
- replicas may briefly use previous revision within bounded window.

---

## 23. Не определяется

- UI for policy editing;
- user-created groups/roles;
- OPA/Cedar/external policy engine;
- secret manager integration;
- arbitrary expression language;
- exact JSON patch standard.
