# v0.8 — REST/MCP & Agent Integration Stabilization

## Статус

`ready for implementation`

Версия стабилизирует внешний contract уже реализованной системы перед production hardening/v1.0. Она не должна прятать незавершённый backend за красивыми schemas.

---

# 1. Цель

После v0.8:

- REST `/api/v1` имеет reviewable freeze-candidate OpenAPI;
- MCP имеет freeze-candidate semantic catalog ADR-0022;
- actual runtime schemas сохраняются generated contract fixtures;
- error/resource/cursor semantics согласованы;
- own `internet-search-bot` builtin integration проходит cross-repository acceptance;
- generic MCP client продолжает работать без agent-specific implementation dependency;
- accidental public contract change становится CI-visible.

---

# 2. Prerequisites

- реализованные/accepted v0.1–v0.7;
- `../../compatibility.md`;
- `../../agent-integration.md`;
- `../../rest-api.md`;
- `../../mcp.md`;
- `../../application-contracts.md`;
- `../../resource-model.md`;
- `../../testing.md`;
- `../../release-gates.md`;
- ADR-0021;
- ADR-0022;
- current agent-side `builtin-mcp-service-contract.md`.

---

# 3. Explicit non-goals

- new Search provider purely for v0.8;
- new parser family;
- new Browser feature because Playwright supports it;
- crawl;
- persistent Browser profiles;
- user accounts;
- public client SDK requirement;
- v1.0 compatibility promise before v0.9 hardening;
- copying agent trusted descriptors/presentation into Web Access source.

---

# 4. Contract artifact directory

Repository adds generated/reviewed artifacts:

```text
contracts/
├── manifest.json
├── rest/
│   └── openapi-v1.json
├── mcp/
│   └── tools-v1.json
└── common/
    ├── error-taxonomy-v1.json
    └── resource-schemas-v1.json
```

They are generated from actual running application/contracts, canonicalized and committed/gated.

Human design remains in `docs/design`.

---

# 5. Contract manifest

`contracts/manifest.json` includes bounded metadata:

```text
manifest schema version
REST API version
MCP catalog revision
application result envelope revision
error taxonomy revision
resource schema revision
canonical SHA-256 fingerprints of generated artifacts
minimum service compatibility metadata where useful
```

Package/build version separate from contract version.

---

# 6. Canonical JSON generation

Generator:

- stable UTF-8 JSON;
- recursively deterministic key ordering;
- stable formatting/newline;
- removes non-semantic volatile generated fields if necessary through explicit allowlisted normalizer;
- never hides real schema differences merely to keep fixture green.

CI diff is reviewer-visible.

---

# 7. REST freeze candidate

REST remains:

```text
/api/v1
```

v0.8 reviews actual implemented routes against `rest-api.md` and normalizes before freeze.

Required capability groups:

```text
search
retrieval
content
browser
jobs
admin (protected)
```

Operational liveness/metrics may remain outside `/api/v1`.

---

# 8. REST stability requirements

Every public operation has:

- stable `operationId`;
- Russian summary/description where project documentation is exposed;
- exact security scheme;
- exact required/default/min/max/enum;
- common error responses;
- bounded examples for complex models;
- no infrastructure/internal fields.

FastAPI default validation response is normalized to Web Access error envelope.

---

# 9. REST behavior freeze review

Review all existing routes for:

- duplicate intents;
- inconsistent plurals/naming;
- mixed resource/action semantics;
- accidental raw provider fields;
- arbitrary HTTP/Playwright leakage;
- response envelope inconsistency;
- incorrect HTTP status mapping;
- missing owner/auth docs;
- giant inline response paths.

Fix before fixture freeze, not after v1.0.

---

# 10. MCP freeze candidate

Exact catalog from ADR-0022:

```text
web_search
web_fetch
web_fetch_job
content_get
content_parse
content_parse_job
browser_create
browser_get
browser_close
browser_navigate
browser_snapshot
browser_content
browser_tabs
browser_page_create
browser_page_close
browser_screenshot
browser_events
browser_click
browser_fill_form
browser_type
browser_press
browser_hover
browser_drag
browser_wait
browser_upload
job_get
job_cancel
```

No legacy/exploratory mixed variants.

---

# 11. MCP descriptions/schema review

For each tool independently answer:

1. Можно ли по short description понять intent до schema?
2. Отличается ли он от соседних одним предложением?
3. Каждое ли поле описано по-русски?
4. Все ли limits machine-readable?
5. Есть ли один stable execution/retry class?
6. Нет ли backend/provider/Playwright leakage?
7. Можно ли исправить invalid call по structured error?
8. Bounded ли result?

Tool не freeze-ится, пока ответ не «да».

---

# 12. MCP actual fixture

`tools-v1.json` генерируется через реальный MCP client/server discovery и содержит для каждого tool минимум:

```text
name
description
inputSchema
relevant annotations
output/result schema metadata where SDK exposes stable representation
```

Private runtime/context parameters отсутствуют.

---

# 13. Tool semantics fixture

Machine fixture alone не доказывает descriptions/behavior.

Contract test suite дополнительно имеет semantic assertions, например:

```text
web_search description says results are search metadata, not read page
web_fetch says no Browser auto fallback
web_fetch_job says creates Job/survives disconnect
browser_snapshot vs browser_content distinction
browser_tabs read-only
browser_page_create separate
browser_fill_form no submit
browser_click unknown/no blind retry semantics
```

