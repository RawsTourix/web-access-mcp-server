# ADR-0017 — Durable Job delivery: PostgreSQL outbox → arq wake-up → authoritative DB claim

**Статус:** accepted

## 1. Контекст

Jobs design уже определяет:

```text
Job + JobAttempt
PostgreSQL authoritative state
Transactional Outbox
Redis/arq delivery
worker claim/lease/fencing
```

Нужно зафиксировать конкретную delivery semantics до implementation.

У проверенного KudaGo-сервера используется практичный паттерн:

```text
commit Job
→ enqueue arq message с job_id
→ worker получает ID
```

и deterministic queue job ID защищает от части duplicate enqueue cases.

Для Web Access требуется stronger crash consistency: нельзя оставлять незащищённый dual-write `PostgreSQL commit → Redis enqueue`, где process может погибнуть между двумя системами.

---

## 2. Решение

Canonical delivery:

```text
PostgreSQL transaction
  ├── INSERT Job(state=created)
  └── INSERT OutboxEvent(job_enqueue)
        ↓ commit

Outbox Publisher
  → publish lightweight arq message(job_id, dispatch_generation)
  → mark outbox published / Job queued idempotently
        ↓

Job Worker
  → receive duplicate-tolerant wake-up
  → authoritative PostgreSQL claim
  → create JobAttempt + lease
  → execute typed job handler
```

Redis/arq не является source of truth.

---

## 3. Queue payload

Queue message deliberately small:

```text
protocol_version
job_id
job_type/revision hint (optional validation only)
dispatch_generation / enqueue_revision
```

Job input payload **не дублируется полностью в Redis**.

Worker после claim читает authoritative typed input из PostgreSQL/ContentRef metadata.

Большие input bytes всегда находятся в ContentStore, а Job row хранит refs.

---

## 4. Deterministic arq job ID

Queue adapter использует deterministic bounded ID, например:

```text
wa:<job_id>:<dispatch_generation>
```

или hash-equivalent.

Это уменьшает duplicate queued entries, но **не считается correctness guarantee**.

Duplicate delivery всё равно поддерживается end-to-end через DB claim.

---

## 5. Outbox row

Минимальная модель:

```text
outbox_id
aggregate_type = job
aggregate_id = job_id
event_type = enqueue_job
payload_version
dispatch_generation
state
created_at
available_at
published_at | null
attempt_count
last_error_code | null
lease_owner | null
lease_expires_at | null
```

Exact SQL names implementation-specific.

---

## 6. Outbox states

Минимальная internal semantics:

```text
pending
publishing
published
```

`publishing` является lease/claim phase, а не необратимым state.

Expired publisher lease делает row снова eligible.

Permanent `failed` baseline не должен silently orphan Job: after bounded repeated infrastructure errors row остаётся retryable/operationally visible until operator policy/dead-letter process explicitly resolves it.

---

## 7. Publisher claim

Несколько Control Plane/background publisher replicas могут работать параллельно.

Publisher выбирает bounded batch eligible rows через PostgreSQL locking semantics (`FOR UPDATE SKIP LOCKED` или equivalent repository implementation).

Claim:

- записывает publisher identity/lease;
- increment attempt count;
- не держит DB transaction открытой во время Redis network call;
- после commit выполняет publish.

---

## 8. Publish success crash window

Возможен crash:

```text
Redis publish succeeded
→ process died before DB mark published
```

После lease expiry publisher повторит publish.

Это нормально:

- queue delivery at-least-once;
- deterministic queue ID снижает duplicates;
- DB worker claim окончательно предотвращает concurrent duplicate execution.

Не пытаться добиться exactly-once Redis publish сложной distributed transaction.

---

## 9. DB mark published

После successful enqueue publisher transactionally:

- CAS outbox row current lease/generation;
- marks `published`;
- updates Job `created → queued` if still applicable;
- records bounded lifecycle event.

