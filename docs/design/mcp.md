# MCP facade design

## Статус документа

Канонический владелец agent-facing MCP facade Web Access.

Exact freeze candidate tool catalog зафиксирован ADR-0022.

REST/backend capabilities описываются отдельно; MCP не является копией REST.

---

# 1. Purpose

MCP предоставляет LLM компактный, однозначный и практически мощный interface к Web Access:

```text
Search
Retrieval
Content
Browser
Durable Jobs
```

Facade должен позволять агенту выполнить почти любой типичный web workflow, не раскрывая:

- internal provider API;
- SQL/Redis;
- Playwright implementation;
- filesystem/S3 keys;
- worker topology;
- admin controls.

---

# 2. Language

Agent-facing тексты по умолчанию на русском:

- tool descriptions;
- field descriptions;
- validation explanations;
- trusted service error/hint messages.

Technical identifiers остаются английскими:

```text
web_fetch
content_id
browser_session_id
error.code
```

---

# 3. JSON Schema = agent UX

Schema проектируется намеренно для LLM, а не автоматически принимается как случайный результат Python signature.

LLM должна понять:

- что делает tool;
- когда его использовать;
- чем он отличается от соседних;
- что означает каждое поле;
- какие ограничения действуют;
- какой result/lifecycle ожидать.

Runtime server-side validation остаётся обязательной.

---

# 4. Discovery-first descriptions

Tool description сначала отвечает на вопрос:

> Для чего нужен этот инструмент?

Затем, где важно:

> Когда использовать его вместо соседнего?

Например:

```text
web_search
→ найти URL/источники

web_fetch
→ немедленно получить известные URL по HTTP

web_fetch_job
→ создать durable batch Job для большого набора URL

browser_*
→ работать с реальным stateful browser runtime
```

Search snippet не описывается как прочитанная страница.

---

# 5. Field descriptions

Каждое public input property и nested property имеет русскоязычное описание:

- смысл;
- формат/единицы;
- omission/default;
- ограничения;
- связь с другими полями.

Unknown fields запрещены.

---

# 6. Machine-readable constraints

Где возможно использовать actual JSON Schema:

```text
minItems/maxItems
minLength/maxLength
minimum/maximum
enum
format
discriminator/oneOf
required
```

Prose не заменяет machine-readable invariant.

Cross-field runtime validation и actual generated schema должны согласовываться.

---

# 7. Null / omitted / default

Optional field не создаётся без ясной semantics.

Если omission означает configured default — это прямо написано.

`null` не используется как случайное третье состояние.

---

# 8. Agent-facing enums

Enum представляет stable Web Access concept, не provider/library implementation.

Пример:

```text
safe_search = off | moderate | strict
```

Не выдавать:

- Yandex raw `lr`;
- Playwright locator strategy;
- internal parser IDs;
- worker IDs как schema enum.

---

# 9. Result envelope

Expected application outcomes возвращаются structured result:

```text
operation_id
outcome
data | null
error | null
warnings[]
hints[]
```

Common outcomes включают:

```text
succeeded
partial
failed
rejected
cancelled
unknown
```

Exact aggregate semantics следуют `application-contracts.md`.

---

# 10. Protocol error vs application error

MCP protocol/transport error используется только если tool call невозможно корректно представить как application operation.

Ожидаемые failures — invalid URL, unsupported content, quota, stale ref, expired session, provider failure — возвращаются structured application result.

Это позволяет LLM исправить вызов.

---

# 11. Warning / Hint / Error

```text
Warning
→ ограничение уже полученного результата

Hint
→ возможный следующий шаг

Error
→ причина non-success outcome
```

Не объединять всё в один `message`.

Web content не может само назначить trusted hint.

---

# 12. Structured hints

Примеры trusted codes:

```text
browser_may_be_required
advanced_processing_may_be_required
processing_requires_job
snapshot_refresh_recommended
session_expiring
alternative_representation_available
```

Для capability того же Web Access точный related tool может быть указан, например:

```text
processing_requires_job
→ web_fetch_job
```

Hint не вызывает инструмент автоматически.

---

# 13. Result size

MCP result всегда bounded.

