# v0.6 — Durable Jobs Runtime

## Статус

`ready for implementation`

Версия добавляет устойчивое background execution для **явно выбранных typed long-running workloads**. Она не переводит все Web Access operations в очередь.

---

# 1. Цель

После v0.6 клиент должен уметь:

```text
создать durable retrieval/content batch
→ сразу получить JobRef
→ отключиться
→ позже получить progress/state
→ отменить job
→ получить terminal summary/result manifest
```

а система должна переживать:

- Redis outage;
- duplicate queue delivery;
- Job Worker crash/restart;
- outbox publisher crash;
- attempt lease loss;
- Control Plane restart;
- cancellation;
- partial per-item failures;

без потери Job и без повторной обработки уже успешно checkpointed items.

---

# 2. Prerequisites

- v0.1 Foundation;
- v0.3 Retrieval & Content Core;
- v0.5 Native Content Expansion для полного parser capability set, если реализуется в roadmap порядке;
- `../../jobs.md`;
- `../../application-contracts.md`;
- `../../resource-model.md`;
- `../../persistence.md`;
- `../../observability.md`;
- `../../security.md`;
- `../../rest-api.md`;
- `../../mcp.md`;
- `../../deployment.md`;
- `../../testing.md`;
- `../../release-gates.md`;
- ADR-0017 outbox/arq delivery;
- ADR-0018 typed Job/JobItem workloads.

---

# 3. Explicit non-goals

v0.6 не реализует:

- generic arbitrary task execution;
- arbitrary Python/code payload;
- cron/scheduler;
- crawl;
- durable Browser click/navigation workflow;
- distributed sharding одного batch Job по множеству workers;
- exactly-once execution guarantee;
- infinite retry;
- automatic direct→durable promotion;
- automatic creation of Job because request «seems large»;
- generic MCP `job_run(command, args)`.

---

# 4. Runtime topology

Добавляется полноценный Job Worker runtime:

```text
Control Plane
  │
  ├── PostgreSQL
  │     ├── jobs
  │     ├── job_attempts
  │     ├── job_items
  │     ├── job_events
  │     └── outbox
  │
  └── Redis/arq delivery
           │
           ▼
      Job Worker replica(s)
           │
           ├── arq consumer
           ├── JobRunner
           ├── outbox publisher/coordinator loop
           └── reconciler loop
```

Publisher/reconciler могут позднее быть выделены в отдельный runtime без изменения application contracts.

---

# 5. Job tables

## `jobs`

Minimum:

```text
id
job_id
owner_principal_id
job_type
job_type_revision
state
revision
input_summary/input_manifest_ref
progress JSONB bounded
result_summary JSONB bounded
result_content_id | null
error JSONB | null
created_at
updated_at
queued_at | null
started_at | null
next_attempt_at | null
cancellation_requested_at | null
terminal_at | null
expires_at | null
overall_deadline_at | null
```

## `job_attempts`

```text
id
attempt_id
job_id FK
attempt_number
worker_id
worker_generation
state
lease_token/revision
lease_expires_at
heartbeat_at
started_at
completed_at
error/result summary
```

## `job_items`

```text
id
job_item_id
job_id FK
item_index
item_type
input JSONB bounded / ContentRef
state
revision
attempt_id | null
attempt_count
next_retry_at | null
result_summary JSONB bounded
result_refs JSONB bounded
error JSONB | null
started_at | null
completed_at | null
```

Unique:

```text
(job_id, item_index)
```

## `job_events`

Bounded durable client-visible lifecycle/progress events.

## `outbox`

Согласно ADR-0017.

---

# 6. Job lifecycle

Canonical:

```text
created
→ queued
→ running
→ succeeded
```

Additional:

```text
running → retry_wait → queued
created/queued/running/retry_wait → cancelling → cancelled
running/retry_wait → failed
terminal → expired
```

`lost` принадлежит JobAttempt, не Job terminal state.

---

# 7. JobAttempt lifecycle

```text
claimed
→ running
→ succeeded | failed | cancelled | lost
```

Every actual execution claim = new Attempt.

Late/stale attempt fenced by `attempt_id` + lease/revision.

---

# 8. JobItem lifecycle

```text
pending
→ running
→ succeeded
       │
       ├→ failed
       └→ retry_wait → running

pending/running/retry_wait → cancelled
```

Only current active JobAttempt can transition its running items.

Succeeded items are never restarted within same Job.

---

# 9. Transactional creation

Public typed create operation performs one PostgreSQL transaction:

```text
INSERT Job(created)
INSERT JobItems in original order
INSERT Outbox(enqueue_job)
INSERT created event
COMMIT
```

После commit JobRef durable even if Redis unavailable.

No direct enqueue before DB commit.

---

# 10. Outbox publisher

According ADR-0017:

- bounded DB batch claim;
- lease/`SKIP LOCKED`-style coordination;
- no transaction held during Redis call;
- publish lightweight job ID message;
- at-least-once;
- deterministic queue ID optimization;
- DB mark published/queued after enqueue;
- retry/backoff on failure;
- multiple publisher replicas safe.

