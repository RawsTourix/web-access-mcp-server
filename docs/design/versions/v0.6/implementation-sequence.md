# v0.6 — Implementation sequence

## Назначение

Обязательный порядок реализации Durable Jobs Runtime.

> Сначала доказать durable DB/outbox/claim/fencing на synthetic handler. Затем подключить Retrieval/Content typed workloads. REST/MCP — только после backend correctness.

---

# J0 — Preconditions

- v0.1/v0.3 persistence/content tests зелёные;
- v0.5 gates зелёные при последовательном roadmap;
- Redis/PostgreSQL fault injection готова;
- actual REST/MCP baseline fixtures сохранены;
- `arq` dependency выбирается/pin-ится через `uv.lock` после compatibility test.

No public Jobs surface.

---

# J1 — Domain/application Job model

Implement:

```text
Job / JobAttempt / JobItem
state machines
JobTypeDescriptor registry
retry/cancellation/progress/result contracts
```

No arbitrary task payload/function name.

Unit state tests first.

---

# J2 — Database migration

Create:

```text
jobs
job_attempts
job_items
job_events
outbox
```

Indexes/constraints for owner/state/retry/lease/outbox/retention and unique `(job_id,item_index)`.

Migration tests.

---

# J3 — Repository/CAS lifecycle

Implement transactionally:

- create Job + ordered Items + Outbox;
- lifecycle CAS;
- Attempt claim/lease;
- Item claim/result;
- cancellation intent;
- retry schedule;
- progress summary/event;
- terminal manifest coordinates.

Race tests directly at repository layer.

---

# J4 — Outbox Publisher + fake queue

Before Redis:

- bounded row claim;
- publisher lease;
- no open DB transaction during queue I/O;
- publish;
- CAS published/Job queued;
- failure/backoff;
- crash after publish before ack.

Multiple publisher test.

---

# J5 — ArqJobQueue

Implement ADR-0017:

- lightweight versioned job ID message;
- fixed dispatcher function;
- deterministic `_job_id` optimization;
- no full input/result in Redis;
- normalize queue errors.

Redis outage/duplicate tests.

---

# J6 — Synthetic Job Worker

Create `entrypoints/job_worker.py` with:

- arq consumer;
- worker identity/generation;
- JobRunner;
- OutboxPublisher/reconciler background tasks;
- graceful shutdown.

Internal synthetic handler proves:

```text
message → DB claim → Attempt → execution → terminal Job
```

Duplicate message no duplicate body.

---

# J7 — Lease/fencing/retry

Independent attempt heartbeat.

Implement:

- lost Attempt detection;
- stale write rejection;
- worker restart generation;
- retry_wait + `next_attempt_at`;
- due retry outbox wake-up.

Kill worker at multiple phases.

---

# J8 — Cancellation

Durable cancellation intent + execution cancellation context.

Test created/queued/running/retry_wait/terminal/lost-worker cases.

Do not mark cancelled while body still active.

---

# J9 — JobItem checkpoint engine

Implement ADR-0018:

- ordered items;
- bounded item claims;
- current Attempt ownership;
- terminal checkpoints;
- item retry_wait;
- lost-attempt running item recovery;
- aggregate progress.

Synthetic batch crash after N items must resume remaining only.

---

# J10 — Result manifest finalization

```text
all items terminal / cancellation finalization
→ build structured manifest
→ ContentApplication ingest/finalize
→ Job terminal + result_content_id
```

Crash during manifest creation must not rerun successful items.

---

# J11 — `retrieval_batch`

Register typed handler reusing normal Retrieval/Content application path.

Limits/budgets from v0.6 README.

Test:

- per-host/global limits still apply;
- partial item failures;
- retryable network failures;
- byte budget exhaustion;
- worker crash checkpoint.

---

# J12 — `content_parse_batch`

Register typed handler reusing ContentApplication/registry.

- owner check;
- representation reuse;
- isolated parser global capacity;
- permanent vs retryable errors.

