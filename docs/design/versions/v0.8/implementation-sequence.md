# v0.8 — Implementation sequence

## Назначение

Порядок стабилизации внешних contracts и own-agent integration.

Ключевое правило:

> Не freeze-ить случайно сгенерированную текущую схему. Сначала actual implementation сравнивается с reviewed `contracts/*`, semantic divergences исправляются или явно пересматриваются, и только затем generated artifacts становятся golden.

---

# F0 — Preconditions/baseline inventory

Require accepted v0.1–v0.7.

Generate temporary actual inventory:

- REST paths/methods/operationIds/security/schemas;
- Browser specialized routes;
- Admin/policy routes;
- MCP names/descriptions/input schemas/annotations;
- common result/error/resource serialization;
- own-agent trusted descriptors.

No fixture committed as authoritative yet.

---

# F1 — Contract spec consistency

Read together:

```text
contracts/common-models.md
contracts/mcp-tools.md
contracts/rest-api-v1.md
contracts/browser-api-v1.md
contracts/policy-models.md
contracts/admin-api-v1.md
```

Verify no conflicting definitions for same namespace/type.

Specificity:

```text
Browser REST → browser-api-v1.md
Admin REST   → admin-api-v1.md + policy-models.md
Other REST   → rest-api-v1.md
MCP          → mcp-tools.md
```

If conflict is real, resolve Design/ADR first.

---

# F2 — Common public model implementation audit

Align actual serialization with `common-models.md`:

- OperationResult/outcomes;
- errors/details/retryability;
- warnings/hints;
- batch item envelope;
- Content/Browser/Page/Snapshot/Job refs;
- cursors/progress.

No transport-specific accidental duplicate model with different semantics.

---

# F3 — MCP exact schema audit

Actual FastMCP must match **28-tool** contract.

Verify:

- exact names;
- Russian descriptions;
- all nested descriptions;
- no aliases/obsolete tools;
- exact defaults/bounds/enums;
- actual discriminated unions;
- unknown fields rejected;
- scroll/form/key/multi-upload semantics;
- annotations;
- no private/infrastructure fields.

Runtime validation negative fixtures required.

---

# F4 — Retry/resource/cost metadata audit

Implement/verify ADR-0024 end-to-end.

Own-agent trusted descriptor must distinguish:

- pure reads;
- billable Search uncertainty;
- Content/resource creating direct calls;
- idempotent canonical parse reuse;
- Job/session/page/artifact creation;
- Browser mutating actions;
- idempotent cleanup/cancel.

Tests inject response loss at pre-dispatch/post-dispatch/terminal-response phases.

No static “all read-only tools safe retry” shortcut.

---

# F5 — REST common exact audit

Compare ordinary REST implementation to `rest-api-v1.md`:

- Search;
- Retrieval;
- Content;
- Jobs;
- common auth/result/error/cursor/stream semantics.

Verify no raw provider/HTTP/library leakage.

---

# F6 — Browser REST exact audit

Compare Browser namespace to `browser-api-v1.md`:

- sessions/pages/navigation;
- snapshot/rendered Content/screenshot;
- typed actions;
- explicit scroll;
- fill fail-fast;
- structured key;
- multi-upload;
- events;
- retry/unknown semantics;
- Browser read/write scopes.

Actual OpenAPI unions/bounds tests required.

---

# F7 — Policy/Admin exact audit

Compare to:

```text
policy-models.md
admin-api-v1.md
```

Verify:

- exact 8 task capabilities;
- no dynamic `admin` capability;
- global/default/max/override validation;
- policy revisions/rollback;
- principal override CRUD;
- provider/usage/audit;
- worker drain generation;
- typed maintenance;
- admin:read/write auth + deployment boundary;
- no secret/raw SQL/Redis/admin MCP leakage.

Explicit self-lockout test:

```text
disable all task capabilities
→ authorized admin policy control remains usable
```

---

# F8 — Generated artifact tooling

Create deterministic generators for:

