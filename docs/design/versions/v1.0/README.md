# v1.0 — Stable Web Access

## Статус

`release contract defined`

`v1.0` не является очередной большой feature version. Она обозначает переход уже реализованного и прожаренного Web Access к первой stable public contract line.

Версия может быть объявлена завершённой только после выполнения `release-checklist.md` на реальном release candidate.

---

# 1. Meaning of v1.0

`v1.0` означает:

- основные architecture boundaries считаются стабильными;
- REST `/api/v1` поддерживается по опубликованной compatibility policy;
- MCP core catalog поддерживается как stable semantic contract;
- durable resource/lifecycle semantics стабильны;
- operator/deployment recovery model доказан;
- дальнейшее развитие преимущественно additive;
- breaking change требует явной новой contract/migration boundary.

`v1.0` **не означает**:

- отсутствие будущих features;
- поддержку всех файлов/сайтов;
- универсальный OCR/VLM/L2;
- абсолютную безошибочность внешнего Internet;
- бесконечную backward compatibility с любым pre-v1 experiment.

---

# 2. Required completed versions

До v1.0 должны быть accepted/implemented/gated:

```text
v0.1 Service Foundation
v0.2 Search Runtime
v0.3 Retrieval & Content Core
v0.4 Managed Browser Runtime
v0.5 Native Content Expansion
v0.6 Durable Jobs Runtime
v0.7 Distributed Operations & Policy Hardening
v0.8 REST/MCP & Agent Integration Stabilization
v0.9 Production Hardening
```

Нельзя пропустить version gate и «закрыть» его v1 smoke-тестом.

---

# 3. Stable architecture boundaries

Stable first-major boundaries:

```text
Transport (REST/MCP)
→ Application
→ Domain
→ Ports
→ Infrastructure adapters
```

Process topology:

```text
Control Plane
Job Worker
Browser Worker supervisor
BrowserSession subprocess
PostgreSQL
Redis
ContentStore
Search providers
Browser Egress Gateway
```

Internal implementations могут эволюционировать, пока public/application invariants сохраняются.

---

# 4. Stable REST contract

REST stable line:

```text
/api/v1
```

После v1.0 внутри `/api/v1`:

- removal/rename required field/path запрещён без migration/deprecation/new major boundary;
- new optional fields/endpoints allowed with compatibility review;
- status/error semantics stable;
- ResourceRefs/cursors stable under compatibility policy;
- OpenAPI golden contract gate mandatory.

Breaking external REST change обычно требует `/api/v2` или другой explicitly approved major migration.

---

# 5. Stable MCP contract

MCP v1 core catalog основывается на ADR-0022 и фактическом v0.8/v0.9 contract fixture.

После v1.0:

- tool name/intent cannot silently change;
- required input cannot change incompatibly;
- retry/resource/lifecycle class cannot silently change;
- descriptions may be clarified without changing semantics;
- additive new tool only for genuine new intent;
- deprecated tool follows explicit migration/removal policy.

No convenience aliases proliferation.

---

# 6. Stable resource/lifecycle contracts

Stable resource classes:

```text
ContentObject / ContentRef
BrowserSession / PageRef / snapshot refs
Job / JobRef
```

Core guarantees:

- opaque handles;
- server-side owner validation;
- BrowserSession independent of MCP connection;
- Job durable across client disconnect;
- Content stored/retained according service policy;
- server-side cleanup/reconciliation;
- `unknown` preserved for uncertain side-effect outcome.

---

# 7. Stable Content boundary

Web Access v1 guarantees conceptual split:

```text
L0 Inspection
L1 Native Parsing
L2 Advanced Processing outside Web Access
```

New direct parsers may be added additively.

Service will not silently turn unsupported format into OCR/LibreOffice/VLM processing.

---

# 8. Stable Browser boundary

v1 Browser remains:

```text
explicit BrowserSession
→ Browser Worker supervisor
→ session subprocess
→ Playwright/Chromium
```

Core semantics stable:

- no hidden browser fallback;
- explicit page IDs/actions;
- semantic snapshot/opaque exact refs;
- no CSS/XPath normal MCP surface;
- mutating uncertain outcome not blindly retried;
- server TTL/reaper;
- public-only browser egress boundary.

Future pooling/persistent profiles are additive/new capabilities only after separate design.

---

# 9. Stable Jobs boundary

v1 durable Jobs guarantee:

- PostgreSQL authoritative state;
- transactional outbox;
- at-least-once queue delivery;
- DB claim/Attempt fencing;
- retry/cancellation durable;
- Item checkpoints for supported batch jobs;
- result manifest ContentObject;
- no exactly-once fiction;
- no arbitrary public task executor.

