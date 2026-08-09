# Integration with internet-search-bot

## Статус

Канонический владелец Web Access-side expectations для интеграции с `RawsTourix/internet-search-bot` как builtin MCP service.

Agent-side canonical contract остаётся в его `docs/design/contracts/builtin-mcp-service-contract.md`.

Web Access не копирует/импортирует Agent Runtime.

---

# 1. Boundary

```text
internet-search-bot Agent Runtime
→ MCP registry / ToolDispatcher
→ Streamable HTTP
→ Web Access MCP
```

Service independently deployable.

No direct REST bypass for normal builtin tool execution baseline.

---

# 2. Transport/lifecycle

Production integration uses `/mcp` Streamable HTTP.

Authentication belongs transport/deployment, not tool args.

MCP disconnect/reconnect:

- does not close BrowserSession;
- does not cancel Job;
- does not delete ContentObject;
- does not change owner.

---

# 3. Agent discovery model

Agent workflow:

```text
mcp_list_tools
→ tool name + description
→ mcp_get_tool_schema
→ full input schema
→ mcp_call_tool
```

Therefore Web Access must provide:

- Russian discovery descriptions with clear intent;
- neighbor-tool distinctions;
- every nested property description;
- machine-readable bounds/unions;
- runtime validation independent of LLM compliance.

Exact current target: `contracts/mcp-tools.md`.

---

# 4. Trusted metadata boundary

Tool output cannot appoint its own:

- agent permission;
- trusted presentation profile;
- retry class;
- lifecycle cleanup binding;
- user-facing progress string.

These live in agent trusted builtin registry.

Web Access supplies objective stable semantics/resources/outcomes enabling that mapping.

---

# 5. Current catalog compatibility

Current freeze candidate = **28 tools**.

Agent descriptor compatibility checks exact names/semantics from:

```text
mcp.md
contracts/mcp-tools.md
ADR-0021/0022/0024/0025
```

Unknown future/additive tool gets generic safe presentation until explicitly trusted; it cannot inherit privileged lifecycle/retry profile by name similarity.

---

# 6. Remote resources

## BrowserSession

`browser_create` returns opaque handle.

Agent trusted descriptor maps:

```text
resource_type = browser_session
cleanup_operation = browser_close
```

Agent may attach resource to cycle/run/session owner.

Web Access sees authenticated principal/resource calls, not AgentCycle object.

Server TTL/reaper remains final cleanup authority.

## Content

Content generally not per-AgentCycle cleanup.

Lifetime controlled by Web Access retention/quota.

Agent stores opaque refs/cursors only.

## Job

Durable Job survives AgentCycle/MCP disconnect.

Agent does not auto-cancel every Job on cycle completion.

Explicit lifecycle:

```text
web_fetch_job/content_parse_job
→ JobRef
→ job_get
→ optional job_cancel
```

---

# 7. Retry mapping — cost/resource aware

ADR-0024 replaces old simplistic “read tool = safe retry” mapping.

Trusted Agent semantics must distinguish:

## Pure safe observations

Examples:

```text
content_get
browser_get
browser_snapshot
browser_tabs
browser_events
browser_wait
job_get
```

Safe subject to ordinary deadline/capacity policy.

## `web_search`

Read-oriented but selected provider can be billable.

```text
possible provider dispatch/cost
→ no blind Agent-level automatic repeat after lost result
```

Service may internally retry only pre-dispatch/provably-safe phases according provider/budget evidence.

## `web_fetch`

Creates raw/derived Content resources.

```text
lost result after acquisition/resource creation
→ no blind duplicate Agent call
```

## `content_parse`

Can use idempotent Agent class only after implementation proves canonical compatible representation reuse under concurrent/replay tests.

## Resource creation

```text
web_fetch_job
content_parse_job
browser_create
browser_page_create
browser_content
browser_screenshot
```

Conservative after uncertain creation unless explicit same-operation/idempotency evidence exists.

## Browser stateful actions

```text
browser_navigate
browser_click
browser_fill_form
browser_type
browser_press
browser_hover
browser_drag
browser_scroll
browser_upload
```

never blind automatic repeat after dispatch uncertainty.

Worker action ledger/status recovery first tries to recover **same action**, not issue a new action.

## Cleanup/cancel

```text
browser_close
browser_page_close
job_cancel
```

idempotent according exact semantics.

---

# 8. `unknown` outcome

If Browser/resource operation outcome cannot be proven:

```text
unknown
→ safe observation/status/snapshot where possible
→ infer only from evidence
→ ask user when consequential ambiguity remains
```