Если Job уже cancelling/cancelled/terminal, stale outbox can be marked consumed/published-without-execution according reconciliation; queue wake-up later rejected by claim.

---

## 10. Publish failure

Redis/arq unavailable:

- outbox remains durable pending after lease expiry/backoff;
- Job remains `created` (or queue-unavailable observable state via metadata, not new public lifecycle state);
- client JobRef remains valid;
- publisher retries with bounded backoff;
- readiness/capability becomes degraded;
- no synchronous request thread loops forever retrying Redis.

---

## 11. Publisher backoff

Use bounded exponential-like backoff + jitter operationally.

Outbox stores `available_at`.

No worker/process sleep for long intervals.

Exact timings configurable; infinite rapid retry forbidden.

---

## 12. arq adapter

Concrete `ArqJobQueue` port implementation uses arq Redis queue.

Application layer does not import arq.

Adapter responsibilities:

- enqueue known worker function name;
- serialize small versioned payload;
- deterministic queue ID;
- optional defer-until for retry wake-ups only where consistent with durable DB state;
- normalize Redis/arq errors.

No arbitrary function name from public client.

---

## 13. Worker entrypoint

Job Worker registers a small fixed set of internal arq entry functions, preferably one dispatcher:

```text
process_job(job_id, dispatch_generation)
```

Inside:

```text
validate envelope
→ DB claim
→ resolve typed JobHandler from registry
→ execute
```

Queue function name is infrastructure, not public job type.

---

## 14. PostgreSQL claim

Worker receiving message must atomically prove execution right.

Claim transaction verifies:

- Job exists;
- owner/input metadata valid;
- state permits start;
- dispatch generation current;
- no active valid attempt;
- not already terminal/cancelled;
- required handler/revision supported;
- overall deadline not expired.

Then creates `JobAttempt` and transitions Job to `running`.

Only committed successful claim permits handler execution.

---

## 15. Duplicate queue delivery

Example:

```text
message A → worker A → claim succeeds
message duplicate → worker B → claim sees active attempt → no-op
```

Worker B returns successful infrastructure acknowledgement/no execution.

Duplicate message is not application error.

---

## 16. Attempt identity/fencing

Each claim creates:

```text
attempt_id
attempt_number
worker_id
worker_generation
lease_token/revision
lease_expires_at
```

All progress/terminal updates must include current attempt coordinates.

Lost/stale attempt cannot commit result over new attempt.

---

## 17. Worker heartbeat/lease

Long attempt periodically updates bounded heartbeat/lease via DB.

Initial implementation direction:

```text
heartbeat every ~10 s
attempt lease ~30–60 s
```

Exact values per job type/runtime profile are configuration, with validation `heartbeat << lease`.

Job handler should not write heartbeat from tight inner loops directly; shared execution context/runner owns lease task.

---

## 18. Lost attempt

Reconciler sees expired active attempt lease:

1. marks attempt `lost` with fencing CAS;
2. evaluates JobType retry policy;
3. if retryable + attempts/deadline remain → Job `retry_wait` + `next_attempt_at` + new outbox wake-up when due;
4. otherwise Job `failed`.

No automatic retry for job type with unsafe unknown external side effects.

---

## 19. Retry scheduling

Durable source of retry timing:

```text
Job.state = retry_wait
next_attempt_at
```

A scheduler/reconciler creates/enables new enqueue outbox event when due.

Redis deferred job timing may be optimization/wake-up mechanism but **not only durable record** of retry schedule.

---

## 20. Cancellation delivery

Cancellation intent stored in PostgreSQL.

Worker learns it through:

- periodic execution context DB cancellation checks;
- optional Redis/internal wake-up optimization;
- lease/progress update responses.

Correctness does not require reliable Redis cancel message.

Running handler must cooperate at bounded checkpoints.

---

## 21. Worker shutdown

Graceful Job Worker shutdown:

