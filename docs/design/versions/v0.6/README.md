# v0.6 — Durable Jobs Runtime

## Статус

`ready for implementation`

Версия добавляет durable/background execution только для явно зарегистрированных typed workloads. Короткие Search/Retrieval/Content/Browser operations не становятся Jobs автоматически.

---

# 1. Цель

После v0.6 клиент может:

```text
создать retrieval/content batch Job
→ получить JobRef
→ отключиться
→ читать progress/state
→ отменить Job
→ получить terminal manifest
```

Система переживает Redis/publisher/worker/Control Plane failures без потери committed Job и без повторной обработки уже checkpointed successful items.

---

# 2. Prerequisites

- v0.1 Foundation;
- v0.3 Retrieval & Content Core;
- v0.5 Native Content Expansion при последовательном roadmap;
- `../../jobs.md`;
- `../../persistence.md`;
- `../../resource-model.md`;
- `../../mcp.md`;
- `../../rest-api.md`;
- ADR-0017 outbox/arq delivery;
- ADR-0018 first typed jobs + JobItems;
- ADR-0021 direct MCP operation vs Job tool boundary.

---

# 3. Non-goals

- arbitrary task/Python execution;
- cron/scheduler;
- crawl;
- durable Browser workflow;
- exactly-once guarantee;
- infinite retry;
- distributed item sharding one Job across many workers;
- automatic direct→Job promotion;
- generic public `job_create(command,args)`.

---

# 4. Runtime topology

```text
Control Plane
  │
  ├── PostgreSQL
  │    ├── jobs
  │    ├── job_attempts
  │    ├── job_items
  │    ├── job_events
  │    └── outbox
  │
  └── Redis/arq wake-up
          │
          ▼
      Job Worker(s)
       ├── arq consumer
       ├── JobRunner
       ├── OutboxPublisher loop
       └── JobReconciler loop
```

Publisher/reconciler могут позднее быть отдельными runtime без public/application contract change.

---

# 5. Persistence model

## Job

```text
job_id
owner_principal_id
job_type + revision
state + revision
input summary/ref
progress
result summary/result_content_id
error
created/queued/started/terminal timestamps
next_attempt_at
overall_deadline_at
retention/expiry
```

## JobAttempt

```text
attempt_id
job_id
attempt_number
worker_id/generation
state
lease/fencing coordinates
heartbeat/start/completion
result/error summary
```

## JobItem

```text
job_item_id
job_id
item_index
item_type
bounded input/ref
state/revision
attempt_id | null
attempt_count
next_retry_at
result refs/summary
error
```

`(job_id,item_index)` unique; input order preserved.

## JobEvent

Bounded durable client-visible lifecycle/progress events.

## Outbox

ADR-0017 model.

---

# 6. Lifecycle

Job:

```text
created → queued → running → succeeded
                    ├→ retry_wait → queued
                    ├→ cancelling → cancelled
                    └→ failed
terminal → expired
```

Attempt:

```text
claimed → running → succeeded | failed | cancelled | lost
```

Item:

```text
pending → running → succeeded | failed
                     └→ retry_wait → running
pending/running/retry_wait → cancelled
```

`lost` belongs to Attempt; Job recovery policy decides retry/failure.

---

# 7. Transactional creation and delivery

One DB transaction:

```text
Job(created)
+ ordered JobItems
+ enqueue Outbox
+ created event
→ COMMIT
```

Then:

```text
OutboxPublisher
→ arq lightweight message(job_id, dispatch_generation)
→ DB mark published/queued
```

Redis is at-least-once wake-up, not source of truth.

Worker performs authoritative PostgreSQL claim before body execution.

---

# 8. Duplicate delivery / fencing

- deterministic arq queue ID is optimization only;
- duplicate messages allowed;
- one current DB Attempt claim executes;
- all Attempt-owned writes include current attempt/revision;
- stale/lost worker cannot commit over newer Attempt.

---

# 9. Attempt lease defaults

Initial:

```text
heartbeat interval = 10 s
attempt lease = 45 s
lost reconciliation grace = 60 s
```

Config-validated and overridable stricter per Job type.

Expired Attempt → `lost`; retryable Job moves `retry_wait`, otherwise failed.

---

# 10. Retry/cancellation defaults

Initial public Job profile:

```text
max Job attempts = 3
max item attempts = 3
overall lifetime = 6 h
```

Retry is error/job-type specific; no retry permanent validation/policy/malformed/unsupported/hard-limit error.

Cancellation stores durable intent, stops new items, cooperatively cancels active work, and becomes `cancelled` only when execution has stopped.

---

# 11. JobItem checkpoints

One active JobAttempt baseline; it processes items with bounded internal concurrency.

If worker dies:

```text
succeeded items stay succeeded
running items of lost Attempt → eligible retry/recovery
pending stay pending
```

No restart of whole batch.

---

# 12. `retrieval_batch`

Each URL = JobItem.

Uses exact same application path as direct `web_fetch`:

```text
SafeHttpFetcher
→ raw ContentObject
→ L0
→ request-independent direct L1 where applicable
```

No Browser/L2.

MCP Job tool limit:

```text
web_fetch_job urls: 1..256
```

REST public batch hard item ceiling baseline:

```text
1000 items
```

Initial aggregate decoded-byte budget:

```text
default 512 MiB
hard 2 GiB
```

Initial per-Job item concurrency: `8`, still bounded by global/per-host Retrieval policies.

---

# 13. `content_parse_batch`

Each ContentRef = JobItem.

Uses same ContentApplication/parser registry as direct `content_parse`.

Existing compatible representation can return `reused=true` without new parse.

MCP:

```text
content_parse_job content_ids: 1..256
```

REST public hard item ceiling baseline: `1000`.

Initial aggregate source bytes:

```text
default 512 MiB
hard 2 GiB
```

Initial parser item concurrency: `4` or lower global isolated-parser capacity.

No L2.

---

# 14. Partial batch result

When all items terminal:

```text
all succeeded
→ Job succeeded, aggregate succeeded

expected mix success/item failures
→ Job succeeded, aggregate partial

framework/invariant/deadline failure preventing normal completion
→ Job failed
```

A bad URL/document is not automatically infrastructure Job failure.

---

# 15. Progress

Measured by real work:

```text
completed = terminal items
total = item count
unit = items
```

Plus bounded counts by outcome/state and bytes where meaningful.

Progress writes coalesced; JobItem state remains durable.

---

# 16. Result manifest

Terminal/partial/cancelled batch with results creates immutable structured ContentObject manifest preserving original item order.

Job row stores bounded summary + `result_content_id`.

Job does not claim successful finalization until required manifest is available via Content lifecycle.

Crash during manifest creation retries finalization, not successful JobItems.

---

# 17. MCP direct vs durable boundary

Per ADR-0021:

```text
web_fetch         → direct request-bound
web_fetch_job     → create retrieval_batch Job

content_parse     → direct request-bound
content_parse_job → create content_parse_batch Job
```

No `execution=direct|durable` field.

Reason: direct and Job creation have different resource/retry semantics and need different trusted Agent descriptors.

Direct tool can return `processing_requires_job` hint with exact same-service Job tool.

---

# 18. MCP Job lifecycle

```text
job_get(job_ids[])
job_cancel(job_ids[])
```

`job_get` read-only: state/progress/retry summary/result manifest/error/hints.

`job_cancel` idempotent cancellation request; response can be `cancelling`.

No generic public Job start tool.

---

# 19. REST API

Typed creation/lifecycle:

```text
POST /api/v1/jobs/retrieval-batches
POST /api/v1/jobs/content-parse-batches
GET  /api/v1/jobs/{job_id}
POST /api/v1/jobs/{job_id}/cancel
GET  /api/v1/jobs/{job_id}/events
```

REST never exposes arq function/Redis payload.

---

# 20. Retention/readiness

Terminal Job/result/event retention policy initially aligned with explicit `job_result` retention class (24h default direction before v0.7 policy hardening).

Jobs readiness considers:

- PostgreSQL;
- Redis/arq;
- outbox backlog age;
- Job Worker availability;
- reconciler;
- ContentStore manifest capability.

Redis outage can delay execution of already committed Job but cannot lose it.

---

# 21. Security

- Job owner from PrincipalContext;
- input ContentRefs owner-checked;
- no arbitrary handler name from client;
- queue payload small/no secrets/no pickle;
- Job Worker gets scoped dependencies only;
- result manifest remains untrusted web-derived data;
- no maintenance Job publicly exposed by default.

---

# 22. Observability

Required:

- Jobs/Attempts/Items by state/type;
- outbox backlog/oldest age/publish errors;
- worker claims/rejections/lease loss;
- retry/cancel latency;
- item throughput;
- manifest finalization;
- queue/backlog admission;
- worker utilization.

No raw URLs/content as metric labels.

---

# 23. Required tests

- all ADR-0017 publish crash windows;
- duplicate delivery one execution;
- Redis outage/recovery;
- worker lost attempt/retry;
- stale attempt fenced;
- JobItem checkpoint resume;
- per-item partial success;
- cancellation every lifecycle stage;
- manifest crash/recovery;
- MCP `*_job` creation + trusted semantics;
- direct tools contain no durable execution mode;
- job_get/cancel owner isolation;
- 256-item MCP / 1000-item REST load profiles;
- repeated worker kill/soak.

---

# 24. Definition of Done

1. Committed Job cannot be lost between DB and Redis.
2. Duplicate delivery cannot duplicate active execution.
3. Lost worker cannot leave permanent running Job.
4. Stale Attempt cannot overwrite retry.
5. Successful items survive attempts.
6. Cancellation honest/durable.
7. Partial item failure distinct from framework failure.
8. Result manifest durable.
9. MCP uses separate direct and Job tools with stable execution class.
10. REST uses typed Job endpoints.
11. No crawl/generic task/browser workflow creep.
12. Applicable race/fault/load/schema gates green.
