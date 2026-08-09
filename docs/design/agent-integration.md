# Integration with internet-search-bot

## Статус документа

Канонический владелец Web Access-side expectations для интеграции с собственным ИИ-агентом `RawsTourix/internet-search-bot` как builtin MCP service.

Документ **не копирует внутреннюю архитектуру агента**. Канонический agent-side contract остаётся в его `docs/design/contracts/builtin-mcp-service-contract.md`.

---

# 1. Boundary

```text
internet-search-bot Agent Runtime
→ MCP registry / ToolDispatcher
→ Streamable HTTP
→ Web Access MCP
```

Web Access является отдельным deployable service.

Он не импортирует код агента и не зависит от его conversation/runtime models.

---

# 2. Transport

Production builtin integration использует Streamable HTTP endpoint `/mcp` согласно agent-side builtin contract.

Service authentication передаётся transport/deployment configuration, а не MCP tool arguments.

MCP disconnect/reconnect:

- не закрывает BrowserSession;
- не отменяет durable Job автоматически;
- не удаляет ContentObject;
- не меняет owner.

---

# 3. Tool discovery workflow

Agent может видеть внешний MCP tool через последовательность:

```text
list tools
→ short name/description discovery
→ get full schema
→ call tool
```

Следствие для Web Access:

- первый абзац русскоязычного tool description должен однозначно объяснять intent;
- соседние tools явно разводятся по назначению;
- каждая input property имеет description;
- actual JSON Schema содержит machine-readable constraints;
- runtime validation остаётся обязательной.

---

# 4. Trusted metadata boundary

Web Access tool output **не определяет** agent-side:

- trusted presentation profile;
- permissions;
- cleanup binding;
- retry class;
- user-facing progress text.

Эти значения принадлежат trusted builtin registry агента.

Web Access предоставляет объективную operation/resource semantics, достаточную для такого trusted mapping.

---

# 5. Canonical capability mapping

Agent-side integration может классифицировать tools по stable semantics:

```text
web_search
web_fetch
content_get
content_parse
browser_*
job_*
```

Конкретная trusted metadata версия хранится со стороны агента и проходит compatibility tests против фактических Web Access schemas.

---

# 6. BrowserSession remote resource

`browser_create` возвращает opaque BrowserSession handle.

Agent trusted descriptor знает:

```text
resource_type = browser_session
cleanup_operation = browser_close
```

Web Access:

- проверяет owner handle на каждом вызове;
- обеспечивает idempotent explicit close;
- имеет собственный TTL/reaper;
- окончательно очищает browser process/resource независимо от agent cleanup.

Agent best-effort cleanup не является единственной защитой от orphan session.

---

# 7. Browser lifecycle owner

Agent может привязать BrowserSession к своему lifecycle owner (`cycle`, future run/task/session) согласно agent design.

Web Access получает только service principal/resource calls и не обязан понимать AgentCycle object.

Web Access internal owner remains authenticated principal; agent-side lifecycle owner is orchestration metadata outside service.

---

# 8. ContentRef

ContentObjects обычно не требуют per-AgentCycle cleanup hook.

Service retention policy управляет lifetime.

Agent может хранить opaque ContentRef в working/result context, но:

- handle не раскрывает storage key;
- owner validated server-side;
- expiration may make old handle unavailable;
- large content read through `content_get` cursor/bounds.

---

# 9. JobRef

Durable Job переживает MCP connection и AgentCycle boundary согласно explicit semantics.

Agent не должен автоматически cancel every Job только потому, что один cycle завершился, если trusted policy не определяет это отдельно.

Lifecycle:

```text
create durable mode
→ JobRef
→ job_get
→ optional job_cancel
```

Web Access server-side retention/reconciliation authoritative.

---

# 10. Retry mapping

Agent-side trusted execution semantics должны согласовываться с Web Access behavior.

Examples:

```text
web_search      safe/read-oriented
web_fetch       safe/read-oriented
content_get     safe
content_parse   safe/idempotent relative immutable source/revision where applicable
browser_get     safe
browser_snapshot safe/read
browser_close   idempotent cleanup
browser_click/fill/press/navigate  never blind automatic retry after uncertain dispatch
job_get         safe
job_cancel      idempotent cancellation request
```

Exact agent descriptor version reviewed with actual schemas.

---

# 11. `unknown` outcome

Browser mutating action can return/normalize `unknown` when service cannot prove whether side effect happened.

Agent must not transform it into automatic duplicate call.