Большие данные:

```text
preview
+
ContentRef
+
opaque cursor
```

Никакого giant HTML/PDF text/base64 screenshot в одном result.

---

# 14. Opaque resources

MCP использует:

```text
ContentRef
BrowserSessionRef
PageRef
JobRef
```

Handle не раскрывает internal routing/storage.

Ownership проверяется server-side при каждом вызове.

---

# 15. Tool naming

- lowercase snake_case;
- semantic capability;
- no provider name для provider-agnostic operation;
- no ordinary version suffix;
- no `*_many` для batch-first operations.

Namespaces:

```text
web_*
content_*
browser_*
job_*
```

---

# 16. One stable execution class per tool

ADR-0022 invariant:

```text
one tool
→ one primary intent
→ one retry/side-effect/resource class
```

Discriminator разрешён только между variants одной execution semantics.

Допустимо:

```text
browser_navigate(url|back|forward|reload)
```

Недопустимо:

```text
web_fetch(direct|create Job)
browser_tabs(list|create|close)
```

Это особенно важно для trusted Agent Dispatcher metadata.

---

# 17. Batch rule

Batch используется для независимых экземпляров одной операции:

```text
web_search queries[]
web_fetch urls[]
content_get items[]
browser_close session_ids[]
job_get/job_cancel job_ids[]
```

Или как одна semantic compound action:

```text
browser_fill_form fields[]
```

Sequential browser state transitions остаются отдельными calls.

---

# 18. Freeze candidate catalog

```text
Web
  web_search
  web_fetch
  web_fetch_job

Content
  content_get
  content_parse
  content_parse_job

Browser lifecycle/observation
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

Browser interaction
  browser_click
  browser_fill_form
  browser_type
  browser_press
  browser_hover
  browser_drag
  browser_wait
  browser_upload

Jobs
  job_get
  job_cancel
```

Catalog version/freeze rules — `compatibility.md` и ADR-0022.

---

# 19. `web_search`

Intent:

> Найти релевантные страницы/источники по одному или нескольким независимым запросам.

Baseline v0.2:

```text
queries: 1..8
provider: default | supported stable provider IDs
a shared page/language/region/safe-search/time options profile
limit <= 20/query MCP baseline
```

Common options применяются ко всему batch.

Разные provider/options → отдельные calls.

Result:

- title;
- URL;
- snippet;
- provider/provenance;
- optional metadata;
- warnings/hints.

No target page acquisition.

---

# 20. `web_fetch`

Intent:

> Немедленно получить один или несколько известных HTTP(S)-URL через safe Retrieval и доступный L0/L1 Content pipeline.

Baseline:

```text
urls: 1..8
```

Pipeline fixed:

```text
safe Retrieval
→ raw ContentObject
→ L0 Inspection
→ registered direct L1 Native Parsing when request-bound applicable
```

No Browser, L2 or Job.

If direct contract insufficient, result/error can hint `web_fetch_job`.

---

# 21. `web_fetch_job`

Intent:

> Создать durable Job для большого batch известных URL.

Baseline:

```text
urls: 1..256
```

Result:

```text
JobRef
```

Job survives MCP disconnect.

Use `job_get` / `job_cancel`.

No blind automatic retry after uncertain Job creation response.

---

# 22. `content_get`

Intent:

> Прочитать уже существующий ContentObject без повторного HTTP/Browser acquisition.

Input batch:

```text
items: 1..8
  content_id
  cursor | null
max_chars: bounded common value
```

Server returns complete UTF-8 chunk boundaries, metadata, derived refs and next cursor.

Binary object without readable representation does not get fake text conversion.

---

# 23. `content_parse`

Intent:

> Немедленно выполнить доступный L1 Native Parsing существующих ContentObjects.

Freeze baseline:

```text
content_ids: 1..8
```

Registry chooses canonical parser by detected format.

No parser library ID.

No OCR/L2/Job.

Existing compatible representation may be reused.

---

# 24. `content_parse_job`

Intent:

> Создать durable Native Parsing batch Job.

Baseline:

```text
content_ids: 1..256
```

Returns JobRef.

No L2.

---

# 25. `browser_create`

