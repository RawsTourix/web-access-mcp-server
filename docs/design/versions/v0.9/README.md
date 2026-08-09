# v0.9 — Production Hardening

## Статус

`ready for implementation`

v0.9 не добавляет новую пользовательскую capability. Версия превращает уже реализованный Web Access в доказуемо production-ready release candidate перед `v1.0`.

Канонический владелец требований: `../../operational-readiness.md`.

---

# 1. Цель

После v0.9 система должна иметь не только корректную архитектуру, но и **измеренное/проверенное operational behavior** при:

- длительной нагрузке;
- saturation/backpressure;
- process/container failures;
- Redis loss;
- PostgreSQL interruptions/restore;
- ContentStore failures/restore;
- Browser/Job worker crashes;
- rolling deployments;
- dependency/security regressions;
- secret rotation;
- backup/restore drills.

v0.9 является release-candidate hardening line. Public REST/MCP contract из v0.8 меняется только при обнаружении реального pre-v1 defect через явный compatibility review.

---

# 2. Prerequisites

Обязательны завершённые v0.1–v0.8 и документы:

- `../../operational-readiness.md`;
- `../../deployment.md`;
- `../../testing.md`;
- `../../release-gates.md`;
- `../../security.md`;
- `../../observability.md`;
- `../../compatibility.md`;
- `../../policy-and-operations.md`;
- actual v0.8 contract fixtures.

---

# 3. Explicit non-goals

v0.9 не должна «заодно» добавлять:

- новый MCP tool;
- новый REST capability;
- новый search provider;
- crawl;
- OCR/VLM/transcription;
- persistent Browser profiles;
- account/auth product;
- shared Chromium pool optimization без измерений;
- новый Job orchestration model;
- другую очередь/БД/cache только ради benchmark novelty.

Если hardening выявил архитектурный defect, он исправляется минимальным design/ADR patch, а не feature expansion.

---

# 4. Release candidate profiles

Нужно иметь минимум два воспроизводимых профиля.

## Local integration

```text
Control Plane
PostgreSQL
Redis
SearXNG
filesystem ContentStore
Browser Worker + egress gateway
Job Worker
```

Поднимается одной Compose-командой для разработки/CI integration.

## Production-like

```text
Control Plane replicas >= 2
PostgreSQL
Redis
SearXNG
S3-compatible ContentStore
Browser Workers >= 2
Browser Egress Gateway
Job Workers >= 2
policy/audit/quota enabled
```

Может быть Compose/controlled environment для project acceptance; exact production orchestrator vendor не является contract.

---

# 5. Reproducible dependencies/images

Release candidate обязан иметь:

- committed `uv.lock`;
- no production `latest` tags;
- version/digest policy для PostgreSQL/Redis/SearXNG/browser egress/object storage/base images;
- pinned Playwright↔Chromium-compatible image/dependency;
- build metadata с source commit/version;
- deterministic container build настолько, насколько practically achievable.

Dependency update не объединяется с unrelated hardening fix без необходимости.

---

# 6. Migration hardening

Test matrix:

```text
empty DB → latest
v0.8 DB → v0.9 DB
latest migration head uniqueness
mixed-version rolling overlap
migration interrupted/failure path where testable
```

Rules:

- no production `create_all()`;
- expand-first;
- destructive cleanup only after compatibility window;
- migration command separate from API startup;
- DB backup required before irreversible migration.

---

# 7. PostgreSQL backup/restore drill

Reference production-like environment performs real drill:

1. create representative Search/Content/Browser terminal/Job/policy/audit data;
2. take backup;
3. mutate/add later state;
4. restore backup into isolated target;
5. start target software according supported migration path;
6. run post-restore reconciliation;
7. verify resource integrity/expected RPO boundary;
8. record measured restore duration/evidence.

No claim that backup works merely because backup command exits 0.

---

# 8. ContentStore backup/restore/integrity

Filesystem/S3 profile as applicable.

Verify after restore:

- available ContentObject bytes exist;
- sampled/full bounded SHA-256/size matches metadata;
- derived representation provenance refs valid;
- Job result manifests readable;
- missing/corrupt object produces explicit state/diagnostic, not silent success.

S3-compatible production-like profile must pass.

---

# 9. Restore reconciliation

After DB/Content restore:

```text
stale BrowserSession non-terminal
→ lost/expired reconciliation

Job/outbox
→ recover eligible durable execution

PrincipalUsage
→ reconcile

Redis registry/cache
→ rebuild
```

No backed-up `ready` BrowserSession may pretend its old Chromium is still alive.

---

# 10. Redis destructive recovery

Test **flush/recreate**, not only restart.

Expected:

- Search cache lost harmlessly;
- transient rate/concurrency state safely resets according policy;
- Browser worker registry rebuilds heartbeat;
- Job outbox/reconciler republishes eligible wake-ups;
- durable quota/billable accounting unchanged;
- no Job/Content loss.

Document recovery time and degraded states.

---

# 11. Browser soak

Required long soak/roast includes:

- thousands create/close sessions;
- navigation/snapshot/action loops;
- popups/dialogs;
- downloads/screenshots/content handoff;
- forced session subprocess kill;
- Chromium crash;
- Browser Worker restart/drain;
- egress gateway outage/recovery;
- response loss after mutating action.

Monitor:

```text
Python child count
Chromium process count
zombies/orphans
RSS/fd count
temp dirs/bytes
ElementHandle/snapshot retention
session close latency
unknown outcome count
```

Acceptance: no monotonic unexplained process/temp/resource growth after cleanup windows.

---

# 12. Job soak/fault

Run sustained:

- many retrieval/content Jobs;
- worker SIGKILL/restart;
- duplicate queue delivery;
- Redis interruptions;
- publisher/reconciler restarts;
- retry/cancellation;
- result manifest finalization;
- hot-principal fairness.

Verify:

- no permanent running Jobs;
- no duplicate successful item execution beyond permitted failed/retry observation;
- attempt fencing;
- bounded progress/event writes;
- backlog recovery after worker scale restoration.

---

# 13. Parser/content fuzz and soak

Corpus includes:

- malformed/truncated HTML/XML/JSON/PDF;
- package bombs/traversal;
- malformed OOXML/ODF/EPUB;
- huge spreadsheet repetitions;
- image decompression bombs;
- parser hangs/crashes;
- Unicode/encoding edge cases;
- Content staging/finalization failure injection.

Expected:

- Control Plane survives parser crash;
- isolated child reaped;
- limits enforced during processing;
- no temp/blob leak after reconciliation;
- no L2 fallback.

---

# 14. Search/Retrieval load

Measure separately:

- SearXNG throughput;
- Web Access service overhead;
- Redis cache hit/miss;
- provider limiter behavior;
- Retrieval concurrent/per-host behavior;
- body/decompression limit behavior;
- slow upstream saturation;
- billable provider admission in controlled mocked/non-billable tests by default.

No accidental live paid-provider load test.

---

# 15. Capacity profile evidence

Produce versioned operational report with at least:

```text
Control Plane request concurrency
Retrieval stable concurrency/throughput
isolated parser concurrency/RAM
Browser launch latency/RAM per session/max stable sessions worker
Job worker throughput/backlog recovery
S3/filesystem throughput
DB connection/lock profile
Redis connection/throughput profile
```

Defaults changed only if measured evidence supports it.

---

# 16. Backpressure acceptance

At saturation:

- Browser create rejects before OOM;
- parser admission bounded;
- S3 executor queue bounded;
- Job backlog admission bounded;
- Retrieval semaphores bounded;
- DB/Redis pools bounded;
- request bodies/results bounded.

Caller receives normalized rate/capacity/backlog result rather than hidden unbounded wait.

---

# 17. Multi-replica race roast

Randomized/concurrent scenarios:

- last Browser quota slot;
- Job quota/attempt fairness;
- Content finalize/expire/GC;
- policy update/refresh;
- billable reservation;
- outbox publishers;
- reconcilers;
- worker generation restart;
- Browser create/close/expiry.

Run repeated seeds and retain failed seed/repro data.

One green rerun does not erase detected race.

---

# 18. Rolling deploy drill

Test version-compatible mixed deployment:

1. expand DB migration;
2. old/new Control Plane overlap;
3. old/new Browser/Job worker revisions according compatibility;
4. policy schema remains compatible;
5. drain old workers;
6. complete rollout;
7. verify contract fingerprint unchanged unless intended.

Failure halfway must have documented resume/rollback/forward-fix action.

---

# 19. Rollback classification

Each release candidate documents:

```text
rollback-safe
forward-fix-only
restore-required for particular irreversible migration
```