---

# 14. Error taxonomy freeze

All facade/domain errors mapped to stable external categories/codes.

Required broad categories:

```text
validation
authentication
authorization/policy
not_found/expired/lost
conflict/stale
rate/quota/capacity
upstream/provider/network
content/parser
browser
jobs
storage
internal
```

Specific codes may grow additively after freeze, but existing meaning/retryability must not silently change.

---

# 15. Resource schema freeze

Stable public ResourceRef identities:

```text
content_id
browser_session_id
page_id
job_id
snapshot_id / element_ref as ephemeral Browser coordinates
```

Opaque means client never relies on prefix beyond human diagnostics.

Ownership/routing never encoded client-side.

---

# 16. Cursor versioning

Existing Content/collection/event cursors gain/confirm explicit internal version parsing.

Old cursor version remains readable for relevant resource retention window or fails explicit version error.

Client always treats cursor opaque.

---

# 17. Result envelope freeze

REST/MCP mappings consistently preserve canonical:

```text
operation_id
outcome
data/error
warnings
hints
```

Batch per-item outcomes preserve input order.

`unknown` remains first-class, especially Browser mutating action.

---

# 18. Own Agent integration mapping

Coordinated acceptance with `RawsTourix/internet-search-bot` verifies:

```text
Web Access actual MCP schemas
↔ agent builtin trusted descriptors
```

Agent-side mapping owns:

- presentation profiles;
- retry/side-effect classes;
- remote-resource handling;
- permissions/budgets;
- BrowserSession cleanup binding.

Web Access does not store agent UI strings.

---

# 19. Browser resource mapping

Own agent descriptor maps:

```text
browser_create
→ resource_type browser_session
→ cleanup browser_close
```

Agent lifecycle hook cleanup is best effort.

Web Access TTL/reaper remains authoritative final cleanup.

MCP reconnect does not close BrowserSession.

---

# 20. Job resource mapping

```text
web_fetch_job/content_parse_job
→ JobRef
→ job_get/job_cancel
```

Job is durable and not automatically bound to one MCP connection/AgentCycle.

Trusted tool creation semantics prevent blind automatic retry if JobRef response lost.

---

# 21. Progress/presentation integration

Agent UI can map stable tool identity to phrases/events, but this remains agent-side.

Web Access only returns stable semantic operation/provider/domain/resource/progress metadata.

Cross-repo acceptance checks:

- pretty presentation does not depend on parsing raw tool text;
- unknown future tool gets generic safe fallback;
- Web Access result text cannot override trusted presentation.

---

# 22. Cross-repository integration test

Release/integration workflow can checkout:

```text
web-access-mcp-server @ candidate commit
internet-search-bot @ pinned compatible commit
```

Run controlled Web Access deployment with fake/local providers and agent MCP integration tests.

This is a **test-time pinned dependency**, not Python runtime package dependency.

Default fast unit CI in either repo need not depend on network checkout of the other; release gate does.

---

# 23. Generic MCP client acceptance

Separate from own-agent test:

- standard MCP connect/list/call;
- no manager-function assumption;
- explicit Browser lifecycle;
- Content read;
- durable Job lifecycle;
- reconnect.

This prevents accidental lock-in to own Agent Runtime.

---

# 24. Authentication integration

Agent Web Access connection receives service credential through trusted MCP server definition/secret config.

Tool schema never contains bearer/API credential.

Web Access owner remains authenticated principal unless future delegated identity contract is explicitly added.

---

# 25. Compatibility review labels

Every public-contract PR/change after v0.8 classifies:

```text
internal
additive
compatible behavior
breaking candidate
```

Generated diff attached to review/CI artifact.

Breaking candidate cannot merge unnoticed.

---

# 26. Pre-v1 deprecation policy

v0.8–v0.9 are freeze-candidate phases.

If a genuine defect requires breaking change before v1.0:

- explicit ADR/change note;
- contract fixture diff;
- own-agent coordinated update;
- migration/release note;
- no compatibility fiction.

Better fix defect before v1 than preserve broken design forever.

---

# 27. Contract tests

Required:

- deterministic fixture generation twice same code;
- OpenAPI fixture diff;
- MCP actual schema fixture diff;
- schema descriptions/limits/annotations;
- old representative requests against new service;
- error code/retryability assertions;
- cursor old/current version;
- agent trusted descriptor compatibility;
- generic MCP client;
- REST client representative flow;
- Browser unknown outcome integration;
- Job resource integration.

---

# 28. Documentation synchronization

Before v0.8 release:

- remove exploratory tool/endpoint examples that conflict with freeze;
- `mcp.md`/`rest-api.md` reflect actual implementation;
- version docs point to current ADRs;
- README/catalog generated from contract where practical;
- examples use exact real schemas.

---

# 29. Definition of Done

v0.8 complete only if:

1. REST OpenAPI freeze candidate committed/generated deterministically.
2. MCP 27-tool freeze candidate actual fixture committed.
3. No mixed execution-class tool remains.
4. Error/resource/cursor contracts reviewed.
5. Own-agent builtin descriptors match actual Web Access schemas/semantics.
6. Browser cleanup/unknown behavior works end-to-end.
7. Job lifecycle works end-to-end.
8. Generic MCP client works without own agent internals.
9. Contract-changing PR gate active.
10. Documentation has no contradictory exploratory public contracts.