No L2.

---

# J13 — Progress/events

Bounded/coalesced durable events:

```text
created
queued
attempt_started/lost/retry
progress
cancellation_requested
terminal
```

No row-per-network-chunk.

---

# J14 — Reconciler completeness

Handle:

- outbox lease expiry;
- stale created no outbox;
- expired Attempt lease;
- retry_wait due;
- stale running JobItems;
- cancelling with lost worker;
- manifest-finalization pending;
- retention expiry.

Multiple reconciler replicas safe.

---

# J15 — Admission/backpressure

Add bounded:

- pending Jobs/principal;
- global backlog;
- items/job;
- aggregate bytes;
- worker/type concurrency;
- outbox backlog admission threshold.

No application-memory backlog.

v0.7 later turns these into dynamic policy/accounting.

---

# J16 — REST facade

Typed endpoints:

```text
POST /api/v1/jobs/retrieval-batches
POST /api/v1/jobs/content-parse-batches
GET /api/v1/jobs/{id}
POST /api/v1/jobs/{id}/cancel
GET /api/v1/jobs/{id}/events
```

Owner/auth, OpenAPI tests, no arq internals.

---

# J17 — MCP Job creation tools

Per ADR-0021 add:

```text
web_fetch_job
content_parse_job
job_get
job_cancel
```

Keep existing direct:

```text
web_fetch
content_parse
```

unchanged as request-bound tools; **no `execution` discriminator**.

Schema requirements:

```text
web_fetch_job urls 1..256
content_parse_job content_ids 1..256
job_get/job_cancel job_ids[] bounded
```

Russian descriptions must clearly communicate:

- `*_job` creates durable Job Resource;
- returns JobRef immediately;
- survives MCP disconnect;
- use `job_get` for result;
- uncertain create response must not be blindly retried.

Actual FastMCP schema/annotation tests required.

---

# J18 — Hints/direct overflow

Direct `web_fetch`/`content_parse` validation or request-bound limit condition may return structured:

```text
processing_requires_job
related_tool = web_fetch_job | content_parse_job
```

No automatic invocation/promotion.

---

# J19 — Queue/DB fault roast

Automate:

- Redis stop/start;
- publisher kill;
- publish success/DB ack crash;
- Job Worker SIGKILL;
- DB transient failure;
- duplicate delivery;
- stale attempt late completion;
- multi-replica reconcilers.

No lost/infinite-running Jobs.

---

# J20 — Large batch/load/soak

- MCP 256-item jobs;
- REST 1000-item jobs;
- concurrent principals;
- many workers;
- outbox backlog;
- DB contention;
- progress write amplification;
- ContentStore pressure;
- repeated worker kill/recovery.

---

# J21 — Security/ownership

Verify:

- cross-owner get/cancel denied;
- cross-owner input ContentRef denied;
- no arbitrary Python/arq function input;
- queue payload no secrets/giant content/no pickle;
- result Content owner correct;
- error/events don't leak other principal.

---

# J22 — Documentation/acceptance closure

- actual migrations match design;
- arq version locked;
- Job registry only typed supported workloads;
- actual OpenAPI reviewed;
- actual MCP catalog includes ADR-0021 tools;
- old mixed direct/durable schema absent;
- fault evidence recorded;
- `current.md` updated;
- gates green.

---

# Forbidden shortcuts

Do not:

- DB commit then direct Redis enqueue without outbox;
- treat `_job_id` as exactly-once guarantee;
- execute queue message without DB claim;
- put full payload/result in Redis;
- rerun succeeded items after worker crash;
- allow stale Attempt terminal write;
- fake cancellation/progress;
- expose generic queue function to clients;
- use `execution=direct|durable` in existing MCP tools;
- automatically convert direct request to Job;
- implement crawl as recursive generic batch loop.

---

# Final acceptance

v0.6 completes only after README Definition of Done plus outbox/lease/checkpoint/cancellation/load/MCP schema gates.
