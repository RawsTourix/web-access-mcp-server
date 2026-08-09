# v1.0 — Release checklist

## Назначение

Этот checklist выполняется для **конкретного release candidate**. Пункт нельзя отметить выполненным без проверяемого evidence.

Если пункт неприменим, причина документируется явно; release-critical invariant нельзя объявить N/A ради выпуска.

---

# 1. Candidate identity

- [ ] source commit/tag зафиксирован;
- [ ] package/build version зафиксирована;
- [ ] `uv.lock` hash зафиксирован;
- [ ] container image refs/digests зафиксированы;
- [ ] contract manifest hash зафиксирован;
- [ ] Alembic head зафиксирован;
- [ ] policy schema revision/support range зафиксированы;
- [ ] compatible own-agent candidate/ref зафиксирован.

---

# 2. Source/design consistency

- [ ] architecture dependency tests green;
- [ ] implemented process topology соответствует docs;
- [ ] accepted ADR registry актуален;
- [ ] нет незадокументированного architecture shortcut;
- [ ] version/current docs соответствуют фактическому implementation status;
- [ ] known limitations актуальны;
- [ ] open architecture questions не являются implementation blockers.

---

# 3. Migrations

- [ ] Alembic single head;
- [ ] empty DB → latest succeeds;
- [ ] supported previous release → latest succeeds;
- [ ] mixed-version rolling compatibility tested where promised;
- [ ] irreversible migrations explicitly identified;
- [ ] rollback/forward-fix classification documented;
- [ ] pre-migration backup requirement documented/exercised.

---

# 4. PostgreSQL durability

- [ ] transaction/race suites green;
- [ ] Job/outbox consistency green;
- [ ] Content lifecycle reconciliation green;
- [ ] Browser durable metadata reconciliation green;
- [ ] policy/audit/quota transactional invariants green;
- [ ] pool/lock saturation tested;
- [ ] no unresolved corruption/data-loss issue.

---

# 5. Backup/restore

- [ ] recent PostgreSQL backup created;
- [ ] restore performed into isolated environment;
- [ ] restored DB upgraded/startable by candidate;
- [ ] ContentStore restore/availability verified;
- [ ] content hashes/sizes sampled/verified;
- [ ] Job result manifests verified;
- [ ] post-restore reconciliation executed;
- [ ] stale BrowserSessions do not resurrect;
- [ ] measured restore evidence recorded;
- [ ] known RPO/RTO/profile documented honestly.

---

# 6. Redis destructive recovery

- [ ] Redis contents destroyed/recreated in controlled test;
- [ ] worker registry rebuilt;
- [ ] Job wake-ups recovered from outbox/reconciler;
- [ ] durable quotas/accounting preserved;
- [ ] Search cache loss harmless;
- [ ] no durable Job/Content data loss;
- [ ] readiness/degraded states correct during recovery.

---

# 7. Search

- [ ] SearXNG integration/contract tests green;
- [ ] explicit provider/default selection works;
- [ ] no hidden provider fallback;
- [ ] cache/rate/concurrency isolation works;
- [ ] billable provider budget/accounting tests green;
- [ ] provider outage/degraded states correct;
- [ ] no paid live calls in default CI/load suite;
- [ ] MCP `web_search` actual schema frozen/green.

---

# 8. Retrieval

- [ ] SSRF tests green;
- [ ] DNS rebinding/mixed result tests green;
- [ ] redirect revalidation green;
- [ ] TLS/hostname/SNI tests green;
- [ ] private/link-local/metadata targets blocked;
- [ ] body/decompression limits enforced during streaming;
- [ ] slow upstream/cancellation/deadline tests green;
- [ ] per-host/global backpressure green;
- [ ] no Browser auto fallback;
- [ ] MCP `web_fetch` contract green.

---

# 9. Content Core / Native Parsing

- [ ] staging/finalization crash matrix green;
- [ ] reconciliation/GC green;
- [ ] filesystem ContentStore contract green;
- [ ] S3-compatible ContentStore contract green for production profile;
- [ ] L0 identification/inspection green;
- [ ] v0.3 L1 parsers green;
- [ ] v0.5 registered parser families green;
- [ ] complex parser isolation/timeouts/kill green;
- [ ] package bombs/traversal/XML attacks green;
- [ ] image decompression-bomb protection green;
- [ ] macros/external code/formulas not executed;
- [ ] no OCR/VLM/LibreOffice hidden fallback;
- [ ] provenance/versioning correct;
- [ ] storage quota lifecycle correct;
- [ ] MCP Content tools contracts green.