Perform at least one safe binary rollback drill in production-like environment.

No generic «можно откатить Docker tag» claim without DB compatibility proof.

---

# 20. Secret rotation drill

Verify rotation with overlap/restart behavior for at least:

- external service principal Bearer;
- internal Browser Worker credential;
- provider API secret in controlled fake/test configuration;
- S3/static credential profile where used.

No secret appears in logs/contract fixtures/audit.

---

# 21. Security regression matrix

Required automated/controlled:

- Retrieval SSRF;
- DNS rebinding/mixed IP;
- redirect to private;
- Browser private network/metadata egress;
- browser proxy bypass attempts;
- malicious package/parser input;
- auth/owner cross-principal;
- admin scope;
- policy scope escalation attempt;
- queue/IPC malformed payload;
- path traversal/upload;
- Content headers/download safety;
- secret redaction.

---

# 22. Supply-chain gates

Release candidate records:

- Python dependency vulnerability scan;
- container image vulnerability scan;
- secret scan;
- license review for core dependencies;
- SBOM generation if tooling selected;
- Dockerfile/container best-practice/security scan.

Critical exploitable issue blocks release unless explicit documented exception with scope/mitigation/expiry.

---

# 23. Observability hardening

Validate dashboards/queries/alerts from real failure injection:

- capability readiness;
- provider outage;
- Redis loss;
- Job backlog/outbox age;
- lost workers;
- Browser forced kills;
- parser failures;
- Content reconciliation errors;
- policy stale;
- storage/DB saturation;
- billable budget utilization.

Metric labels remain bounded; no URLs/principal IDs/content text as high-cardinality labels.

---

# 24. Alert quality

Alerts must be actionable and sustained where appropriate.

Test that a single transient public-site 500 does not page operator, while:

- sustained no Browser workers;
- oldest outbox age breach;
- Content corruption;
- stale policy beyond grace;
- DB/ContentStore outage

does.

---

# 25. Runbooks

Create/update runbooks for every operational-readiness failure listed in canonical doc.

Each runbook contains:

```text
symptoms
how to confirm
safe actions
unsafe actions / do not do
recovery verification
escalation/evidence to collect
```

Runbooks are tested during drills, not only written.

---

# 26. Production smoke suite

Automated post-deploy smoke with controlled resources:

- live/ready/status;
- DB/Redis/ContentStore;
- SearXNG controlled search;
- safe Retrieval fixture;
- Content parser fixture;
- Browser controlled page through egress;
- durable typed Job;
- MCP discovery/fingerprint;
- REST manifest/version.

Paid provider excluded unless explicitly configured/budgeted.

---

# 27. Contract freeze preservation

v0.9 CI regenerates v0.8 contract fixtures.

Any diff is release blocker until classified.

Hardening fix requiring breaking pre-v1 contract change must:

- have explicit ADR/change note;
- update own-agent integration;
- update fixtures;
- explain why defect cannot be corrected compatibly.

No incidental schema drift.

---

# 28. Release evidence report

Generate/store release-candidate evidence containing:

```text
commit/tag candidate
uv.lock hash
container image refs/digests
contract manifest hash
Alembic head
gate/test results
fault/race/soak/load summary
security scan summary
backup/restore drill evidence
known limitations/exceptions
```

No secrets/raw web content in report.

---

# 29. Known limitations register

Before v1.0 explicitly document accepted limitations, for example:

- L2 processing absent;
- Browser sessions ephemeral/no migration;
- no CAPTCHA/stealth guarantee;
- direct format support bounded registry;
- external website/provider latency/availability not guaranteed;
- exact supported media/document family matrix.

Limitation is not hidden failure.

---

# 30. Definition of Done

v0.9 complete only if:

1. Full applicable G0–G21 release gates green.
2. Backup/restore drill succeeded with integrity verification.
3. Redis destructive recovery succeeded.
4. Rolling deploy + at least one safe rollback drill succeeded.
5. Browser/Job/Parser/Content soak found no unresolved leak/race blocker.
6. Capacity/backpressure defaults have measured evidence.
7. Security/supply-chain gates have no unresolved release blocker.
8. Secret rotation tested.
9. Alerts/runbooks exercised.
10. v0.8 external contract freeze remains intentional/consistent.
11. Own-agent and generic MCP acceptance remain green.
12. Release evidence and known limitations are complete.