```text
OpenAPI v1
FastMCP tool schema/annotations
public model schema/serialization metadata
```

Requirements:

- stable ordering/normalization;
- no timestamps/random build noise;
- one command/CI step reproducible;
- generated from actual registered runtime, not parallel hand-written JSON.

---

# F9 — Golden fixtures

Only after F1–F8 green, commit reviewed golden artifacts.

Recommended logical artifacts:

```text
openapi-v1
mcp-tools-v1
public-models-v1
```

Path can follow repository convention.

Fixture commit includes generation instructions and source revision.

---

# F10 — Compatibility diff classifier

Implement CI diff/report according `compatibility.md`.

Detect/classify at least:

- route/tool removal/rename;
- required field added;
- field removed;
- bound change;
- default change;
- enum change;
- union/discriminator change;
- security requirement change;
- result/resource model change;
- MCP annotations/own-agent retry semantic change;
- policy schema revision/change.

Some additive changes require human semantic review.

---

# F11 — Own-agent builtin registry integration

In `internet-search-bot` integration environment:

- register Web Access as builtin MCP service through standard registry/config;
- trusted presentation descriptors per tool;
- retry/resource/cost semantics from exact current catalog;
- BrowserSession remote handle ownership/cleanup;
- Job/Content lifecycle mapping;
- no special WebToolProvider/direct REST bypass.

Web Access repo must not import agent code.

---

# F12 — Agent UX/workflow acceptance

Representative real workflows:

```text
Search only
Search → Fetch
Search → Browser
Fetch HTML/PDF
Browser navigate → snapshot → interaction
long/lazy page snapshot → scroll → snapshot
form fail-fast recovery
multi-file upload
Browser content/screenshot/download artifacts
durable retrieval Job
durable content parse Job
```

Verify user-facing progress is rendered by Agent trusted presentation, not arbitrary MCP text.

---

# F13 — Response-loss/retry acceptance

Inject failures proving:

- Yandex/billable Search not double-called blindly;
- web_fetch ambiguous response not blind duplicated;
- content_parse canonical reuse/idempotency concurrency;
- Job/session/page/artifact create uncertainty handled conservatively;
- Browser navigate/click/press/scroll/upload no duplicate action;
- close/cancel idempotent replay works;
- unknown outcome remains visible.

---

# F14 — Generic MCP client acceptance

Independent client:

```text
initialize
list tools
inspect schemas
call representative Web/Content/Browser/Job tools
reconnect
reuse BrowserSession handle
close
```

No dependency on own-agent private protocol required.

---

# F15 — REST client acceptance

Validate:

- generic OpenAPI/raw HTTP client;
- streaming Content;
- cursor opacity;
- Browser discriminated unions;
- Admin policy exact models;
- protected scopes;
- normalized errors;
- creation idempotency only where exact contract says it exists.

Generated SDK optional.

---

# F16 — Documentation/contract freeze gate

Before v0.8 accepted:

1. actual MCP = 28-tool contract;
2. actual REST = composite exact contract;
3. generated fixtures deterministic;
4. CI contract diff enabled;
5. own-agent descriptors/lifecycle/retry current;
6. generic MCP accepted;
7. admin self-lockout impossible by dynamic task policy;
8. no unresolved public contract drift;
9. all relevant release gates green;
10. `current.md`/versions updated factually from evidence.

After F16, v0.9 may harden/measure but should not casually redesign public contract.

---

# Forbidden shortcuts

Do not:

- freeze current accidental framework schema without target comparison;
- hand-edit golden JSON instead of generator/source model;
- keep old 27-tool assumption;
- omit `browser_scroll` and hide scrolling inside snapshot;
- mark all read-oriented tools auto-retry-safe ignoring cost/resource creation;
- let dynamic policy include/disable admin control plane;
- let Admin/Browser specialized routes diverge because common REST file is older;
- change agent retry semantics without Web Access contract update;
- make own-agent private integration mandatory for generic MCP client.
