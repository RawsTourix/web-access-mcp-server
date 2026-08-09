# v0.8 — REST/MCP & Agent Integration Stabilization

## Статус

`ready for implementation`

v0.8 не добавляет новую backend capability. Она превращает фактически реализованные v0.1–v0.7 facades в **явно зафиксированную внешнюю contract line** и проверяет интеграцию с собственным ИИ-агентом.

---

# 1. Цель

После v0.8 должны существовать reviewed/generated/golden executable contracts:

```text
REST /api/v1
MCP 28-tool freeze candidate
common result/error/resource models
policy/admin models
own-agent trusted integration metadata
```

и CI должен отличать compatible change от breaking/semantic drift.

---

# 2. Prerequisites

- accepted v0.1–v0.7;
- all current component/ADR decisions implemented;
- `../../compatibility.md`;
- `../../agent-integration.md`;
- `../../rest-api.md`;
- `../../mcp.md`;
- `../../contracts/README.md`;
- `../../contracts/common-models.md`;
- `../../contracts/mcp-tools.md`;
- `../../contracts/rest-api-v1.md`;
- `../../contracts/browser-api-v1.md`;
- `../../contracts/policy-models.md`;
- `../../contracts/admin-api-v1.md`;
- ADR-0021/0022/0024/0025;
- agent-side builtin MCP service contract in `internet-search-bot`.

---

# 3. Non-goals

- new Search/Browser/Content/Job feature;
- L2 processing;
- arbitrary REST/Playwright expansion;
- auth architecture rewrite;
- changing accepted lifecycle/security because schema generation is inconvenient;
- generic operator MCP tools.

If implementation cannot reproduce exact contract, resolve as explicit Design/ADR review, not silent divergence.

---

# 4. Common public models

Freeze generated equivalents of `contracts/common-models.md`:

- `PublicOperationResult`;
- `PublicError`;
- `PublicWarning`;
- `StructuredHint`;
- `BatchItemResult`;
- ResourceRef variants;
- JobProgress;
- cursor/page/snapshot public metadata where applicable.

Verify serialization equality/compatibility between REST and MCP projections where concepts are intentionally shared.

---

# 5. MCP freeze

Current target = **28 tools** from `contracts/mcp-tools.md`.

Key stabilized refinements:

- direct vs Job creation separate;
- one stable execution/lifecycle class per tool;
- resource/cost-aware retry metadata (ADR-0024);
- explicit `browser_scroll` (ADR-0025);
- fail-fast form semantics;
- structured key+modifiers;
- multi-file ContentRef upload;
- no active-tab hidden state;
- no CSS/XPath/raw JS/admin tools.

Actual FastMCP schema/annotations are authoritative generated artifact after passing target contract tests.

---

# 6. REST freeze

Target exact REST is composite:

```text
contracts/rest-api-v1.md
+ contracts/browser-api-v1.md
+ contracts/policy-models.md
+ contracts/admin-api-v1.md
```

Generated OpenAPI must represent the union without conflicting duplicate definitions.

Specialized contract owns its namespace when more specific than common REST baseline.

---

# 7. Generated contract artifacts

Implementation should generate deterministic artifacts, e.g.:

```text
contracts/generated/openapi-v1.json
contracts/generated/mcp-tools-v1.json
contracts/generated/public-models-v1.json
```

Exact repository path may follow project convention, but generation source must be deterministic/documented.

Do not hand-maintain golden JSON separately from actual application registration.

---

# 8. Compatibility CI

CI classifies at least:

```text
endpoint/tool removal/rename
required field added
field removed
bound tightened/loosened
new enum value
changed default
changed union/discriminator
resource/result shape change
annotation/retry semantic change
policy schema change
```

Generated diff visible in PR; some behavioral changes require human classification even if JSON shape additive.

---

# 9. Own-agent integration

Web Access remains ordinary MCP service transport-wise but is registered as trusted builtin in agent registry.

Agent trusted metadata maps:

```text
semantic presentation
retry/resource/cost class
remote resource creation
lifecycle cleanup tool
progress rendering
```

Web Access never imports agent runtime code.

Agent does not bypass MCP to hidden Web Access internals for normal tool execution.

---

# 10. BrowserSession lifecycle mapping

Agent recognizes BrowserSession handle as remote resource.

Cleanup:

```text
owner agent cycle/session terminal
→ best-effort browser_close
```

Server TTL/reaper final authority.

MCP disconnect ≠ Browser close.

Job not automatically cancelled at agent cycle end.

Content survives cycle subject to service retention.

---

# 11. Pretty progress mapping

Trusted presentation can distinguish:

```text
web_search       → поиск
web_fetch        → чтение известных сайтов
browser_navigate → открытие/переход
browser_snapshot → анализ интерфейса
browser_scroll   → прокрутка страницы
browser_click    → взаимодействие
web_fetch_job    → durable batch
job_get          → background progress
```

User-facing text belongs to Agent Dispatcher/UI, not arbitrary MCP result text.

Arguments/results provide trusted provider/URL/domain/resource metadata after redaction/policy.

---

# 12. Retry integration tests

Cross-repo acceptance proves:

- billable `web_search` lost response does not cause blind second Agent-level paid call;
- `web_fetch` lost result does not cause blind duplicate Content acquisition;
- `content_parse` idempotent class enabled only after canonical reuse tests;
- Job/session/page/artifact creation uncertainty not blindly replayed;
- Browser click/press/scroll/etc. uses same-action recovery/unknown, not new call retry;
- cleanup close/cancel idempotent cases remain retryable as designed.

---

# 13. Generic MCP compatibility

Test independent generic MCP client:

```text
initialize
list tools
inspect schemas
call representative tools
receive structured results
reconnect
reuse BrowserSession handle
close
```

Own-agent presentation extensions optional outside transport contract.

---

# 14. REST compatibility consumers

Validate:

- raw HTTP/OpenAPI client;
- generated client feasibility if used;
- opaque cursors/resources;
- streaming Content;
- Browser typed unions;
- Admin policy typed schemas;
- normalized errors.

SDK generation optional; stable OpenAPI mandatory.

---

# 15. Required tests

## MCP

- exact 28 names;
- Russian descriptions;
- all nested field descriptions;
- bounds/defaults/oneOf;
- annotations + own-agent retry descriptors;
- no private fields;
- scroll/form/key/upload fixtures;
- structured result/error.

## REST

- exact normal routes;
- exact Browser specialized routes;
- exact Admin routes/policy models;
- operationId/security;
- streaming;
- no infrastructure leakage;
- admin auth/self-lockout prevention.

## Compatibility

- golden diff;
- intentional additive fixture;
- intentional breaking fixture;
- mixed software/policy schema compatibility;
- old client scenario where supported.

## Agent

- discovery;
- Search→Fetch;
- Search→Browser;
- long/lazy page `snapshot→scroll→snapshot`;
- Browser cleanup;
- durable Job lifecycle;
- response-loss no duplicate side effects/cost.

---

# 16. Definition of Done

v0.8 complete only if:

1. Generated OpenAPI equals reviewed composite REST target or design changed explicitly.
2. Actual FastMCP schemas equal reviewed 28-tool target.
3. Common public model serialization stable.
4. Compatibility CI reports meaningful diffs.
5. ADR-0024 retry/cost/resource semantics reflected in own-agent trusted descriptors.
6. Browser scroll/form/key/upload semantics pass actual schema + e2e tests.
7. Dynamic policy rejects admin self-lockout model and Admin REST remains recoverable by authorized principal.
8. Own-agent builtin integration passes lifecycle/progress/retry/resource tests.
9. Generic MCP client passes representative protocol suite.
10. No public schema contains secrets/internal routing/storage/Playwright fields.
11. Full relevant release gates green.

After this point external contract changes require compatibility discipline; v0.9 focuses on hardening, not redesign.