Recommended orchestration:

```text
unknown
→ safe observation/status/snapshot where possible
→ infer current state only from evidence
→ ask user if consequential ambiguity remains
```

Web Access structured result should include enough code/context for this behavior without prescribing UI text.

---

# 12. Structured hints

Web Access hints are trusted **service-generated codes/messages**, distinct from untrusted web content.

Agent may use them in reasoning/presentation mapping.

Examples:

```text
browser_may_be_required
advanced_processing_may_be_required
snapshot_refresh_recommended
processing_requires_job
session_expiring
```

Hint is recommendation, not imperative automatic action.

Page/document text cannot create a trusted hint merely by containing similar text.

---

# 13. Progress

Web Access may emit technical MCP progress only where protocol/tool execution benefits.

Agent remains owner of canonical user-facing progress.

Useful stable semantic metadata from tool/result includes:

- capability/tool;
- URL/domain where safe;
- provider;
- phase/outcome;
- resource/job IDs;
- progress counts for durable jobs.

Web Access does not generate Telegram/Web-specific phrases.

---

# 14. Presentation profile compatibility

Agent can show semantic phrases such as:

```text
Ищу в интернете…
Читаю страницы…
Открываю сайт в браузере…
```

but these strings are agent-side trusted presentation profiles.

Web Access only guarantees stable tool identities/semantics that allow mapping.

Renaming tool/intent therefore has integration compatibility impact even if backend unchanged.

---

# 15. Service unavailable/restart

Agent must tolerate Web Access endpoint temporary failure as optional builtin capability failure according its runtime policy.

Web Access restart semantics:

- request-bound operation lost according normal transport/outcome rules;
- durable Jobs recover from DB/worker model;
- Browser Worker session resources are independent of Control Plane MCP connection, but actual owning Browser Worker loss can mark session lost;
- Content remains in durable storage.

---

# 16. Schema compatibility

Web Access v0.8 maintains generated MCP schema fixture.

Agent integration acceptance compares:

- expected tool names;
- input schema compatibility;
- resource/result shapes relevant to trusted descriptor;
- retry/remote-resource semantics.

Agent must not infer compatibility only from service package version string.

---

# 17. Cross-repository testing

Responsibilities:

## Web Access repository

- standard MCP client connect/discovery/call tests;
- actual schema fixtures;
- lifecycle/retry behavior tests;
- generic-client compatibility.

## Agent repository

- trusted builtin registry descriptor tests;
- ToolDispatcher mapping;
- presentation profile;
- lifecycle owner/cleanup;
- `unknown` behavior;
- degraded/unavailable server handling.

## Coordinated integration acceptance

Use pinned refs/controlled test deployment for end-to-end verification without creating runtime code dependency between repositories.

---

# 18. Generic MCP client compatibility

All essential Web Access MCP tools work without `internet-search-bot` manager functions.

A generic client can:

- discover/call tools;
- manage BrowserSession explicitly;
- poll/cancel Job;
- read Content.

What generic client does not get automatically:

- agent-specific pretty progress;
- agent lifecycle auto-cleanup;
- trusted local permission/budget mapping.

---

# 19. Security

- external bearer/service credential never appears in LLM arguments;
- agent user/session identifier is not trusted unless conveyed through authenticated/delegated identity contract;
- Browser/Content/Job ownership enforced server-side;
- tool output cannot escalate agent trusted metadata;
- web content remains untrusted;
- cleanup only operates owner-authorized resource.

---

# 20. Acceptance matrix

Builtin integration must verify:

1. Streamable HTTP connect/discovery/reconnect;
2. schema fixture match;
3. Russian descriptions sufficient for agent discovery;
4. `web_search`/`web_fetch` direct flow;
5. ContentRef chunk flow;
6. durable Job creation/poll/cancel;
7. Browser create/use/close;
8. AgentCycle completion triggers bounded browser cleanup when configured;
9. service cleanup/TTL works even if agent disappears;
10. Browser worker loss becomes explicit lost resource;
11. mutating response loss does not produce duplicate action;
12. `unknown` propagated;
13. generic fallback presentation for unrecognized future tool;
14. Web Access outage does not destroy unrelated Agent Runtime;
15. secrets absent from LLM context/tool schemas.

---

# 21. Non-goals

- copying agent Dispatcher implementation into this repo;
- storing agent conversations;
- defining Telegram/Web UI;
- agent authorization database;
- hard dependency on one LLM/provider;
- making Web Access useful only to own agent.
