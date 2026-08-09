# External contract compatibility design

## Статус документа

Канонический владелец правил совместимости публичных REST/MCP contracts Web Access MCP.

---

# 1. Purpose

Web Access имеет два публичных machine-facing facade:

```text
REST /api/v1
MCP Streamable HTTP /mcp
```

До v0.8 схемы могут эволюционировать вместе с backend design. Начиная с v0.8 проект должен иметь формальные правила, по которым автоматические клиенты понимают, что обновление является additive, а что требует coordinated migration/new contract boundary.

---

# 2. Public contract surface

REST contract включает:

- HTTP methods/paths;
- auth requirements;
- request schemas;
- response/error envelopes;
- status semantics;
- ResourceRef shapes;
- cursor semantics;
- headers documented as contract;
- OpenAPI schema.

MCP contract включает:

- server transport/path;
- tool names;
- tool descriptions where agent discovery depends on semantics;
- input JSON Schema;
- output/result envelope semantics;
- resource handle shapes;
- errors/warnings/hints;
- tool annotations;
- state/lifecycle semantics.

Internal Python classes/SQL/Redis/worker protocols are not public contract.

---

# 3. Contract fixtures generated from running application

CI generates and canonicalizes:

```text
REST OpenAPI document
MCP tool catalog + actual input schemas + relevant metadata
```

Fixtures live versioned in repository or as golden test resources.

Tests compare **actual mounted FastAPI/FastMCP runtime output**, not hand-written Pydantic models only.

---

# 4. REST versioning

Public paths use:

```text
/api/v1
```

`v1` denotes external REST contract generation, not package version.

Before stable v1.0 release breaking changes may still occur during coordinated v0.x design, but v0.8 establishes candidate freeze and requires explicit compatibility review.

After v1.0, breaking REST change requires new contract boundary (e.g. `/api/v2`) or documented migration strategy.

---

# 5. MCP versioning

Ordinary tool names do not contain version suffixes.

Compatibility is maintained by stable semantic tool contract + generated schema fixture.

Breaking change to a tool requires one of:

- coordinated pre-v1 migration before freeze;
- introducing a new tool/contract while deprecating old one;
- future explicit MCP integration contract generation if unavoidable.

Do not silently change meaning while keeping same schema/name.

---

# 6. Additive changes

Usually backward-compatible when clients can ignore them:

- optional response field;
- new warning/hint code;
- new optional input field with safe/default omission semantics;
- new REST endpoint;
- new MCP tool with distinct intent;
- new provider/format capability that does not change existing semantics;
- new enum only if consumers are required/known to tolerate unknown values — otherwise treat enum expansion carefully.

Compatibility tests must reflect actual client behavior, not assume all JSON consumers ignore unknown enum values.

---

# 7. Breaking changes

Examples:

- rename/remove REST path;
- rename/remove MCP tool;
- rename/remove required/used field;
- optional field becomes required;
- type changes incompatibly;
- enum value semantics change;
- resource ID changes meaning;
- cursor becomes stateful/owner semantics change;
- tool switches from direct result to Job automatically;
- Browser action retry/outcome semantics change;
- error category/code changes meaning;
- authentication semantics change.

Breaking change requires explicit design/migration.

---

# 8. Descriptions are partly semantic contract

MCP descriptions are agent-facing discovery UX.

Minor wording/clarity corrections are allowed if semantic meaning unchanged.

Changing:

- when tool should be used;
- what it does not do;
- neighbor-tool distinction;
- field omission semantics

is considered semantic contract change and requires review even if JSON Schema identical.

---

# 9. Error taxonomy

Stable external error model separates:

```text
category
code
retryable
message
field/details
operation/outcome
```

New codes may be additive within known category if clients treat unknown code safely.

Changing retryability/meaning of existing code is compatibility-sensitive.

Internal exception class names never become required external code.

---

# 10. ResourceRef stability

Opaque handles keep stable public shape per resource class:

```text
content_id
browser_session_id
page_id
job_id
```

Clients never parse prefix for authorization/routing.

Internal ID generator may change only if all valid existing persisted resource IDs remain readable during retention/migration window.

---

# 11. Cursor stability

Cursor is opaque client-side.

Server cursor payload may evolve with explicit internal version marker.

Existing cursor versions must remain readable for at least resource/session contract lifetime or fail with explicit `cursor_version_unsupported`, not undefined parsing.

---

# 12. Contract manifest

Repository maintains a generated human/machine summary containing at least:

```text
REST API version
MCP tool names
canonical input schema fingerprints/fixtures
result envelope schema revision
resource/ref schema revision
error taxonomy revision
```

This is CI/release metadata, not necessarily a new MCP tool.

---

# 13. Schema fingerprint

Fingerprint can be SHA-256 of canonical JSON representation for CI/release comparison.

Fingerprint is diagnostic compatibility metadata, not substitute for semantic review.

Whitespace/property ordering do not affect canonical hash.

---

# 14. Deprecation

Before v1.0 deprecation period may be shorter but explicit.

After v1.0:

- deprecated REST field/path documented;
- deprecated MCP tool remains discoverable only for declared migration window if feasible;
- warning/deprecation metadata emitted where protocol supports it;
- removal scheduled in next breaking contract boundary.

Do not keep aliases forever solely for convenience; one canonical intent remains goal.

---

# 15. Database/runtime rolling compatibility

External compatibility is not enough.

Release supports rolling overlap through:

- expand-first DB migrations;
- policy schema compatibility;
- Job handler revision support;
- Browser worker/control-plane runtime revision checks;
- no migration requiring all processes atomically stop unless explicitly release-blocked.

---

# 16. Contract review gate

Every PR/change touching transport schema/tool description/error semantics must classify:

```text
internal only
additive public
behavioral compatible
breaking candidate
```

CI fixture diff shown to reviewer.

Breaking candidate cannot merge as accidental patch.

---

# 17. Generic clients

MCP facade must remain usable by generic conforming MCP clients.

Web Access cannot require `internet-search-bot` internal Python classes or manager functions for basic tool execution.

Agent-specific trusted presentation/lifecycle metadata lives agent-side.

---

# 18. Tests

- generated OpenAPI canonical fixture;
- actual FastMCP tool/schema fixture;
- semantic contract snapshot review;
- old representative client payloads against new server;
- old cursor versions;
- rolling worker/job handler revision;
- unknown additive response field tolerance in own clients;
- error taxonomy compatibility.

---

# 19. Non-goals

- automatic semantic compatibility proof;
- supporting every historical pre-v0.8 experiment forever;
- making internal worker RPC a public stable protocol;
- client SDK generation requirement.