---

# 10. Browser Runtime

- [ ] separate Browser Worker runtime;
- [ ] one BrowserSession → one session subprocess → one Chromium baseline verified;
- [ ] cookie/storage/process isolation green;
- [ ] worker registration/generation/lease/self-fencing green;
- [ ] multi-replica routing green;
- [ ] exact snapshot ElementRefs/stale replacement tests green;
- [ ] session action serialization green;
- [ ] action status recovery green;
- [ ] mutating response-loss never duplicates action;
- [ ] unresolved mutating result propagates `unknown`;
- [ ] dialog policy green;
- [ ] screenshot/rendered/download/upload Content handoff green;
- [ ] TTL/reaper green without client cleanup;
- [ ] forced close kills/reaps child tree;
- [ ] repeated create/close soak leaves no zombies/temp leak;
- [ ] worker drain/restart green;
- [ ] egress gateway blocks internal/private/metadata targets;
- [ ] no direct Internet fallback;
- [ ] session child has no internal credentials;
- [ ] actual Browser MCP catalog/annotations green.

---

# 11. Durable Jobs

- [ ] committed Job cannot be lost DB→Redis;
- [ ] duplicate queue delivery does not duplicate body;
- [ ] authoritative DB claim/fencing green;
- [ ] worker crash → Attempt lost/recovery green;
- [ ] stale Attempt cannot late-commit;
- [ ] JobItem successful checkpoints survive retry;
- [ ] retrieval/content parse batch handlers reuse application logic;
- [ ] cancellation lifecycle green;
- [ ] partial result semantics green;
- [ ] manifest finalization crash recovery green;
- [ ] backlog/reconciler green;
- [ ] hot-principal fairness green;
- [ ] `web_fetch_job`/`content_parse_job` contracts green;
- [ ] `job_get`/`job_cancel` owner/lifecycle green;
- [ ] no generic arbitrary task public surface.

---

# 12. Policy / quotas / admin

- [ ] policy revision optimistic concurrency green;
- [ ] policy polling/invalidation/staleness green;
- [ ] policy cannot mint auth scope;
- [ ] secrets absent from dynamic policy;
- [ ] Browser quota concurrent last-slot race green;
- [ ] Job quota/fairness green;
- [ ] Content logical byte quota green;
- [ ] billable reservation double-spend tests green;
- [ ] usage reconciliation green;
- [ ] admin endpoints require admin scope;
- [ ] operator mutations produce transactional audit;
- [ ] no admin MCP tools.

---

# 13. REST contract

- [ ] `/api/v1` OpenAPI fixture matches expected candidate;
- [ ] all `operationId`s stable/unique;
- [ ] auth schemes documented;
- [ ] validation/error envelope consistent;
- [ ] bounds/defaults/enums accurate;
- [ ] binary/streaming endpoints bounded/safe;
- [ ] no infrastructure/private fields leak;
- [ ] breaking diff absent or explicitly approved before release;
- [ ] representative REST client suite green.

---

# 14. MCP contract

- [ ] actual FastMCP discovery yields exact frozen core catalog;
- [ ] all tool descriptions Russian and semantically reviewed;
- [ ] every public/nested input field documented;
- [ ] machine-readable limits accurate;
- [ ] no mixed execution-class tool;
- [ ] annotations/trusted semantics consistent;
- [ ] structured errors/warnings/hints green;
- [ ] bounded result/ContentRef behavior green;
- [ ] contract fixture/fingerprint matches;
- [ ] generic MCP client suite green.

---

# 15. Own-agent integration

- [ ] Web Access builtin registration uses Streamable HTTP;
- [ ] agent trusted descriptors compatible with actual schemas;
- [ ] presentation profiles green;
- [ ] BrowserSession handle/cleanup mapping green;
- [ ] agent cleanup failure does not invalidate correct final answer improperly;
- [ ] service TTL cleans if agent disappears;
- [ ] `unknown` never blind-retried by Dispatcher;
- [ ] durable Job survives disconnect/cycle as designed;
- [ ] Web Access outage degrades capability without destroying unrelated Agent Runtime;
- [ ] no secrets in LLM context/tool schema;
- [ ] pinned cross-repo release acceptance green.

---

# 16. Multi-replica/race/fault

