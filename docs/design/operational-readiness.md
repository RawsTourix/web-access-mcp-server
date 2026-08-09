# Operational readiness design

## Статус документа

Канонический владелец production-readiness требований Web Access MCP: rollout, backup/restore, disaster recovery, capacity/backpressure, supply-chain, runbooks и long-running reliability.

Не заменяет component-specific lifecycle/security docs.

---

# 1. Purpose

Production-ready означает не только «все unit tests зелёные».

Сервис должен доказуемо:

- запускаться воспроизводимо;
- обновляться без corruption/lost durable state;
- восстанавливаться после process/infrastructure failures;
- ограничивать overload;
- не накапливать browser/parser/temp/blob leaks;
- восстанавливать PostgreSQL/ContentStore из backup;
- переживать потерю Redis без потери authoritative data;
- иметь понятные alerts/runbooks;
- иметь pinned/scanned supply chain.

---

# 2. Failure-domain model

Основные failure domains:

```text
Control Plane replica
Browser Worker / session subprocess
Job Worker
PostgreSQL
Redis
ContentStore
SearXNG
billable search provider
Browser Egress Gateway
external Internet target
```

Каждый имеет:

- expected effect;
- readiness/degraded status;
- automatic recovery boundary;
- operator action/runbook;
- durability implication.

---

# 3. Durable sources of truth

Durable recovery baseline:

```text
PostgreSQL
+
ContentStore
```

Redis не является backup-required authoritative store baseline.

Redis loss may lose:

- cache;
- token bucket transient state;
- route registry;
- queue wake-ups.

Correctness recovers from PostgreSQL/resources/reconcilers:

- outbox republishes Jobs;
- Browser live sessions may be lost, but durable metadata becomes correct;
- worker registry rebuilds;
- cache refills.

---

# 4. PostgreSQL backup/restore

Production deployment must document/test:

- automated backups;
- retention;
- encryption/access;
- restore into isolated environment;
- schema migration compatibility;
- integrity checks;
- RPO/RTO chosen by operator profile.

Project does not claim universal RPO/RTO number; reference deployment records measured restore evidence.

---

# 5. ContentStore backup/restore

For filesystem production-like profile:

- backup strategy explicit;
- atomic snapshot/filesystem consistency considerations;
- restore verification against DB metadata/hash.

For S3-compatible profile:

- provider versioning/replication/backup policy documented;
- object encryption;
- lifecycle policies reviewed;
- restore/access verification.

DB restore and ContentStore restore must be treated as a related consistency set.

---

# 6. Restore reconciliation

After restore:

```text
DB + ContentStore
→ migration to target version if needed
→ Content reconciliation
→ Job/outbox reconciliation
→ Usage reconciliation
→ worker registries rebuilt
→ readiness only after required checks
```

Stale BrowserSessions from backup cannot resurrect live browser processes; non-terminal stale sessions become lost/expired through reconciliation.

---

# 7. Redis disaster recovery

Redis can be recreated empty.

Recovery flow:

- service reconnects;
- Search cache empty;
- rate/concurrency ephemeral state resets according safe policy;
- Browser worker registry repopulates heartbeats;
- Job outbox/reconciler republishes eligible Jobs;
- no durable quota/billable usage reset because it lives PostgreSQL.

Tests explicitly destroy Redis data, not only restart process.

---

# 8. Database migrations

Migration policy:

- Alembic single head;
- migration command separate from API startup;
- expand-first for rolling releases;
- destructive contract changes only after compatibility window;
- migration tested from latest supported previous release database;
- backup/rollback plan before destructive data migration;
- no hidden `create_all()` production schema management.

---

# 9. Rollback

Application rollback is supported only when DB/policy/contracts remain compatible with older version.

Release notes identify:

```text
rollback-safe
rollback-requires-db-restore
forward-fix-only
```

Do not promise binary rollback across irreversible migration without evidence.

---

# 10. Graceful shutdown

Control Plane:

- stop admission;
- bounded in-flight request handling;
- close pools/clients;
- no new long operations after shutdown starts.

Job Worker:

- stop claims;
- cooperate/current Attempt or allow lease recovery;
- no fake terminal state.

Browser Worker:

- drain sessions;
- terminate/kill remaining child trees by deadline;
- no orphan Chromium.

---

# 11. Rolling deployment

Order chosen based on compatibility matrix, typically:

```text
expand migration
→ deploy compatible Control Plane/Workers
→ switch policy/schema features
→ contract freeze verification
→ cleanup migration later
```

Mixed-version window has automated tests.

Browser Worker/Job Worker runtime revisions advertised and checked.

---

# 12. Capacity model

Capacity is explicit by subsystem:

```text
Control Plane request concurrency
Retrieval global/per-host concurrency
Search provider capacity
isolated parser concurrency
S3 executor concurrency
Browser sessions/worker
Job attempts/worker/type/principal
PostgreSQL pool/locks
Redis connections/throughput
```

No single global `max_concurrency` pretending to cover all resources.

---

# 13. Backpressure

At saturation system rejects/defer work *before* OOM/thread/process explosion.

Mechanisms:

- bounded semaphores;
- queue/backlog quotas;
- Browser worker capacity;
- parser process capacity;
- S3 executor queue;
- request/body/byte limits;
- Job admission;
- per-principal quotas.

Errors indicate rate/capacity/backlog category, not timeout after minutes of hidden waiting.

---

# 14. Capacity evidence

Reference hardware/profile records measured:

