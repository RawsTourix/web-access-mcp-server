# MCP facade design

## Статус документа

Канонический владелец **семантики agent-facing MCP facade** Web Access.

Exact public DTO/catalog:

```text
contracts/mcp-tools.md
```

Ключевые ADR:

- ADR-0021 — direct vs durable Job boundary;
- ADR-0022 — one semantic intent / stable execution class;
- ADR-0024 — cost/resource effects influence retry semantics;
- ADR-0025 — explicit Browser scroll capability.

Generated actual FastMCP schemas freeze-ятся в v0.8.

---

# 1. Purpose

MCP предоставляет LLM компактный, понятный и практически мощный interface к:

```text
Search
Retrieval
Content
Browser
Durable Jobs
```

Он не является копией REST и не раскрывает:

- SQL/Redis;
- raw provider protocols;
- Playwright/CDP internals;
- storage paths;
- worker topology;
- operator/admin controls;
- arbitrary code execution.

---

# 2. Language

Agent-facing тексты проекта преимущественно русские:

- tool descriptions;
- field descriptions;
- validation explanations;
- trusted error/hint messages.

Technical names/codes остаются английскими.

Это улучшает сопровождение без ухудшения понимания современными LLM.

---

# 3. Schema = agent UX

JSON Schema проектируется вручную как часть интерфейса LLM.

До вызова tool модель должна по `description` понять intent.

После получения full schema она должна без догадок понимать:

- поля;
- defaults;
- bounds;
- omission/null semantics;
- unions/cross-field rules;
- result/lifecycle;
- соседние tools.

Runtime validation обязательна даже после schema discovery.

---

# 4. Discovery descriptions

Description structure:

1. что делает tool;
2. когда его использовать / отличие от соседнего;
3. критичное lifecycle/side-effect ограничение, если есть.

Пример conceptual distinction:

```text
web_search
→ найти URL/источники

web_fetch
→ немедленно получить известные URL

web_fetch_job
→ создать durable retrieval batch

browser_snapshot
→ получить interactive refs

browser_content
→ прочитать rendered page как document
```

Search snippet не считается прочитанным target page.

---

# 5. One intent / one execution class

Canonical invariant:

```text
one tool
→ one primary semantic intent
→ one stable lifecycle/retry/resource class
```

Поэтому разделены:

```text
web_fetch / web_fetch_job
content_parse / content_parse_job
browser_tabs / browser_page_create / browser_page_close
```

Недопустим mixed discriminator, который превращает read/request-bound operation в Job/resource creation.

---

# 6. Batch rule

Batch-first применяется к независимым экземплярам одной операции:

```text
web_search queries[]
web_fetch urls[]
content_get items[]
content_parse content_ids[]
browser_close session_ids[]
job_get/job_cancel job_ids[]
```

Один элемент — список из одного элемента.

No `*_many` aliases.

Stateful sequential Browser transitions выполняются отдельными calls.

`browser_fill_form fields[]` — допустимый semantic compound action: несколько полей одной последовательной form-fill операции.

---

# 7. Result envelope

Expected application outcome:

```text
operation_id
outcome
data | null
error | null
warnings[]
hints[]
```

Common outcomes:

```text
succeeded
partial
failed
rejected
cancelled
unknown
```

`unknown` first-class для mutating/ambiguous operations.

Expected validation/quota/stale/session/provider failures возвращаются structured result, а не raw MCP protocol exception.

---

# 8. Warning / Hint / Error

```text
Warning
→ ограничение уже полученного результата

Hint
→ trusted recommendation следующего шага

Error
→ причина non-success
```

Web content не может само назначить trusted hint.

Hints не запускают инструменты автоматически.

Same-service hint может быть точным (`browser_may_be_required`), external L2 recommendation описывает capability class осторожно.

---

# 9. Bounded results

Большие payloads выносятся в Content:

```text
preview
+
ContentRef
+
opaque cursor when needed
```

No giant HTML/PDF/base64 screenshot.

---

# 10. Opaque resources

MCP использует stable handles:

```text
ContentRef
BrowserSessionRef
PageRef
SnapshotRef / ElementRef
JobRef
```

Client не строит routing/storage logic по внутреннему формату ID.

Ownership проверяется server-side.

BrowserSession/Job/Content lifecycle не привязан к одному MCP connection.

---

# 11. Retry semantics учитывает не только «чтение»

ADR-0024:

- billable upstream cost;
- создание Web Access resources;
- external/browser side effects;
- доказанная idempotency

влияют на trusted retry class.

Примеры:

```text
web_search
→ read-oriented, но provider может быть billable
→ no blind Agent retry after possible provider dispatch

web_fetch
→ создаёт ContentObjects
→ no blind retry after uncertain response

content_parse
→ idempotent только при доказанном canonical representation reuse

browser click/type/press/scroll/etc.
→ no blind retry after dispatch uncertainty
```

MCP annotations и own-agent retry metadata могут иметь разную детализацию; agent policy выбирает более консервативный доказуемый класс.

---

# 12. Current freeze-candidate catalog

**28 tools:**

## Web

```text
web_search
web_fetch
web_fetch_job
```

## Content

```text
content_get
content_parse
content_parse_job
```

## Browser lifecycle / observation / page state

```text
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
```

## Browser interaction

```text
browser_click
browser_fill_form
browser_type
browser_press
browser_hover
browser_drag
browser_scroll
browser_wait
browser_upload
```

