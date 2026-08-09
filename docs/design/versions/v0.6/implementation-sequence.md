# v0.6 — Implementation sequence

## Назначение

Обязательный порядок реализации Durable Jobs Runtime.

Ключевой принцип:

> Сначала доказать durable creation/delivery/claim/fencing на synthetic handler. Только затем подключать реальные Retrieval/Content workloads и только после этого REST/MCP.

---

# Patch J0 — Preconditions

1. v0.1/v0.3 Content/persistence tests зелёные;
2. v0.5 если реализуется roadmap последовательно — parser/S3 gates зелёные;
3. actual REST/MCP schemas сохранены baseline fixtures;
4. Redis/PostgreSQL fault test infrastructure готова;
5. добавить `arq` dependency pinned через `uv.lock` после compatibility test с текущим Redis/Python stack.

No public Jobs routes/tools yet.

---

# Patch J1 — Job domain/application model

Реализовать:

- JobId/AttemptId/JobItemId;
- JobState/AttemptState/JobItemState;
- JobTypeDescriptor/registry;
- typed Job creation contracts;
- Job progress/error/result summaries;
- cancellation semantics;
- retry policy interfaces.

State-machine unit tests прежде SQL.

No arbitrary payload/function contract.

---

# Patch J2 — Database migration

Create:

```text
jobs
job_attempts
job_items
job_events
outbox
```

Indexes for:

- owner/state;
- next_attempt_at;
- lease expiry;
- job item job/state/index;
- outbox state/available_at/lease;
- retention/reconciler.

Constraints:

- unique public IDs;
- unique `(job_id,item_index)`;
- attempt number uniqueness per Job;
- bounded JSON schemas validated application side.

Migration/reversal/empty DB tests.

---

# Patch J3 — Repository/CAS lifecycle

Implement repositories and UnitOfWork operations:

- create Job+Items+Outbox atomically;
- state transition CAS;
- attempt claim;
- lease renewal;
- item claim/terminal;
- cancellation intent;
- retry schedule;
- progress coalescing;
- terminal result;
- event append bounded;
- retention queries.

Race tests directly at DB layer.

---

# Patch J4 — Outbox publisher with fake queue

Before Redis/arq implement `JobQueue` fake and real OutboxPublisher algorithm:

- bounded claim batch;
- publisher lease;
- no DB transaction during queue I/O;
- publish;
- CAS published/Job queued;
- failure/backoff;
- crash between publish and DB acknowledgement.

Multiple publishers integration test.

**Gate:** committed Job always eventually deliverable with healthy fake queue.

---

# Patch J5 — ArqJobQueue adapter

Implement ADR-0017:

- small JSON-safe payload;
- fixed internal dispatcher function;
- deterministic `_job_id` optimization;
- normalize Redis/arq errors;
- no input/content data duplication in Redis;
- queue message version validation.

Test duplicate enqueue and Redis outage.

---

# Patch J6 — Synthetic Job Worker/claim runner

Create `entrypoints/job_worker.py`.

Worker runtime:

- arq consumer;
- worker identity/generation;
- DB pool;
- ContentStore as needed later;
- JobRunner;
- background outbox publisher/reconciler loops (or clearly separated tasks in same runtime);
- graceful shutdown.

First handler `test.synthetic` internal-only.

Prove:

```text
queue message
→ DB claim
→ Attempt
→ synthetic execution
→ terminal Job
```

Duplicate message → no duplicate execution.

---

# Patch J7 — Attempt lease/fencing

Implement independent heartbeat task while handler runs.

- lease renew CAS;
- lost attempt detection;
- stale worker terminal update rejected;
- worker restart generation;
- retry_wait scheduling.

Fault injection kills worker at multiple points.

**Gate:** no permanent `running` after lease/reconciler window.

---

# Patch J8 — Cancellation foundation

Implement durable cancellation intent and runner context.

Synthetic handler checkpoints cancellation.

Test:

- before publish;
- queued;
- running;
- retry_wait;
- terminal cancel idempotency;
- worker lost during cancelling.

Job not `cancelled` until active attempt is gone.

---

# Patch J9 — JobItem checkpoint framework

Implement ADR-0018:

- ordered items;
- bounded item claim batches;
- current-attempt ownership;
- terminal checkpoint;
- item retry_wait;
- lost attempt running-item recovery;
- aggregate progress.

Synthetic batch handler proves worker crash resumes remaining only.

---

# Patch J10 — Result manifest finalizer

Implement common batch finalization:

```text
all items terminal
→ build bounded structured manifest stream
→ ContentApplication ingest
→ manifest available
→ Job terminal aggregate/result_content_id
```

Crash/fault tests:

- before manifest create;
- during Content staging;
- after Content available before Job terminal;
- retry finalization without re-running items.

---