Creates exactly one ephemeral BrowserSession + initial blank page.

Baseline input empty (или только stable options added by explicit design).

No URL input.

Result:

```text
browser_session_id
initial page_id
state/lifetime metadata
```

---

# 26. `browser_get`

Read BrowserSession state/lifetime/owner-safe metadata.

No page snapshot.

Useful for lifecycle/status recovery.

---

# 27. `browser_close`

Idempotent cleanup batch:

```text
session_ids[]
```

Per item:

```text
closed
already_terminal
lost/error
```

This is the trusted cleanup operation for agent BrowserSession lifecycle.

---

# 28. `browser_navigate`

Input:

```text
session_id
page_id
destination discriminator:
  url
  back
  forward
  reload
optional explicit dialog policy where operation supports it
```

All variants mutate browser/page state and share conservative retry semantics.

No hidden page/session creation.

---

# 29. `browser_snapshot`

Read semantic interactive state:

```text
session_id
page_id
```

Returns:

- snapshot_id;
- page generation/revision;
- semantic tree/preview;
- actionable `element_ref`s;
- optional full ContentRef if externalized.

No screenshot automatically.

---

# 30. `browser_content`

Intent:

> Получить rendered current page как document-like Content и применить обычный Content pipeline.

Distinct from snapshot:

```text
snapshot → interaction
content → reading/analysis
```

Returns ContentRefs/preview.

---

# 31. `browser_tabs`

Read-only page/tab listing.

Returns pages with:

```text
page_id
URL
title
state/basic metadata
```

There is no required MCP active-tab state; all page actions accept explicit page_id.

---

# 32. `browser_page_create`

Creates one new blank Page in existing BrowserSession.

Returns page_id.

Navigation remains explicit next action.

Uncertain response must not be blindly retried because duplicate page may exist.

---

# 33. `browser_page_close`

Close explicit page.

Freeze baseline preserves at least one live page:

```text
closing final remaining page
→ rejected last_page_close_rejected
```

Use `browser_close` to close whole session.

No silent replacement blank page.

---

# 34. `browser_screenshot`

Explicit screenshot artifact:

```text
session_id
page_id
optional element_ref
bounded approved capture options
```

Returns image ContentRef + metadata.

No base64 giant result.

---

# 35. `browser_events`

Read bounded browser diagnostic event log.

Input:

```text
session_id
page_id | null
types[]
after_sequence | null
limit
```

Combines console/network/page/dialog/download/security event reading under one read-only intent.

Untrusted event text separated from trusted metadata.

---

# 36. `browser_click`

Explicit click on current snapshot `element_ref`.

No selector.

Potential external side effect; never blind retry after uncertain dispatch.

---

# 37. `browser_fill_form`

Set several form controls in one semantic operation:

```text
fields[]:
  element_ref
  typed value
```

Supports text/select/check/radio classes where snapshot identifies control.

No automatic submit.

Per-field result preserves partial mutation.

Separate `browser_select`/`browser_check` baseline tools are unnecessary.

---

# 38. `browser_type`

Eventful/incremental keyboard-style text input to target element.

Used when `fill` semantics are insufficient (autocomplete/input event behavior).

Potentially side-effecting.

---

# 39. `browser_press`

Keyboard key/shortcut action.

Target may be explicit element_ref or page-level only if schema makes semantics unambiguous.

Enter can submit; conservative retry semantics.

---

# 40. `browser_hover`

Hover target `element_ref` for menus/tooltips/lazy UI.

No coordinates baseline.

---

# 41. `browser_drag`

Drag source `element_ref` to target `element_ref`.

No arbitrary screen-coordinate scripting baseline.

---

# 42. `browser_wait`

Wait for one typed bounded condition, such as:

```text
duration
URL condition
element state
page load state
```

No free-form JS predicate.

Wait never claims semantic completion of arbitrary site.

---

# 43. `browser_upload`

Attach owner-authorized ContentObject to explicit file-input `element_ref`.

No local filesystem path.

Potential external/page side effect; never blind retry.

---

# 44. Downloads

No separate `browser_download` baseline.

