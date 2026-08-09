# v0.9 — Implementation sequence

## Назначение

Порядок production hardening. Версия не считается завершённой по числу написанных тестов: каждый блок должен иметь фактическое evidence и не оставлять обнаруженные race/security/leak defects «на потом».

---

# H0 — Release-candidate baseline

- все v0.1–v0.8 gates зелёные;
- contract fixtures чистые;
- known warnings/flakes catalogued;
- production-like profile reproducible;
- hardening branch/change window не используется для feature creep.

Freeze commit/evidence baseline.

---

# H1 — Dependency/image reproducibility

- audit `uv.lock`;
- pin all reference images/version policy;
- Playwright/Chromium compatibility test;
- remove `latest`;
- record build/source metadata;
- verify clean rebuild.

---

# H2 — Migration drill

Run:

```text
empty → latest
v0.8-like DB → v0.9
mixed old/new runtime
```

Check Alembic one head, expand-first compatibility and failure handling.

Document rollback class.

---

# H3 — PostgreSQL backup/restore drill

Create representative durable state, backup, restore isolated, reconcile and verify.

Record:

- commands/profile;
- timestamps;
- size;
- restore duration;
- integrity result;
- RPO boundary observed.

---

# H4 — ContentStore restore/integrity

Filesystem/S3 production-like as applicable.

Verify sampled/controlled full corpus SHA/size/provenance/result refs.

Inject missing/corrupt blob and ensure explicit detection.

---

# H5 — Redis destructive recovery

Destroy Redis contents while durable state exists.

Prove:

- registry rebuild;
- cache harmless loss;
- outbox Job wake-up recovery;
- durable quotas unchanged;
- no hidden manual database edits required.

---

# H6 — Browser extended roast

Run dedicated long suite:

- create/close thousands;
- session child hang/kill;
- Chromium crash;
- worker crash/drain;
- proxy outage;
- response-loss after mutating action;
- popup/dialog/download/screenshot loops.

Track process tree/RSS/fd/temp/ref retention.

Any monotonic leak must be fixed or explicitly proven bounded before continuing.

---

# H7 — Jobs extended roast

- publisher kills;
- Redis failure;
- worker SIGKILL;
- stale Attempt write;
- large batch checkpoints;
- cancellation;
- backlog recovery;
- multiple workers;
- hot principal fairness.

No stuck Job beyond documented reconciliation window.

---

# H8 — Content/parser fuzz roast

Expand synthetic/malformed corpus and randomized mutations within safe testing boundaries.

Validate:

- child crashes isolated;
- timeout kills/reaps;
- package/image bombs bounded;
- no Control Plane process crash;
- no temp/staging leak;
- provenance/output deterministic where expected.

---

# H9 — Search/Retrieval stress

Controlled SearXNG/fake upstream targets:

- cache cold/hot;
- Redis limiter contention;
- per-host/global Retrieval capacity;
- slow streams;
- decompression limits;
- DNS/redirect attack fixtures;
- provider outage/recovery.

Paid live provider excluded from default load.

---

# H10 — Multi-replica race matrix

Run randomized repeated seeds for:

- Browser principal quota last slot;
- Job admission/attempt quota;
- Content finalize vs expiry/GC;
- policy revisions;
- billable usage reservation;
- outbox/reconciler;
- worker generation transitions.

Persist failing seed/reproduction details.

---

# H11 — Capacity characterization

Measure every major capacity domain.

Produce versioned `capacity-report` artifact/document with hardware/profile.

Use results to tune defaults only through explicit documented patch.

Never infer universal production capacity from one laptop/server profile.

---

# H12 — Saturation/backpressure tests

Force each bounded subsystem to ceiling:

- HTTP request concurrency;
- Retrieval;
- parser child slots;
- Browser worker slots;
- Job backlog;
- S3 executor;
- DB pool;
- Redis pool.

Expected: controlled reject/defer, no process collapse/OOM/unbounded queue.

---

# H13 — Rolling upgrade

Perform controlled old/new deployment sequence with traffic.

Verify:

- DB compatibility;
- policy revision compatibility;
- Job handler revisions;
- Browser worker revisions/drain;
- contract fingerprint;
- no lost durable state.

---

# H14 — Rollback/forward-fix drill

For a rollback-safe candidate, deploy previous compatible binary after partial/full rollout and verify.

For irreversible migration paths, verify documented forward-fix/restore procedure rather than pretending rollback works.

---

# H15 — Secret rotation

Exercise overlapping external bearer rotation and internal worker credential rotation.

Test provider/storage credential rotation in configured reference profile where feasible.

Search logs/audit/traces/contracts for secret leakage afterward.

---

# H16 — Security regression suite

Run all component security suites + deployment tests.

Include network-level Browser egress verification, Retrieval DNS/SSRF, package parsing, auth/owner, admin/policy, malformed IPC/queue and Content headers.

Release blocker severity policy applies.

---

# H17 — Supply-chain scanning

Automate/gate:

- Python dependency scan;
- container scan;
- secret scan;
- license inventory/review;
- SBOM if selected;
- Dockerfile/container lint/security.

Exceptions require explicit reason/mitigation/expiry.

---

# H18 — Observability validation by failure

Trigger real controlled failures and confirm:

- correct metrics;
- useful logs/traces;
- readiness/degraded state;
- expected alert.

Do not accept dashboards that were never exercised against failure.

---

# H19 — Runbook game days

For each critical runbook choose representative drills and follow only written steps.

If operator needs undocumented tribal knowledge, update runbook and rerun.

---

# H20 — Production smoke automation

Implement post-deploy smoke suite using controlled free/local resources.

Outputs machine-readable result and correlation IDs.

No paid provider hidden call.

---

# H21 — Contract regression

Regenerate v0.8 REST/MCP fixtures.

Any diff requires explicit classification and own-agent compatibility rerun.

No hardening patch merges accidental public schema change.

---

# H22 — Cross-repo agent/generic acceptance rerun

Run:

- own internet-search-bot builtin integration;
- generic MCP client;
- representative REST client.

Include reconnect, Browser cleanup/unknown and durable Job lifecycle.

---

# H23 — Known limitations/security exceptions review

Every known limitation/exception must have:

- current applicability;
- user/operator impact;
- mitigation;
- whether it blocks v1;
- follow-up tracking if accepted.

Delete stale exceptions instead of carrying them forever.

---

# H24 — Release evidence automation

Produce versioned evidence bundle/markdown+JSON summary from CI/manual controlled gates.

No secret/raw content.

Include commit, contract fingerprint, migration head, lock/image refs, test/load/restore/security summaries.

---

# H25 — Final v0.9 audit

Independent/adversarial review of:

- dependency rules;
- crash windows;
- race coverage;
- security boundaries;
- contract consistency;
- operational recovery;
- docs vs actual code.

No release-blocking finding open.

---

# Forbidden shortcuts

Do not:

- mark flaky race test «known» after one successful rerun;
- disable Chromium sandbox for CI/production parity convenience;
- reduce security limits solely to make fuzz pass;
- use fake backup restore evidence;
- call Redis restart test disaster recovery without deleting state;
- load test paid provider by accident;
- auto-update golden contracts;
- tune capacity without recording hardware/profile;
- accept zombie/temp leak because container restart hides it;
- add features while calling them hardening.

---

# Final acceptance

v0.9 finishes only when every Definition of Done item from README has evidence and the v1 release checklist can be executed without unresolved architecture blocker.
