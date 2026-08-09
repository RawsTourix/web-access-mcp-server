# Release Gates Web Access MCP

## Статус

Каноническая система acceptance gates.

Version считается `accepted` только после всех применимых gates + version-specific DoD. Green happy-path unit tests недостаточны.

---

# G0 — Documentation / design consistency

Required:

- code follows current Design/non-superseded ADR;
- exact public contracts match implementation scope;
- version README/sequence/current status factual;
- no unresolved implementation blocker hidden in code;
- superseded contract not implemented as alternative.

Fail if documentation and code disagree on lifecycle/security/public semantics.

---

# G1 — Dependency / architecture boundaries

Verify automatically where possible:

- domain/application do not import transport/concrete infrastructure;
- REST/MCP do not own business logic;
- REST and MCP do not call each other in baseline;
- provider/ORM/Playwright types do not leak public models;
- worker child boundaries respected.

---

# G2 — Unit/type/static quality

Required for affected code:

- unit tests;
- configured type/static checks;
- formatting/lint/import discipline;
- no unexplained warnings/errors;
- deterministic serialization/schema where required.

Exact tooling pinned by target version/project config.

---

# G3 — Public contract/schema

For affected facade:

- actual FastMCP schemas from real MCP client;
- generated FastAPI OpenAPI;
- common public serialization;
- exact required/default/bounds/enums/oneOf;
- descriptions;
- no private fields;
- positive/negative fixtures.

v0.8+ compares generated golden contract diff/compatibility.

---

# G4 — Authentication / ownership / authorization

Test:

- missing/invalid credential;
- wrong owner;
- missing task scope;
- dynamic policy restriction;
- delegated context if implemented;
- admin:read/write boundary;
- dynamic task policy cannot mint scope or self-lock admin recovery.

Opaque handle knowledge alone never grants access.

---

# G5 — Persistence / migrations / consistency

For schema/state change:

- empty DB→head migration;
- upgrade from previous accepted head;
- one Alembic head;
- constraints/indexes;
- transaction boundaries;
- no hidden commit;
- crash-window reconciliation;
- stale revision/fencing tests;
- rollback/restart semantics where designed.

---

# G6 — Security boundary

Applicable tests include:

- SSRF/private/metadata/DNS rebinding;
- redirect/TLS;
- Browser public-only egress;
- parser/session subprocess isolation;
- path/temp traversal;
- compression/package/parser bombs;
- secret redaction;
- untrusted page/content not becoming trusted hint/control;
- no raw JS/selector/HTTP/admin escape not designed.

Critical/High dependency/container findings require documented disposition according release security policy; production release cannot silently ignore them.

---

# G7 — Search provider/cost

Search release must prove:

- deterministic provider selection;
- no hidden fallback;
- cache freshness/isolation;
- distributed rate/concurrency correctness;
- provider outage/rate-limit/timeout mapping;
- default CI live billable calls = 0;
- billable provider send/usage evidence;
- **response loss after possible paid dispatch does not cause blind second provider/Agent call**;
- cache hit consumes zero upstream billable unit.

---

# G8 — Retrieval / Content acquisition

Must prove:

- safe DNS/connect/redirect path;
- streaming/decompression limits;
- Content staging/finalization/reconciliation;
- owner isolation;
- no hidden Browser/L2;
- `web_fetch` ambiguous response after possible acquisition/Content creation **does not blind replay**;
- large payload externalized/bounded.

---

# G9 — Content parser / representation reuse

For L1 parser changes:

- format detection contract;
- parser input/output/time/resource limits;
- isolated risky parser crash/timeout/kill;
- no OCR/L2 hidden escalation;
- provenance;
- concurrent/replayed compatible representation reuse;
- `content_parse` cannot receive idempotent trusted classification until canonical reuse is proven.

v0.5 additionally tests archive/container bomb limits and S3/filesystem parity.

---

# G10 — Browser lifecycle / interaction

Browser release must prove:

- worker generation/lease/self-fencing;
- session subprocess + dedicated Chromium boundary;
- public-only egress/no fallback;
- create/close/TTL/reaper/lost/drain;
- page identity/generation;
- exact ElementRef stale identity;
- per-session serial action lane;
- action ledger/status recovery/`unknown`;
- no blind duplicate mutation;
- explicit `browser_scroll` on long/lazy/nested-scroll fixtures;
- snapshot→scroll→snapshot behavior;
- fill-form sequential fail-fast + `not_attempted`;
- structured key press;
- multi-file upload semantics;
- dialogs/popups/downloads;
- screenshot/rendered/download Content handoff;
- no orphan Chromium/temp/ref leaks.

---

# G11 — Durable Jobs

Must prove:

- transactional Job+Items+Outbox create;
- Redis outage/recovery;
- duplicate queue delivery;
- authoritative DB claim;
- attempt lease/fencing;
- worker crash/lost attempt/retry_wait;
- succeeded JobItems not rerun;
- cancellation;
- partial result manifest;
- bounded progress writes;
- no generic arbitrary function payload.

---

# G12 — Policy / quota / admin operations

v0.7+ must prove:

- global policy CAS/revision/rollback;
- principal override update/delete + revision bump;
- schema/static registry validation;
- no `admin` dynamic task capability;
- authorized admin can recover with all task capabilities disabled;
- quota races cannot oversubscribe;
- billable reservation cannot double-spend;
- usage reconciliation repairs drift;
- audit mutation atomicity/redaction;
- generation-safe worker drain;
- typed maintenance only;
- hot-principal Job fairness/backpressure.

---

# G13 — Observability / health / readiness

Verify:

- operation/request/trace correlation;
- no secrets/high-cardinality content labels;
- dependency/capability states accurate;
- liveness does not incorrectly equal every dependency health;
- readiness/degraded semantics observable;
- metrics/events bounded;
- audit distinct from telemetry.

---

# G14 — MCP facade usability

Actual MCP acceptance:

- exact current catalog (v0.8 target **28 tools**);
- descriptions sufficient for discovery;
- every nested input field described;
- no aliases/obsolete tools;
- no infrastructure/provider secrets;
- batch-first independent operations;
- stateful actions separate;
- cost/resource-aware own-agent retry metadata ADR-0024;
- no admin/L2/raw Playwright tools;
- representative generic MCP client works.

---

# G15 — REST facade

Verify exact composite contract:

```text
rest-api-v1
browser-api-v1
policy-models
admin-api-v1
```

Including:

- security/scopes;
- normalized errors;
- streaming Content;
- opaque cursors/refs;
- Browser action unions;
- Admin typed operations;
- no raw SQL/Redis/provider/Playwright proxy.

---

# G16 — Own-agent integration

Cross-repository acceptance with `internet-search-bot`:

- tool discovery/schema retrieval/call;
- trusted presentation metadata;
- BrowserSession remote handle cleanup;
- Job/Content lifecycle;
- `unknown` preserved;
- billable/resource/stateful response-loss no blind duplicate;
- `snapshot→scroll→snapshot` flow;
- service unavailable does not destroy unrelated Agent runtime.

---

# G17 — Race / concurrency

Applicable randomized/adversarial cases:

- last quota slot across replicas;
- stale revisions;
- concurrent Content finalization/reuse;
- worker generation changes;
- close vs expiry;
- cancellation vs completion;
- outbox publishers/claims;
- Redis lease ownership;
- policy concurrent update;
- Browser queued action vs drain/loss.

A race only reproduced once is still a defect until resolved/explained.

---

# G18 — Fault injection / restart / recovery

Inject failures at important commit/dispatch boundaries:

- before/after DB commit;
- before/after Redis publish;
- after remote send before response;
- worker kill;
- Control Plane restart;
- Redis restart/flush;
- ContentStore write/finalize fault;
- parser/session child hang/crash;
- Browser egress outage;
- policy invalidation loss.

System must converge to documented state or explicit `unknown/lost`, never silent corruption.

---

# G19 — Soak / resource leak

For long-lived/child-process capabilities:

- repeated create/use/close;
- temp files;
- child processes;
- Browser refs/handles;
- DB/Redis connections;
- parser workers;
- Content staging garbage;
- memory/FD growth.

No unbounded leak trend within measured acceptance budget.

---

# G20 — Load / backpressure / fairness