Download is artifact/event caused by explicit browser action/navigation and persisted to ContentRef.

Known direct file URL should use `web_fetch` when possible.

---

# 45. `job_get`

Batch read:

```text
job_ids[]
```

Returns bounded:

- state/type;
- progress;
- retry/attempt summary;
- aggregate result;
- manifest ContentRef;
- errors/warnings/hints.

---

# 46. `job_cancel`

Batch idempotent cancellation request:

```text
job_ids[]
```

Response may be `cancelling`; tool does not lie that execution stopped instantly.

---

# 47. Tools intentionally absent

```text
job_create arbitrary
web_read/web_read_many
browser_download
browser_select
browser_check
browser_evaluate
browser_run_code
CSS/XPath locator tools
provider admin
policy admin
worker drain
parser registry admin
raw HTTP arbitrary method
```

These are redundant, unsafe, implementation-facing or REST/operator concerns.

---

# 48. Tool annotations / trusted semantics

MCP annotations and own-agent trusted descriptors must agree with actual behavior.

Broad mapping:

```text
safe/read:
  web_search, web_fetch, content_get,
  browser_get, browser_snapshot, browser_tabs, browser_events,
  job_get

safe/idempotent representation-producing:
  content_parse, browser_content, browser_screenshot

resource-creating / never blind retry:
  web_fetch_job, content_parse_job,
  browser_create, browser_page_create

idempotent cleanup/cancel:
  browser_close, browser_page_close, job_cancel

state/external-side-effect / never blind retry:
  browser_navigate, browser_click, browser_fill_form,
  browser_type, browser_press, browser_hover,
  browser_drag, browser_upload
```

`browser_wait` separately classified safe observation/open-world wait in trusted metadata.

---

# 49. Own-agent builtin integration

Web Access is builtin MCP service but not in-process.

Agent-side trusted metadata owns:

- presentation;
- permissions;
- budget;
- retry profile;
- lifecycle cleanup mapping.

Web Access schemas/results provide stable semantics; they do not grant themselves trust.

See `agent-integration.md`.

---

# 50. BrowserSession cleanup integration

Agent trusted mapping:

```text
browser_create result
→ remote resource browser_session
→ cleanup tool browser_close
```

Web Access still has server TTL/reaper.

MCP disconnect does not equal close.

---

# 51. Job lifecycle integration

`*_job` returns JobRef.

Jobs are not automatically tied to one AgentCycle baseline.

Agent polls `job_get`; explicit cancel with `job_cancel` only when task semantics require.

---

# 52. `unknown`

Mutating Browser action can return `unknown` if outcome cannot be proven.

Tool result/agent must preserve it.

Recommended next action is safe observation/status, not automatic duplicate mutation.

---

# 53. Technical MCP progress

Allowed only as bounded technical progress where useful.

Canonical user-facing progress remains Agent Runtime responsibility.

No page text promoted to trusted progress phrase.

---

# 54. Authentication

Authentication is transport/service configuration.

No tool accepts:

```text
api_key
bearer_token
user_id as untrusted identity
```

Principal/owner derived from authenticated connection/context.

---

# 55. Validation errors

Structured repairable example shape:

```text
category=validation
code=invalid_arguments
fields[]:
  path
  code
  message
retryable=true after correction
```

LLM should be able to repair without reading server stack trace.

---

# 56. Actual schema tests

CI starts actual FastMCP server/client and verifies:

- exact tool names;
- every public/nested field description;
- required/defaults;
- `additionalProperties=false` where appropriate;
- bounds;
- enums/discriminators;
- annotations;
- hidden Context absent;
- no internal fields;
- descriptions preserve neighboring-tool distinction.

Generated fixture participates in `compatibility.md` contract gate.

---

# 57. Generic MCP compatibility

No own-agent-specific manager call required by service tools.

Generic MCP client can explicitly manage:

- BrowserSession;
- Job;
- Content.

Pretty progress/automatic cleanup are optional agent integration features, not protocol prerequisites.

---

# 58. Compatibility

v0.8 establishes freeze candidate.

Any later rename/remove/semantic change follows `compatibility.md`.

New tool only for real new intent; convenience aliases forbidden.