- [ ] randomized race suite green across repeated seeds;
- [ ] failed seed reproducibility retained;
- [ ] Control Plane replica loss tests green;
- [ ] Browser Worker loss/partition tests green;
- [ ] Job Worker/publisher/reconciler loss tests green;
- [ ] Redis loss tests green;
- [ ] ContentStore transient failure tests green;
- [ ] policy/usage races green;
- [ ] no flaky release-blocking test hidden by rerun.

---

# 17. Load/capacity/backpressure

- [ ] capacity report names hardware/profile;
- [ ] Control Plane saturation measured;
- [ ] Retrieval throughput/concurrency measured;
- [ ] parser concurrency/RAM measured;
- [ ] Browser RAM/session/max stable sessions measured;
- [ ] Job throughput/backlog recovery measured;
- [ ] DB/Redis/storage saturation measured;
- [ ] defaults based on evidence;
- [ ] saturation returns bounded reject/defer, not OOM/unbounded queue;
- [ ] no universal SLA claimed from one profile.

---

# 18. Soak/leak

- [ ] Browser long soak green;
- [ ] parser child churn soak green;
- [ ] Job worker/retry soak green;
- [ ] Content retention/GC soak green;
- [ ] Redis reconnect cycles green;
- [ ] policy update cycles green;
- [ ] RSS/fd/thread/process/temp/storage growth reviewed;
- [ ] no unresolved unbounded leak.

---

# 19. Security / supply chain

- [ ] current threat/security regression suite green;
- [ ] Python dependency vulnerability scan reviewed;
- [ ] container image scan reviewed;
- [ ] secret scan green;
- [ ] license inventory/review complete;
- [ ] SBOM generated if selected release process requires it;
- [ ] container hardening checked;
- [ ] Chromium sandbox enabled in supported production profile;
- [ ] no unresolved critical exploitable blocker;
- [ ] exceptions include mitigation/owner/expiry.

---

# 20. Secret rotation

- [ ] external Bearer rotation tested;
- [ ] internal Browser Worker credential rotation tested;
- [ ] provider credential rotation procedure tested/validated where configured;
- [ ] storage credential rotation procedure validated where configured;
- [ ] no secret leakage after drill.

---

# 21. Observability / alerts

- [ ] structured logs correlation works;
- [ ] metrics bounded cardinality;
- [ ] traces usable across application/provider/worker boundaries;
- [ ] capability readiness accurate;
- [ ] alerts exercised through controlled failure;
- [ ] single transient upstream failures do not cause noisy critical alert;
- [ ] critical durable/security failures do alert;
- [ ] audit append/retention verified.

---

# 22. Runbooks / operations

- [ ] DB outage runbook exercised;
- [ ] Redis loss runbook exercised;
- [ ] SearXNG/provider outage runbook exercised;
- [ ] Browser worker/egress outage runbook exercised;
- [ ] Job backlog runbook exercised;
- [ ] ContentStore problem runbook exercised;
- [ ] policy incompatible/stale runbook exercised;
- [ ] rolling deploy runbook exercised;
- [ ] backup/restore runbook exercised;
- [ ] unsafe operator actions explicitly called out.

---

# 23. Production smoke

- [ ] post-deploy smoke suite green;
- [ ] no hidden paid provider call unless explicitly enabled;
- [ ] REST contract fingerprint correct;
- [ ] MCP contract fingerprint correct;
- [ ] controlled Search/Retrieval/Content/Browser/Job paths green;
- [ ] readiness returns expected capability matrix.

---

# 24. Known limitations

- [ ] limitations page/release notes current;
- [ ] L2 absence explicit;
- [ ] Browser ephemeral/no migration explicit;
- [ ] CAPTCHA/stealth limitation explicit;
- [ ] supported native format matrix current;
- [ ] external provider/site availability limitation explicit;
- [ ] no hidden unsupported capability advertised.

---

# 25. Release evidence

- [ ] machine/human-readable release evidence generated;
- [ ] no secrets/raw web content in evidence;
- [ ] test/fault/soak/load summary attached;
- [ ] backup/restore evidence attached;
- [ ] security scan summary attached;
- [ ] compatibility/cross-repo evidence attached;
- [ ] exceptions/known limitations attached.

---

# 26. Final release decision

Release only if:

- [ ] no release blocker from v1.0 README remains;
- [ ] all applicable checklist items complete;
- [ ] all approved exceptions are documented and non-blocking;
- [ ] current candidate exactly matches tested commit/images/contracts;
- [ ] release notes/migration instructions prepared;
- [ ] tag/release artifact created from the tested candidate, not rebuilt from a different source state.

If any release-blocking item is false, **v1.0 is not released**.