## Jobs

```text
job_get
job_cancel
```

Exact fields/bounds/results: `contracts/mcp-tools.md`.

---

# 13. Web Search

`web_search`:

- queries 1..N batch;
- stable provider selection/default;
- common language/region/page/limit/safe-search/time profile;
- normalized search metadata;
- no page acquisition;
- no hidden provider fallback based on result «quality».

Provider field description must disclose that some providers may consume billable budget.

Service can retry internally only when provider/send evidence proves it safe under budget semantics.

---

# 14. Web Fetch

`web_fetch`:

```text
known HTTP(S) URLs
→ Safe Retrieval
→ raw ContentObject
→ L0
→ available request-bound L1
```

No Browser, no L2, no durable Job.

Because Content resources are created, a lost result is not treated as unconditional safe replay.

Large batch with durable lifecycle uses `web_fetch_job` explicitly.

---

# 15. Content

`content_get` reads an existing chosen Content representation using bounded chunks/cursors.

`content_parse` runs canonical L1 parser registry for existing immutable content.

No parser library ID in schema.

No OCR/VLM/LibreOffice.

Large durable parse uses `content_parse_job`.

---

# 16. Browser create/lifecycle

`browser_create` creates exactly one isolated BrowserSession + initial blank Page.

No URL input: navigation is explicit next operation.

`browser_get` reads lifecycle metadata.

`browser_close` idempotently cleans one/many independent sessions and is the own-agent lifecycle cleanup tool.

Server TTL/reaper remains final cleanup authority.

---

# 17. Browser page model

No hidden active-tab prerequisite.

Every page action uses explicit `page_id`.

```text
browser_tabs
→ read list

browser_page_create
→ create blank Page

browser_page_close
→ close explicit Page
```

Closing last remaining Page is rejected; close whole session with `browser_close`.

---

# 18. Snapshot and ElementRef

`browser_snapshot` returns bounded semantic/ARIA-oriented view and snapshot-scoped `element_ref`s.

Core MCP does not expose CSS/XPath.

Element action uses exact stale/identity validation from Browser design/ADR-0010.

No fuzzy retargeting to «похожий» DOM node.

---

# 19. Browser content vs snapshot

```text
browser_snapshot
→ interaction targeting

browser_content
→ rendered page as document-like Content
```

`browser_content` produces Content resources and therefore is not pure safe replay despite being non-mutating toward target website.

---

# 20. Browser scroll

ADR-0025 adds explicit:

```text
browser_scroll
```

Reason: bounded snapshot alone cannot reliably expose elements on long/lazy pages.

Scroll:

- explicit state transition;
- viewport-relative, not arbitrary coordinates;
- optional scrollable `element_ref` target;
- no auto-snapshot;
- may trigger lazy-loading/network;
- no blind retry after uncertain result.

Typical workflow:

```text
snapshot
→ scroll
→ snapshot
```

---

# 21. Browser form/keyboard actions

`browser_fill_form` sets typed values sequentially and **does not submit**.

First field failure stops further field execution in baseline:

```text
earlier fields → actual results
failed field → error
later fields → not_attempted
```

This makes partial mutation deterministic.

`browser_type` is eventful incremental text entry.

`browser_press` uses a structured key model rather than raw JavaScript shortcut expression.

---

# 22. Browser upload/download

Upload targets file input by ElementRef and uses owner-authorized ContentRefs, never server-local path.

Multiple files can be attached when the target control supports `multiple`; exact bound belongs to `contracts/mcp-tools.md`.

Downloads are artifacts caused by explicit browser actions/navigation and persisted as ContentRefs.

No standalone `browser_download` baseline.

Known direct file URL should use `web_fetch` where possible.

---

# 23. Browser events

`browser_events` is one bounded read log for:

```text
page lifecycle
dialogs
downloads
console
network failures
security blocks
browser lifecycle
```

Untrusted site text stays untrusted; event log is diagnostics, not durable business history.

---

# 24. Jobs

MCP creates only typed durable Jobs:

```text
web_fetch_job
content_parse_job
```

Generic:

```text
job_get
job_cancel
```

No public arbitrary `job_create(task,args)`.

Job survives disconnect and is not automatically cancelled at ordinary agent cycle end.

---

# 25. Admin/operator boundary

No normal MCP tools for:

- dynamic policy;
- provider/operator controls;
- quotas registry;
- worker drain;
- audit browsing;
- maintenance;
- raw parser registry.

REST/admin surface owns these capabilities.

---

# 26. Actual schema tests

For every tool actual FastMCP client discovery must verify:

- exact tool name;
- Russian tool description;
- every nested field description;
- required/default/null semantics;
- min/max/list bounds;
- discriminator/`oneOf`;
- unknown input fields rejected;
- no Context/private/provider/worker/storage fields;
- annotations;
- runtime validation agrees with generated schema.

Positive/negative fixtures validate actual emitted schema, not only Pydantic source model.

---

# 27. Compatibility

Before v0.8 freeze this catalog remains reviewed freeze candidate.

After freeze:

- removal/rename/semantic change → breaking candidate;
- additive tool → new unique semantic intent + execution-class review;
- bounds/default/required change → compatibility-sensitive;
- generated schema diff → CI visible;
- own-agent trusted descriptors updated alongside semantic changes.

Exact policy: `compatibility.md`.
