# ADR-0020 — Durable quota/accounting: PostgreSQL usage rows + reconciled resource counters + billable reservations

**Статус:** accepted

## 1. Контекст

v0.7 добавляет multi-principal quotas и billable budgets.

Redis token buckets/semaphores уже подходят для rate/concurrency, но недостаточны как authoritative accounting для:

- active BrowserSession slots;
- non-terminal Job slots;
- retained logical Content bytes;
- billable provider units/period.

Нужно корректно переживать:

- concurrent API replicas;
- process crash после resource create/terminal;
- Redis loss;
- double provider retry;
- resource reconciler;
- policy revision changes.

---

## 2. Решение — два класса enforcement

```text
Ephemeral flow limits
→ Redis/local primitives

Durable resource/budget accounting
→ PostgreSQL authoritative rows/ledger
```

Redis не является source of truth для durable usage.

---

## 3. PrincipalUsage row

Per principal durable aggregate:

```text
principal_id PK
revision
active_browser_sessions
nonterminal_jobs
active_job_attempts
retained_content_bytes
updated_at
```

Дополнительные bounded counters могут появляться versioned migration.

Row создаётся lazily/at principal bootstrap.

---

## 4. Counter semantics

Counters являются **transactional materialized usage**, но их correctness подтверждается authoritative resource rows.

Они нужны для cheap admission under lock, а не как единственный historical source.

Reconciler периодически пересчитывает/сверяет:

- BrowserSession non-terminal states;
- Job non-terminal states/active attempts;
- owner available retained ContentObjects.

Drift исправляется transactionally и audit/metric visible.

---

## 5. BrowserSession quota transaction

Create admission transaction:

1. lock `PrincipalUsage` row;
2. load EffectivePolicy Browser active quota;
3. check `active_browser_sessions + 1 <= limit`;
4. insert BrowserSession `creating`;
5. increment usage counter;
6. commit.

Если later create fails terminal:

- terminal transition transaction decrements slot exactly once using resource state/revision guard.

Close/expired/lost likewise releases slot once.

Worker physical capacity remains additional separate admission layer.

---

## 6. Job resource quota

Job creation transaction:

1. lock PrincipalUsage;
2. check non-terminal Job quota;
3. insert Job + JobItems + Outbox;
4. increment `nonterminal_jobs`;
5. commit.

Terminal Job transition decrements once.

Job retention after terminal не занимает non-terminal execution slot, но result Content bytes могут still count storage quota.

---

## 7. Active JobAttempt fairness quota

Job claim transaction may lock PrincipalUsage and enforce:

```text
active_job_attempts < principal execution limit
```

On successful Attempt claim increment.

Attempt terminal/lost decrement exactly once.

Если limit reached:

- Job remains queued/eligible;
- worker does not execute body;
- retry/defer wake-up bounded;
- no attempt created that consumes work slot.

Reconciler corrects drift after worker crashes.

---

## 8. Logical Content storage quota

Quota charges **logical retained ContentObject bytes per owner**, not physical object-store bytes.

Reason:

- physical SHA blob can be deduplicated across owners;
- charging physical unique bytes leaks/distorsts cross-owner dedup semantics;
- owner quota should reflect resources logically retained by that owner.

Thus two owners referencing same hash each consume their own logical `size_bytes` quota.

---

## 9. Content publish quota transaction

Size becomes authoritative after staging/hash.

Before `creating → available` publish:

1. lock PrincipalUsage row;
2. check `retained_content_bytes + size <= effective quota`;
3. if allowed: CAS Content available + increment bytes same DB transaction;
4. if denied: Content creation fails `storage_quota_exceeded`; staged/final physical object follows cleanup/GC and is not publicly available.

This may consume network/temp I/O before final quota check, but preserves durable quota correctness.

Known `Content-Length`/source size can early reject when obviously impossible.

---

## 10. Content derived representations

Every available derived ContentObject counts its logical bytes unless representation retention class is explicitly exempt/system-owned by policy.

This prevents unlimited parser-derived duplication bypassing quota.

Existing representation reuse does not double-charge because no new logical object is created when exact existing owner-compatible ContentRef is reused.

---

## 11. Content expiry/delete release

Transition from charged available state to expired/deleted releases `size_bytes` exactly once under state/revision guard.

Physical blob GC independent and may occur later.

Restoring expired/deleted Content is not baseline; future restore would need re-admission quota.

---

## 12. Transient staging/temp budgets

Logical retained quota does not alone protect staging/browser/parser temp disk.

Separate ephemeral capacity policies remain:

- ContentStore staging bytes/global;
- Browser temp/session bytes;
- parser temp;
- S3 multipart incomplete limits.

These may use local/storage metrics and hard limits, not PrincipalUsage retained bytes.

---

## 13. Billable usage model

Add durable provider usage tables, conceptually:

```text
provider_usage_periods
usage_reservations / usage_events
```

Period key:

```text
principal_id
provider_id
budget_unit_type
period_start
policy/budget revision
```

Aggregate fields:

```text
consumed_units
reserved_units
revision
```

---

## 14. Budget unit

Application uses provider-defined **billable unit**, not hardcoded currency.