- max stable Browser sessions/worker;
- RAM/session;
- parser concurrency/RAM;
- Retrieval throughput;
- Search throughput/provider limits;
- Job throughput/backlog recovery;
- S3/filesystem throughput;
- DB lock/pool saturation.

Defaults can change only with measurements/tests.

---

# 15. Performance objectives vs external SLA

Project may define internal release performance budgets, but these are **not universal public SLA** because upstream Internet/providers dominate latency.

Measure separately:

- service overhead;
- queue wait;
- upstream latency;
- parser/browser startup/action;
- storage I/O.

Do not hide slow upstream behind service latency aggregate only.

---

# 16. Long-running soak

Required soak profiles:

- Control Plane repeated mixed requests;
- Browser create/use/close thousands cycles;
- forced Browser child kills;
- parser subprocess churn;
- Job worker kill/retry loops;
- Content create/expire/GC;
- Redis restart/loss;
- policy updates;
- S3 transfers.

Observe:

- RSS/fd/thread/process count;
- temp/storage growth;
- DB connections/locks;
- Redis connections;
- orphan resources;
- latency drift.

---

# 17. Chaos/fault injection

Automated controlled failures at documented commit points:

- DB transaction before/after commit;
- Content staging/finalize windows;
- Redis enqueue/ack;
- Browser action response loss;
- worker heartbeat partition;
- S3 copy/finalize;
- policy refresh;
- egress gateway failure.

Every crash window has expected recovered state.

---

# 18. Dependency reproducibility

- `uv.lock` committed;
- container base/images pinned by stable tag/digest policy;
- Playwright browser/image compatibility pinned;
- SearXNG/proxy/PostgreSQL/Redis reference images versioned;
- no `latest` production image tags;
- build records source commit/version.

---

# 19. Vulnerability/supply-chain scanning

CI/release includes:

- Python dependency vulnerability scan;
- container image vulnerability scan;
- secret scan;
- dependency license review for newly introduced core libraries;
- optional SBOM generation;
- Dockerfile/container lint/security checks.

Finding severity policy documented; critical exploitable findings block release unless explicit security exception is documented.

---

# 20. Container hardening

Reference production containers:

- non-root where component permits;
- minimal capabilities;
- read-only filesystem where compatible, explicit writable temp/content paths;
- no Docker socket;
- no host network;
- no unnecessary package managers/tools runtime image;
- init/subreaper for Browser worker;
- resource limits;
- health checks;
- secrets mounted/provided safely.

Browser Chromium sandbox must not be disabled merely to make container easier to run.

---

# 21. Secret rotation

Runbook covers rotation for:

- external service principals/bearer secrets;
- Yandex/provider API credentials;
- DB/Redis/S3 credentials where static;
- internal Browser Worker credentials.

Auth baseline supports overlap where needed.

No restart strategy may require logging secret value.

---

# 22. Security regression suite

Release includes:

- Retrieval SSRF/DNS rebinding;
- Browser egress/private network;
- package/parser bombs;
- path traversal;
- auth/owner isolation;
- policy/admin authorization;
- secret redaction;
- Browser action unknown/retry;
- Content upload/download headers;
- CORS/auth boundary;
- malformed IPC/queue payload.

---

# 23. Data integrity audit

Maintenance checker can verify bounded samples/batches:

- available ContentObject storage exists;
- hash/size where feasible;
- representation provenance refs valid;
- terminal Job result ref exists;
- usage counters reconcile;
- no impossible BrowserSession active on dead generation;
- outbox/Job state consistency.

Not a giant synchronous admin request; maintenance operation bounded/job-like internally.

---

# 24. Runbooks

Production docs include concise runbooks:

```text
service won't become ready
PostgreSQL unavailable
Redis lost/restarted
SearXNG unavailable
Yandex disabled/budget exhausted
Browser workers unavailable
Browser egress gateway unavailable
Job backlog growing
ContentStore unavailable/corrupt/missing object
policy revision incompatible/stale
rolling deploy
restore from backup
secret rotation
```

Runbook states what **not** to do if action risks corruption.

---

# 25. Alert principles

Alert on actionable symptoms:

- sustained readiness/capability outage;
- oldest outbox/job backlog age;
- repeated lost Browser/Job workers;
- Content reconciliation corruption;
- policy stale/incompatible;
- billable budget unexpected consumption;
- storage/database saturation;
- leak/zombie/temp growth;
- security deny anomalies.

Avoid alert-per-single transient upstream 5xx.

---

# 26. Log/trace retention

Operational log/trace retention is deployment policy, separate from Content/Job resource retention.

Sensitive web content not logged by default.

Audit retention separate and stricter where needed.

---

# 27. Production smoke

After deployment:

- liveness/readiness;
- DB/Redis/ContentStore;
- local SearXNG controlled query where safe;
- safe Retrieval controlled URL;
- parser fixture;
- Browser controlled test page via egress proxy;
- Job synthetic/controlled typed job;
- MCP discovery/schema fingerprint;
- REST contract version.

Do not use billable provider automatically for smoke unless explicitly enabled/budgeted.

---

# 28. Release evidence

Each production candidate records:

- commit/tag;
- lock hash;
- contract manifest hash;
- migration head;
- test/gate results;
- security scan result;
- load/soak profile;
- backup/restore evidence date/profile;
- known limitations/exceptions.

---

# 29. Non-goals

- universal cloud orchestrator manifests for every platform;
- external SLA numbers valid on arbitrary hardware;
- fully automated disaster recovery across all operators;
- replacing operator backup systems;
- hiding provider outages from clients.