- stop accepting new claims;
- stop/finish current attempts according per-handler shutdown/cancellation policy;
- do not falsely mark succeeded;
- if process dies, lease expiry/reconciler handles lost attempt;
- Redis message can be redelivered/recreated from durable state.

---

## 22. Queue outage and readiness

Redis/arq outage:

- request-bound Search/Retrieval may still operate according their own Redis dependencies/policies;
- Job creation may still durably create Job + Outbox if product policy allows accepting delayed execution;
- Jobs capability status clearly `degraded/queue_unavailable`;
- no Job is lost because enqueue is persisted.

Operator may configure admission to reject new Jobs when queue outage backlog exceeds bounded threshold.

---

## 23. Backpressure

Outbox/Jobs subsystem enforces:

- max pending Jobs per principal;
- max global pending Jobs;
- outbox backlog thresholds;
- per job-type worker concurrency;
- DB query batch ceilings;
- no unbounded in-memory queue in Control Plane.

Admission limits are policy, not queue length guesses.

---

## 24. Events/progress write amplification

Job lifecycle events durable but bounded.

Progress updates are coalesced/throttled; not every processed URL/chunk creates row.

Job current row stores latest progress summary.

Detailed item result goes to ContentObject/result manifest where needed.

---

## 25. Reconciler responsibilities

At least:

- expired outbox publisher leases;
- stale `created` Jobs with missing active outbox;
- queued Jobs lacking usable delivery for too long;
- expired attempt leases;
- retry_wait due;
- cancelling jobs with lost worker;
- terminal retention/expiry;
- stale queue messages are tolerated, not enumerated as source of truth.

Multiple reconciler instances must be concurrency-safe/idempotent.

---

## 26. Why not Redis Streams as primary Job queue

Current architecture already uses arq successfully in related service and Web Access only needs Redis as delivery/wake-up after durable PostgreSQL state.

Switching to custom Streams consumer-group protocol would duplicate:

- worker polling;
- retry/defer helpers;
- message lifecycle;
- operational tooling,

without improving authoritative semantics, because correctness still lives in PostgreSQL claim/lease.

If future scale/load evidence shows arq is bottleneck, `JobQueue` port permits replacement without public contract change.

---

## 27. Why no Celery baseline

Celery adds a larger worker/broker ecosystem than required for current all-async Python service.

The job contract intentionally remains independent of arq so future replacement is possible, but adding a second heavy orchestration system before evidence is unnecessary.

---

## 28. Tests

Required fault/race matrix:

1. crash before DB Job commit → no Job/outbox;
2. commit Job/outbox, crash before publish → later publisher enqueues;
3. publish success, crash before mark published → duplicate publish tolerated;
4. two publishers claim rows concurrently;
5. Redis outage/backlog recovery;
6. duplicate queue messages → one DB attempt;
7. worker crash immediately after claim;
8. worker crash midway;
9. old attempt terminal update after new claim → fenced;
10. retry_wait due across multiple reconcilers;
11. cancel before publish;
12. cancel while queued;
13. cancel while running;
14. queue message after terminal/cancelled → no execution;
15. publisher/worker rolling restart;
16. large outbox backlog bounded processing;
17. no unbounded progress DB writes.

---

## 29. Consequences

Плюсы:

- no DB+Redis lost-job window;
- at-least-once delivery safely tolerated;
- Redis remains replaceable infrastructure;
- queue message small;
- PostgreSQL authoritative;
- multiple publishers/workers safe;
- retry/cancellation durable.

Минусы:

- outbox publisher + reconciler complexity;
- Jobs can exist in `created` while Redis unavailable;
- more DB state/leases;
- exactly-once not promised.

Trade-off intentional: durable correctness is preferred over simpler but lossy enqueue path.

---

## 30. Не определяется

- exact arq/Redis version (pinned at implementation);
- exact outbox table/column names;
- exact heartbeat/lease numbers per job type;
- exact publisher batch size;
- exact queue names;
- autoscaling mechanism;
- future alternate JobQueue backend.