Measure by defined hardware/profile:

- request throughput/latency;
- Search provider cap;
- Retrieval bytes/concurrency;
- Content parser capacity;
- Browser sessions/worker/RAM/action latency;
- Job backlog/throughput;
- quota/policy contention;
- hot-principal fairness.

Overload must reject/defer with structured capacity/backpressure, not OOM/thread/process explosion.

Exact budgets become measured baselines in version evidence; they are not invented by this generic gate.

---

# G21 — Upgrade / rolling compatibility

Applicable v0.7+ / production:

- expand-first migrations;
- mixed old/new API replicas;
- policy schema readable overlap;
- Browser/Job worker revision compatibility;
- drain/rolling restart;
- old client compatibility according public policy;
- rollback within supported window.

---

# G22 — Backup / restore / disaster recovery

v0.9 production candidate:

- PostgreSQL backup/restore;
- ContentStore restore/reconciliation;
- Redis disposable/rebuild assumptions validated;
- restored resource metadata/blob consistency;
- runbook game day;
- documented RPO/RTO evidence/profile.

---

# G23 — Supply chain / artifact reproducibility

Production release validates:

- lockfile/pinned critical runtime artifacts;
- container/image digest/version evidence;
- browser/runtime dependencies;
- dependency/security scans;
- no accidental secret in image/repo;
- reproducible documented build path.

---

# G24 — Full test result hygiene

Acceptance run expects:

```text
0 failed
0 errors
0 unexplained xfail/xpass
```

Skips allowed only with documented intentional environment/scope reason.

A required acceptance test cannot be permanently skipped.

---

# G25 — Flaky policy

Known flaky test = open quality defect until:

- race/flakiness fixed;
- or test proven wrong and corrected/removed.

Rerun can diagnose; a green rerun does not erase original flake.

---

# G26 — Live external profile

Default CI does not depend on public websites or billable providers.

Manual/release live profile:

- bounded budget;
- recorded date/provider/runtime revision;
- exact live call count;
- failures separated from deterministic controlled suites.

Live smoke is supplementary, not sole correctness evidence.

---

# G27 — No hidden orchestration

Integration tests prove absence of forbidden automatic transitions unless explicit caller operation exists:

```text
Search → Retrieval
Retrieval → Browser
Content L1 → L2/OCR
request-bound → durable Job
```

Structured hint is not execution.

---

# G28 — Release evidence artifact

Major version acceptance should preserve report artifact containing at least:

```text
commit SHA
version/patch
migration head
test counts/skips
schema/golden diffs
security summary
race/fault summary
load/soak summary when applicable
live external call count/budget
known limitations
```

Prefer Markdown + machine-readable JSON/CI artifact where project tooling defines it.

---

# G29 — Version-specific gate declaration

Every version README/implementation plan states:

- applicable gates;
- intentionally not-applicable gates + reason;
- extra version-specific gates.

No acceptance by vague «all tests pass».

---

# G30 — Intermediate patch gates

Not every patch runs production soak/load, but every patch preserves accepted previous baseline.

Sequence may escalate:

```text
unit/contract
→ integration/migration
→ race/fault/security
→ final applicable soak/load/release
```

Next patch begins only after previous required gate.

---

# G31 — Coding-agent handoff

Large Codex/ChatGPT task includes:

- canonical docs;
- exact version/patch scope;
- non-goals/forbidden shortcuts;
- expected modules/migrations;
- exact public contracts;
- tests/gates;
- no open architectural choices left to agent.

Coding-agent narrative is not acceptance evidence; repository/test state is.

---

# Gate-system acceptance

Release gate system is complete enough for current v1 line when:

1. each roadmap version can list applicable gates;
2. all critical runtime/resource classes have dedicated gates;
3. cost/resource-aware retry is explicit;
4. Search paid-call, Retrieval Content creation and Browser mutation ambiguity are separately tested;
5. MCP 28-tool/REST specialized contracts are executable-gated;
6. dynamic policy/admin self-lockout is tested;
7. race/fault/security/soak/load are not hidden under unit tests;
8. upgrade/restore/supply-chain exist before production;
9. flaky failures cannot be masked;
10. release evidence supports independent review.