Additional typed Job workloads can be added later.

---

# 10. Stable policy/ownership boundary

- identity from trusted AuthProvider/PrincipalContext;
- dynamic policy can restrict but not mint scopes;
- durable quotas/accounting in PostgreSQL;
- Redis transient flow limiting only;
- secrets not stored dynamic policy;
- admin controls REST-only baseline;
- operator mutations audited.

Future account/OIDC system plugs into AuthProvider without rewriting resource ownership model.

---

# 11. Compatibility policy becomes release requirement

`compatibility.md` is normative for v1.x.

Every public-contract change requires classification and generated fixture diff.

Breaking change cannot be merged as routine patch/minor release without explicit major/migration decision.

---

# 12. Versioning after v1.0

Recommended semantic release direction:

```text
v1.x.y
```

Conceptually:

- patch: bug/security/compatible internal fixes;
- minor: additive capabilities/tools/endpoints/options;
- major: intentionally breaking public contract.

Exact package/tag automation can be chosen implementation-side, but release notes must state compatibility impact.

---

# 13. Upgrade support

Every v1 release documents supported upgrade path from at least previous supported release.

Migrations:

- expand-first where rolling deployment expected;
- no accidental downgrade assumption;
- rollback classification explicit;
- irreversible migration called out before deploy.

---

# 14. Backup/restore obligation

v1 release cannot rely on untested backup theory.

A recent production-like backup/restore drill must exist according `operational-readiness.md` and release checklist.

Critical schema/storage changes can require refreshed drill before release.

---

# 15. Security obligation

v1 release requires:

- current dependency/container scan;
- no unresolved critical exploitable release blocker;
- SSRF/browser egress/parser/auth/owner regression suite green;
- secrets redaction/rotation validated;
- known exceptions documented with mitigation/expiry.

---

# 16. Capacity obligation

Reference defaults must have measured evidence.

Release notes/evidence identify test profile/hardware so numbers are not misrepresented as universal SLA.

Saturation must fail/defer in bounded way.

---

# 17. Own-agent integration

v1 release requires compatible `internet-search-bot` builtin integration candidate:

- Streamable HTTP;
- actual schema compatibility;
- trusted tool descriptors;
- pretty progress mapping;
- Browser cleanup;
- `unknown` semantics;
- Job lifecycle;
- outage/degraded behavior.

Web Access remains generic MCP-compatible regardless.

---

# 18. Generic clients

Stable v1 service remains independently usable through:

- REST;
- generic MCP client.

Own-agent integration cannot become an undocumented protocol requirement.

---

# 19. Known limitations are part of release quality

v1 documentation explicitly lists limitations instead of pretending unsupported cases work.

Examples likely include:

- no built-in L2 OCR/VLM/office conversion;
- no BrowserSession migration;
- no persistent authenticated browser profile baseline;
- no CAPTCHA/stealth guarantee;
- only registered L1 formats;
- external provider/site availability/latency outside service guarantee;
- no crawl unless designed/implemented later.

---

# 20. Release evidence

v1 release archive/CI artifact records at least:

```text
source commit/tag
package/build version
uv.lock hash
container image refs/digests
contract manifest hash
Alembic head
full gate result
security scan summary
capacity/soak summary
backup/restore evidence
own-agent/generic MCP acceptance
known limitations/security exceptions
```

---

# 21. Release blockers

v1 MUST NOT release with unresolved:

- data-loss/corruption defect;
- owner/auth bypass;
- SSRF/internal browser egress bypass;
- blind duplicate mutating Browser action;
- Job permanent-running/lost committed-job defect;
- migration blocker;
- reproducible process/temp/storage leak causing unbounded growth;
- contract inconsistency with own agent/generic client;
- critical exploitable supply-chain/security issue without approved exception;
- backup/restore failure;
- undocumented destructive upgrade behavior.

---

# 22. Post-v1 evolution

Potential additive future directions:

- new Search providers;
- crawl/site traversal as separate designed Job capability;
- new L1 native parsers;
- external L2 document-processing integration;
- persistent Browser profiles under explicit security model;
- richer Browser diagnostics;
- OIDC/delegated users;
- alternative JobQueue/worker scale implementation;
- optimized Browser process pooling after measurements.

None justify weakening stable v1 invariants.

---

# 23. Definition of Done

`v1.0` complete only when `release-checklist.md` is fully signed off/evidenced for a specific candidate and no release blocker remains.
