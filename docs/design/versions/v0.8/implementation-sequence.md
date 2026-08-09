# v0.8 — Implementation sequence

## Назначение

Порядок freeze/stabilization внешних contracts и own-agent integration.

> Нельзя сначала сохранить golden fixture, а потом объявить случайную текущую схему правильной. Сначала semantic review/fix, затем freeze.

---

# F0 — Baseline inventory

Generate temporary reports from actual service:

- all REST routes/operationIds/schemas;
- all MCP tools/descriptions/input schemas/annotations;
- external error codes;
- ResourceRef/cursor schemas;
- own-agent expected trusted tool list.

Compare with design and classify mismatches.

No golden gate yet.

---

# F1 — Contract generator tooling

Create deterministic generator, e.g.:

```text
scripts/generate_contracts.py
```

Outputs:

```text
contracts/manifest.json
contracts/rest/openapi-v1.json
contracts/mcp/tools-v1.json
contracts/common/error-taxonomy-v1.json
contracts/common/resource-schemas-v1.json
```

Run twice → byte-identical output.

Canonicalizer must not hide meaningful difference.

---

# F2 — Common result/error/resource review

Before REST/MCP individually:

- OperationResult envelope;
- outcomes incl. partial/unknown;
- Warning/Hint;
- error category/code/retryability;
- ContentRef/BrowserSession/Page/Job refs;
- cursor version/error.

Fix inconsistency application-side first.

---

# F3 — REST semantic cleanup

Review every implemented `/api/v1` route against `rest-api.md`:

- names;
- methods;
- resource/action structure;
- validation envelope;
- auth;
- status mapping;
- operationId;
- bounded bodies/results;
- no infrastructure leakage.

Remove/rename pre-freeze mistakes now with migration note if any test client exists.

---

# F4 — REST schema quality

Actual OpenAPI tests verify:

- descriptions;
- examples;
- limits/defaults/enums;
- security schemes;
- common errors;
- binary/stream endpoints documented;
- admin endpoints protected.

Then write candidate `openapi-v1.json`.

---

# F5 — MCP catalog cleanup

Make actual registered tools exactly ADR-0022 catalog.

Remove exploratory aliases/mixed variants.

Ensure:

- no `execution=direct|durable`;
- no mutating `browser_tabs` commands;
- no `browser_select/check` duplicates baseline;
- page create/close explicit;
- no internal/admin tools.

---

# F6 — MCP description/schema audit

For all 27 tools:

- Russian tool description;
- Russian every field/nested description;
- neighbor-tool distinction;
- exact limits;
- defaults/null;
- `additionalProperties=false` where appropriate;
- one execution class;
- annotations;
- bounded result contract.

Run actual MCP client schema validation with positive/negative examples.

---

# F7 — Generate MCP fixture

Generate `tools-v1.json` from actual FastMCP runtime.

Canonicalize only SDK-volatile non-semantic metadata through explicit normalizer.

Add semantic assertions separately so wording/meaning regression is caught even when schema shape same.

---

# F8 — Compatibility manifest/fingerprints

Create manifest and hashes.

Manifest generation fails if component artifact missing/inconsistent version.

Package version is recorded informationally but not used as sole compatibility decision.

---

# F9 — Own-agent trusted descriptor mapping

In coordinated `internet-search-bot` work:

- register Web Access as builtin Streamable HTTP service;
- exact tool bindings;
- retry/side-effect classes;
- trusted presentation profiles;
- BrowserSession remote resource cleanup mapping;
- Job resource behavior;
- timeout/budget profiles.

Agent changes remain in agent repo.

---

# F10 — Agent discovery/schema tests

Verify actual workflow:

```text
mcp_list_tools
→ descriptions
→ mcp_get_tool_schema
→ correct arguments
→ mcp_call_tool
```

Focus on neighbor confusion:

- search vs fetch;
- fetch vs fetch_job;
- snapshot vs content;
- direct parse vs parse_job;
- browser tabs vs page create/close.

---

# F11 — Browser lifecycle integration

Agent end-to-end:

```text
browser_create
→ Agent registers handle
→ actions
→ cycle/resource cleanup hook
→ browser_close
```

Fault tests:

- agent disconnect;
- Web Access Control Plane reconnect;
- Browser Worker loss;
- cleanup endpoint unavailable;
- cleanup timeout;
- service TTL/reaper final cleanup.

Final agent answer must not be invalidated solely by cleanup failure per agent contract.

---

# F12 — `unknown` integration

Inject response loss after Browser mutating action.

Prove:

- service returns/recovers same action result where possible;
- unresolved becomes `unknown`;
- Agent Dispatcher does not auto-repeat;
- safe snapshot/status can follow;
- user-facing result preserves ambiguity when evidence insufficient.

---

# F13 — Durable Job integration

Own-agent test:

```text
web_fetch_job/content_parse_job
→ JobRef
→ disconnect/reconnect
→ job_get
→ result ContentRef
```

Cancel test.

No automatic Job cancellation at ordinary AgentCycle end unless explicitly configured by future agent policy.

---

# F14 — Progress/presentation

Agent-side trusted presentation for Web Access tools validated:

- semantic progress;
- no raw MCP tool name only where profile exists;
- generic fallback for unknown future tool;
- page/tool output cannot inject trusted UI text.

Web Access remains UI-agnostic.

---

# F15 — Generic MCP client suite

Without own agent:

- authenticate;
- discovery;
- web search/fetch/content;
- Browser lifecycle;
- Job lifecycle;
- reconnect.

This is separate release gate from own-agent integration.

---

# F16 — REST representative client suite

Script/client flows:

- search;
- retrieval/content stream;
- Browser session/actions/content;
- durable Job;
- admin status/policy with correct scope;
- error parsing.

Generated client optional; raw HTTP contract enough.

---

# F17 — Old/request compatibility fixtures

Keep representative valid request corpus from pre-freeze implementation.

Candidate service must accept them unless explicit intentional pre-v1 breaking correction documented.

Cursor compatibility tests included.

---

# F18 — Enable contract CI gate

After semantic freeze accepted:

CI regenerates contracts and fails on diff unless committed expected artifacts change.

PR must classify diff:

```text
additive
compatible behavior
breaking candidate
```

No automatic fixture regeneration in CI that silently accepts diff.

---

# F19 — Documentation consistency sweep

Search repository for old exploratory public interfaces:

```text
execution=direct|durable
mixed browser_tabs commands
browser_select/check baseline tools
old names/limits
```

Update/delete contradictions.

Version docs may retain historical superseded decision only if explicitly marked as such.

---

# F20 — Cross-repo release gate

Run pinned Web Access candidate + pinned agent candidate in controlled environment.

Required zero live public/provider dependencies where deterministic fake/local fixtures suffice.

Then optional manual live smoke for SearXNG/public web as non-default gate.

Record compatible commit/ref pair in release evidence.

---

# F21 — Freeze acceptance

Before v0.8 completion:

- generated artifacts committed;
- exact MCP catalog = ADR-0022;
- OpenAPI reviewed;
- error/resource/cursor revisions recorded;
- own-agent descriptors updated/tested;
- generic client passes;
- contract CI gate active;
- docs contradiction search clean.

---

# Forbidden shortcuts

Do not:

- freeze generated schema without semantic review;
- copy agent presentation metadata into Web Access output;
- add `service_info` MCP tool only to expose package version if standard discovery/contract manifest suffices;
- require agent-specific manager functions for generic MCP operation;
- automatically approve golden diff;
- keep aliases indefinitely merely to avoid fixing pre-v1 mistake;
- make tool retry class argument-dependent;
- hide breaking change inside description-only edit.