---

# 11. Job Worker/arq

Add `arq` as infrastructure dependency pinned in `uv.lock`.

Queue has fixed internal dispatcher function, conceptually:

```text
process_job(job_id, dispatch_generation)
```

No public function name/arguments reach arq directly.

Worker message is wake-up only; DB claim decides execution.

---

# 12. Job Worker identity

Worker:

```text
worker_id
worker_generation
supported job types/revisions
```

Generation changes after process restart.

Attempt row records both.

Worker capability mismatch rejects claim without executing wrong handler revision.

---

# 13. Claim and fencing

Claim transaction checks:

- Job current state;
- no active valid Attempt;
- cancellation/deadline;
- dispatch generation;
- handler support;
- attempts policy.

Then creates Attempt + Job `running`.

Every later attempt-owned update checks current attempt ID/revision.

Stale worker cannot publish progress/result after lease loss.

---

# 14. Attempt lease

Initial defaults:

```text
heartbeat interval = 10 s
attempt lease = 45 s
lost-attempt reconciliation grace = 60 s
```

Config validation keeps heartbeat substantially shorter than lease.

Long downstream phase must not exceed lease without heartbeat task running independently.

---

# 15. Retry defaults

Initial public typed jobs:

```text
max Job attempts = 3
max item attempts = 3
overall Job lifetime = 6 h
```

Retry policy always error/job-type specific.

No retry for validation/policy/permanent malformed/unsupported/resource-hard-limit cases.

---

# 16. Retry scheduling

Durable:

```text
Job/JobItem retry_wait
next_retry_at
```

Reconciler/outbox creates wake-up when due.

Redis deferred scheduling alone is never durable source of retry timing.

Backoff + jitter configurable and bounded.

---

# 17. Cancellation

`cancel(job_id)` stores durable intent.

Rules:

- no new items start after observed cancellation;
- running handler receives cooperative cancellation context;
- terminal `cancelled` only after no active execution;
- terminal job cancel is idempotent;
- completed ContentObjects remain valid;
- partial result manifest is created when useful results exist.

Cancellation signal delivery may be optimized through Redis but DB state remains authoritative.

---

# 18. Progress

For batch jobs:

```text
completed = terminal JobItems
total = JobItems count
unit = items
```

Summary includes counts by state/outcome.

Progress writes coalesced/throttled; no DB row per URL chunk/network event.

Event sequence monotonic.

---

# 19. First job type: `retrieval_batch`

Input:

```text
urls[]
common stable Retrieval options/profile
```

One URL = one JobItem.

Handler reuses:

```text
SafeHttpFetcher
→ Content ingest
→ L0
→ available direct L1
```

No Browser/L2.

Succeeded item stores ContentRefs and retrieval metadata.

---

# 20. `retrieval_batch` limits

MCP durable:

```text
urls: 1..256
```

REST public hard item ceiling baseline:

```text
1,000 items/job
```

Initial aggregate decoded-byte budget:

```text
default = 512 MiB
hard = 2 GiB
```

Underlying per-item Retrieval limits remain applicable.

Initial per-job item concurrency:

```text
8
```

Global/per-host Retrieval limits still dominate where lower.

---

# 21. Second job type: `content_parse_batch`

Input:

```text
content_ids[]
optional stable requested representation/profile
```

Each item owner-authorized before/during job creation.

Handler reuses ContentApplication/registry.

Existing compatible representation returns `reused=true`.

No L2.

---

# 22. `content_parse_batch` limits

MCP durable:

```text
content_ids: 1..256
```

REST public hard item ceiling baseline:

```text
1,000
```

Initial aggregate source-byte processing budget:

```text
default = 512 MiB
hard = 2 GiB
```

Initial Job-level parser concurrency:

```text
4 or lower global isolated-parser capacity
```

---

# 23. Partial batch semantics

Permanent item failure does not automatically mean Job runtime failed.

When all items terminal:

```text
all success
→ Job succeeded / aggregate succeeded

mix success + expected item failures
→ Job succeeded / aggregate partial

framework/invariant/deadline catastrophic failure
→ Job failed
```

This distinction must be preserved REST/MCP.

---

# 24. Result manifest

Terminal batch creates structured immutable ContentObject manifest preserving original item order.

Job row stores small summary + `result_content_id`.

Manifest includes bounded per item:

- index;
- input summary;
- outcome;
- result refs;
- normalized error;
- warnings/hints.

Large item payload is never copied into manifest when ContentRef suffices.

---

# 25. Manifest finalization

Job does not transition terminal success/partial until required manifest is `available` via normal Content lifecycle.

Crash after items complete but before manifest publish is recoverable finalization work and must not re-run succeeded items.

---

# 26. MCP execution mode

To preserve one intent → one canonical tool:

```text
web_fetch(..., execution="direct" | "durable")
content_parse(..., execution="direct" | "durable")
```

Default `direct`.

No `web_fetch_job`/`content_parse_job` tools.

No automatic promotion.