Agent must not collapse `unknown` into failed/not-executed.

---

# 9. Browser exploration UX

Bounded snapshot intentionally does not reveal infinite UI at once.

Canonical long/lazy page flow:

```text
browser_snapshot
→ agent sees current refs/truncation/state
→ browser_scroll
→ browser_snapshot
```

Scroll is explicit so Agent can display/trace that page state changed.

No hidden scroll inside snapshot.

---

# 10. Form/key/upload UX

Agent schema/presentation assumes exact contract:

- `browser_fill_form` sequential fail-fast;
- prior fields may remain changed;
- later fields `not_attempted` after first failure;
- no automatic submit;
- `browser_press` structured named/character key + modifiers;
- multi-file upload uses ContentIds and requires actual multiple-capable control.

Agent should reason from per-field/action results, not assume atomic browser DOM rollback.

---

# 11. Structured hints

Trusted service-generated hints are distinct from untrusted web content.

Examples:

```text
browser_may_be_required
advanced_processing_may_be_required
snapshot_refresh_recommended
processing_requires_job
session_expiring
```

Hint = recommendation, not automatic command.

Page/document text cannot manufacture trusted hint by containing same phrase.

---

# 12. Pretty progress

Agent owns user-facing progress/presentation.

Possible trusted mapping:

```text
web_search       → Ищу в интернете…
web_fetch        → Читаю страницы…
browser_navigate → Открываю сайт…
browser_snapshot → Анализирую интерфейс…
browser_scroll   → Прокручиваю страницу…
browser_click    → Взаимодействую со страницей…
web_fetch_job    → Запускаю фоновое получение страниц…
job_get          → Проверяю прогресс…
```

Exact UI wording remains agent-side.

Web Access returns stable provider/URL/domain/resource/progress metadata, not Telegram/Web-specific prose.

---

# 13. Service restart/unavailability

Agent tolerates optional builtin service failure according its runtime policy.

Web Access restart semantics:

- request-bound in-flight call follows outcome/retry evidence;
- Jobs recover through DB/outbox/worker lifecycle;
- BrowserSession independent of MCP connection but owning Browser Worker loss can mark it `lost`;
- Content remains durable according storage/lifecycle.

Web Access outage must not destroy unrelated Agent Runtime.

---

# 14. Contract freeze/compatibility

In v0.8 Web Access generates actual MCP golden fixture.

Agent coordinated acceptance compares:

- exact 28 names;
- schema compatibility;
- resources/results used by trusted descriptor;
- retry/cost/resource class;
- cleanup mapping;
- progress presentation mapping.

Do not infer compatibility from package version string alone.

---

# 15. Cross-repository tests

## Web Access repo

- generic MCP connect/discovery/call;
- actual schemas;
- retry/lifecycle fault tests;
- generic-client compatibility.

## Agent repo

- builtin registry descriptors;
- Dispatcher routing/retry;
- presentation profiles;
- remote-resource ownership/cleanup;
- `unknown` handling;
- degraded/unavailable service.

## Coordinated acceptance

Pinned refs/test deployment without runtime code dependency between repositories.

Scenarios include:

1. Search→Fetch;
2. Search→Browser;
3. long page Snapshot→Scroll→Snapshot;
4. Browser form/key/upload;
5. cleanup at Agent lifecycle end;
6. server TTL if Agent disappears;
7. Browser worker lost;
8. billable Search response loss no duplicate paid Agent call;
9. web_fetch response loss no blind duplicate acquisition;
10. mutating Browser response loss no duplicate action;
11. durable Job polling/cancel;
12. service outage leaves unrelated agent functionality alive.

---

# 16. Generic MCP client

All essential tools work without own-agent manager functions.

Generic client can:

- discover/call;
- manage BrowserSession explicitly;
- read Content;
- create/poll/cancel Jobs.

It simply lacks agent-specific pretty progress, lifecycle auto-cleanup and trusted local policy mapping.

---

# 17. Security

- bearer/service credential never enters LLM tool args;
- user/session ID not trusted unless authenticated/delegated through proper identity contract;
- resource owner enforced server-side;
- output cannot escalate trusted registry metadata;
- web content untrusted;
- cleanup owner-authorized;
- billable/retry semantics cannot be weakened by model-generated argument.

---

# 18. Non-goals

- copy Agent Dispatcher into Web Access;
- store agent conversations;
- define Telegram/Web UI;
- build agent authorization DB;
- hard-depend on one LLM/provider;
- make Web Access useful only to own agent.