Examples:

```text
search_request
api_call
provider_credit_unit
```

Pricing/reporting may map units to money separately.

Policy limits units per period.

---

## 15. Reservation before upstream attempt

Before a billable attempt that may incur charge:

1. identify stable `usage_attempt_id` derived from operation/provider attempt;
2. lock period usage row;
3. if reservation already exists → return same state idempotently;
4. check `consumed + reserved + requested <= limit`;
5. insert reservation;
6. increment reserved;
7. commit;
8. permit upstream call.

Concurrent replicas cannot overspend same durable budget through race.

---

## 16. Finalize reservation

After upstream attempt:

### Known not sent

Release reservation → reserved decremented, consumed unchanged.

### Request sent / provider may bill

Conservatively consume according provider semantics:

```text
reserved -= units
consumed += units
usage event finalized
```

Even if response lost, if billing may have occurred, units remain consumed unless provider contract proves otherwise.

This aligns financial safety with `unknown` network outcome.

---

## 17. Reservation timeout/reconciliation

Crash after reservation before known send leaves pending reservation.

Usage reservation records phase/evidence enough for reconciler:

```text
reserved
upstream_started | null
finalized | null
```

If durable evidence proves request never started, release.

If send state is unknown after crash, conservative policy may consume/reserve until operator/reconciler resolution according provider contract.

Never blindly refund uncertain paid attempt.

---

## 18. Search cache relationship

Cache hit:

```text
no upstream attempt
→ no billable reservation
```

Rate/concurrency flow remains ADR-0005.

Budget reservation happens only in provider-call path after cache decision.

---

## 19. Retry relationship

Each actual billable retry has own usage_attempt_id/reservation.

Retry policy checks remaining budget before new attempt.

Budget exhausted stops retry and returns `billable_budget_exceeded`, not hidden provider fallback.

---

## 20. Policy revision changes mid-period

Usage consumed does not reset merely because policy revision changes.

Budget period identity is semantic period (day/month/custom) + provider/principal; policy revision records which limit admitted an attempt.

When limit lowered below already consumed units:

- existing usage remains;
- new reservations rejected until next period or operator raises limit.

No negative/retroactive accounting.

---

## 21. Unlimited policy

`unlimited` is explicit typed state, not magic huge integer.

Even unlimited provider policy still records usage for observability/audit if provider is billable.

Hard deployment/provider rate/capacity controls remain.

---

## 22. Counter reconciliation

Periodic `UsageReconciler`:

- recomputes Browser/Job/Content aggregate counts in bounded chunks;
- compares PrincipalUsage;
- CAS repairs mismatch;
- emits drift metric/audit warning where significant.

It does not rewrite finalized billable usage ledger from generic resource rows, because provider billing attempts have separate evidence.

---

## 23. Transaction ordering/deadlocks

All resource quota transactions lock rows in consistent order:

```text
PrincipalUsage / provider period usage
→ target resource rows
```

or another single documented global order chosen implementation-wide.

Concurrency tests include Browser create vs Job create vs Content finalize for same principal.

---

## 24. Admin reset/correction

Ordinary admin policy update does not edit usage history.

Exceptional accounting correction uses explicit typed admin operation:

- requires admin scope;
- records adjustment event, not silent overwrite;
- reason required;
- audited.

No generic SQL mutation endpoint.

---

## 25. API errors

Normalized:

```text
resource_quota_exceeded
storage_quota_exceeded
billable_budget_exceeded
execution_quota_exceeded
```

Result may include bounded current/limit/reset timestamp only when safe/useful.

Do not leak other principals/global sensitive usage.

---

## 26. Tests

1. two replicas concurrent Browser create at last slot → one admitted;
2. failed Browser create releases exactly once;
3. worker loss releases after terminal resource transition;
4. concurrent Job creates at quota;
5. active Attempt fairness quota;
6. Content finalizations same principal race;
7. same physical hash two owners charged logically separately;
8. derived representation charged/reuse not double-charged;
9. expiry/delete release once;
10. UsageReconciler repairs injected drift;
11. two concurrent billable reservations at last unit;
12. same usage_attempt_id idempotent;
13. crash reserved before send;
14. response loss after send conservatively consumed;
15. retry consumes separate units;
16. lowering policy below consumed blocks new attempts;
17. Redis loss cannot reset durable quota/budget.

---

## 27. Consequences

Плюсы:

- multi-replica quota correctness;
- Redis loss does not lose durable usage;
- Content dedup does not leak cross-owner information;
- paid provider overspend races prevented;
- reconciliation handles drift;
- resource lifecycle and quotas aligned.

Минусы:

- hot principal usage row can become lock hotspot;
- more DB transactions on resource creation/finalization;
- billable reservation model is complex;
- staging may consume temporary resources before storage quota final check.

If hot-row contention appears under measured load, sharded/escrow counters can be separate future ADR while preserving public policy semantics.

---

## 28. Не определяется

- exact table/column names;
- exact budget period calendar/timezone beyond UTC-normalized policy;
- actual provider pricing;
- invoice generation;
- distributed sharded quota optimization;
- user-facing quota dashboard.