---

# 27. MCP cross-field schemas

`web_fetch` actual schema must express:

```text
direct  → urls 1..8
durable → urls 1..256
```

`content_parse` similarly uses direct version limit vs durable 1..256.

Use actual discriminated/cross-field JSON Schema + runtime validation.

Tool description on Russian explicitly explains that durable mode returns `JobRef` and survives disconnect.

---

# 28. MCP result union

Result remains application envelope, but `data` is discriminated by execution mode:

```text
direct_result
or
durable_job_ref
```

LLM should never infer from missing fields which mode happened; explicit `execution`/result kind present.

---

# 29. MCP Job lifecycle tools

```text
job_get
job_cancel
```

`job_get` returns bounded:

- state;
- job type;
- progress;
- attempts/retry summary;
- aggregate result summary;
- result manifest ContentRef if available;
- error/warnings/hints.

`job_cancel` returns current cancellation lifecycle, not fake immediate success.

---

# 30. REST API

Typed durable creation endpoints:

```text
POST /api/v1/jobs/retrieval-batches
POST /api/v1/jobs/content-parse-batches
GET  /api/v1/jobs/{job_id}
POST /api/v1/jobs/{job_id}/cancel
GET  /api/v1/jobs/{job_id}/events
```

Optional item/result pagination can be added through typed Job REST resources if necessary; result manifest remains canonical bulk result.

No generic public arbitrary job command endpoint.

---

# 31. Job retention

Initial defaults:

```text
terminal Job metadata/events = 24 h minimum baseline
result ContentObject uses explicit job-result retention class, initial 24 h unless caller saves/extends via future policy
outbox published rows = shorter operational retention, e.g. hours/day configurable
```

Exact operator retention configurable.

Cleanup must not delete result ContentObject while retained Job still references it unless lifecycle explicitly marks missing/expired result.

---

# 32. Readiness/degraded state

Jobs capability status considers:

- PostgreSQL;
- Redis/arq;
- outbox backlog age/size;
- Job Worker heartbeat/capability;
- reconciler health;
- ContentStore for result manifests.

Redis outage may leave Job creation durable but execution delayed; response/status must not claim queued execution is progressing.

Admission can reject new Jobs when backlog policy exceeded.

---

# 33. Observability

Metrics/traces:

- Jobs by state/type;
- outbox pending/oldest age/publish attempts;
- queue publish errors;
- worker claims/rejections;
- active attempts/lease renewals/lost attempts;
- item throughput/outcomes/retries;
- cancellation latency;
- job duration;
- manifest finalize latency;
- backlog/admission rejects;
- worker utilization.

No raw URLs/content in metric labels.

---

# 34. Security

- Job owner fixed from authenticated PrincipalContext;
- all ContentRefs owner-validated;
- raw public job payload never names Python function;
- no pickle Redis payload;
- no secrets in queue message;
- Job Worker gets only credentials needed for its capabilities;
- maintenance/admin job types not automatically exposed public;
- result manifests treated as untrusted web-derived content.

---

# 35. Required tests

## Outbox/queue

- all ADR-0017 crash windows;
- duplicate delivery;
- Redis outage/recovery;
- multi-publisher contention;
- stale queue message.

## Attempt/lease

- worker crash after claim;
- lease expiry;
- stale terminal update fenced;
- retry_wait concurrent reconcilers;
- rolling Job Worker restart.

## JobItem

- checkpoint after N successes;
- lost running reset/retry;
- succeeded not rerun;
- per-item permanent failure;
- item attempt ceiling;
- original order.

## Cancellation

- created/queued/running/retry_wait;
- active downstream cancellation;
- partial manifest.

## Facades

- REST typed routes/OpenAPI;
- MCP direct/durable schema positive/negative;
- `job_get`/`job_cancel` ownership;
- no generic public execution primitive.

## Load/soak

- large backlog;
- multiple workers;
- Redis restart;
- PostgreSQL contention;
- repeated worker kill/recovery;
- progress write amplification bounded.

---

# 36. Release gates

Applicable:

- persistence/migration;
- outbox consistency;
- Jobs lifecycle;
- race/fault;
- cancellation/retry;
- owner/security;
- REST/MCP actual contracts;
- observability/readiness;
- load/soak;
- local Compose reproducibility.

---

# 37. Definition of Done

v0.6 завершена только если:

1. committed Job cannot be lost between PostgreSQL and Redis.
2. Duplicate queue delivery does not duplicate execution.
3. Worker crash does not leave Job forever running.
4. Stale attempt cannot commit after retry.
5. Succeeded JobItems survive attempt restart.
6. Retrieval/content batch resumes unfinished items only.
7. Cancellation durable and honest.
8. Progress reflects actual items.
9. Partial item failures represented separately from framework failure.
10. Result manifest survives client disconnect.
11. MCP uses explicit direct/durable mode without new duplicate-intent tools.
12. REST exposes typed durable creation/lifecycle.
13. No crawl/browser-workflow arbitrary creep.
14. All applicable release gates green.