# Patch J11 — `retrieval_batch` handler

Register typed job type.

Creation validates:

- URLs;
- owner/scope;
- item count;
- aggregate budgets;
- common retrieval profile.

Handler reuses existing Retrieval/Content application services/ports, not HTTP library directly.

Bounded item concurrency 8 baseline.

Tests:

- per-host/global retrieval limits still apply;
- partial 404/invalid/upstream failures;
- worker crash checkpoint;
- retryable network failure;
- total byte budget exhaustion.

---

# Patch J12 — `content_parse_batch` handler

Register typed job type.

Creation validates all ContentRefs owner/policy.

Handler:

- checks compatible existing representation;
- invokes normal Content parse service;
- bounded isolated parser capacity;
- checkpoints result.

Tests malformed/unsupported/permanent vs retryable infra failure.

---

# Patch J13 — Progress/events/retry polish

Implement client-visible bounded event model:

- created;
- queued;
- attempt started/lost/retried;
- progress coalesced;
- cancellation requested;
- terminal.

Progress update throttle configurable (time/item delta), avoiding row-per-item storm while final item states remain durable.

---

# Patch J14 — Reconciler completeness

Reconcile:

- expired publisher lease;
- stale created no usable outbox;
- expired attempt leases;
- retry_wait due;
- cancelling with lost worker;
- manifest finalization pending;
- terminal expiry;
- stale running JobItems.

Run multiple reconciler replicas concurrently.

---

# Patch J15 — Admission/backpressure

Add policy limits:

- pending Jobs/principal;
- global pending Jobs;
- items/job;
- aggregate byte budgets;
- outbox backlog threshold;
- worker/type capacity.

Redis unavailable + backlog bounded behavior explicit.

No unbounded application in-memory queue.

---

# Patch J16 — REST facade

Add typed routes only after backend stable:

```text
POST /api/v1/jobs/retrieval-batches
POST /api/v1/jobs/content-parse-batches
GET /api/v1/jobs/{id}
POST /api/v1/jobs/{id}/cancel
GET /api/v1/jobs/{id}/events
```

Owner/scopes, cursor/event bounds, OpenAPI tests.

No arq/internal details.

---

# Patch J17 — MCP direct/durable evolution

Modify existing `web_fetch` and `content_parse` with explicit discriminated execution mode.

Required actual schema:

```text
direct vs durable
cross-field list limits
result-kind discrimination
```

Add:

```text
job_get
job_cancel
```

Russian descriptions explain:

- durable survives current MCP connection;
- returns JobRef;
- caller checks with `job_get`;
- cancellation is not instant guarantee.

Schema tests use actual FastMCP client.

---

# Patch J18 — Queue/DB fault roast

Automate:

- Redis stop/start;
- publisher kill;
- publish-ack crash;
- Job Worker SIGKILL;
- Postgres transient disconnect;
- multiple workers duplicate delivery;
- stale attempt late completion;
- reconnect/retry loops.

No Job loss/infinite running.

---

# Patch J19 — Large batch/load/soak

Test at ceilings and realistic profiles:

- 256 MCP items;
- 1000 REST items;
- many simultaneous Jobs;
- worker scaling;
- outbox backlog;
- DB lock contention;
- progress/event write volume;
- result manifest sizes;
- ContentStore pressure.

Measure p50/p95/p99 queue wait/job duration where meaningful.

---

# Patch J20 — Security/ownership audit

- cross-principal Job get/cancel denied;
- input ContentRefs cross-owner denied;
- no queue arbitrary function/pickle;
- Redis payload has no secrets/raw giant data;
- worker credentials scoped;
- result Content owner correct;
- error/events do not leak other principal data.

---

# Patch J21 — Documentation/acceptance closure

1. actual SQL/migrations match version docs;
2. actual arq version locked;
3. current Job types exactly match registry/docs;
4. actual REST/OpenAPI reviewed;
5. actual MCP schemas reviewed;
6. fault matrix evidence recorded;
7. no crawl/generic task code slipped in;
8. `current.md` status updated;
9. release gates green.

---

# Forbidden shortcuts

Implementation must not:

- create DB Job then directly enqueue Redis without outbox;
- trust deterministic arq `_job_id` as sole exactly-once guarantee;
- execute queue message without DB claim;
- put full batch payload or result in Redis;
- restart entire batch after worker crash when item checkpoints exist;
- let stale attempt write terminal state;
- mark cancellation complete while active worker still runs;
- store fake progress percentages;
- expose arbitrary arq function names/job payload to REST/MCP;
- add `web_fetch_job` duplicate-intent MCP tool;
- auto-switch direct request to durable mode;
- implement crawl as recursive retrieval loop inside generic job.

---

# Final acceptance

v0.6 complete only after Definition of Done from README plus Jobs race/fault/load/recovery gates.
