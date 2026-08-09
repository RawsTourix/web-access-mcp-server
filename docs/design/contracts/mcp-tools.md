# Exact MCP tool contracts

## Статус

Каноническая freeze-candidate спецификация public MCP tools Web Access.

Семантика tools принадлежит `../mcp.md` и ADR-0022. Общие result/resource модели принадлежат `common-models.md`. Этот документ фиксирует **точные input DTO, defaults, bounds, cross-field invariants, result data shapes и execution metadata**, которые должны быть воспроизведены фактической FastMCP JSON Schema.

До v0.8 generated actual MCP schemas могут уточняться только через явное изменение Design/ADR/этого contract. Coding agent не должен самостоятельно расширять public surface.

---

# 1. Общие правила schema

Для каждого tool:

- top-level input — JSON object;
- `additionalProperties=false`;
- все nested objects также запрещают неизвестные поля, если явно не сказано обратное;
- descriptions tool/fields — на русском;
- technical field names/codes — на английском;
- URL input в MCP ограничен `4096` Unicode characters и runtime обязан принимать только `http`/`https` там, где это web URL;
- opaque resource IDs — string `1..128`; client не должен разбирать prefix;
- `null` допускается только там, где имеет отдельную описанную semantics;
- omission и default не смешиваются;
- каждый list имеет `minItems/maxItems`;
- каждый integer имеет `minimum/maximum`, если диапазон является частью contract;
- server runtime validation повторяет все ограничения независимо от JSON Schema.

Expected application failures возвращаются через `PublicOperationResult`, а не protocol exception.

---

# 2. Общие reusable input types

## 2.1 `HttpUrlInput`

```text
string
minLength = 1
maxLength = 4096
```

Description:

> Полный HTTP(S)-URL. Сервис повторно проверяет scheme, hostname, port, DNS/IP и redirects по security policy; URL не является разрешением на доступ к private/internal сети.

JSON Schema `format=uri` может использоваться как ранняя проверка, но runtime URL parser/security policy остаются authoritative.

## 2.2 Opaque IDs

```text
ContentId
BrowserSessionId
BrowserPageId
ElementRef
JobId
Cursor
```

Базовый string range:

```text
IDs: 1..128 chars
Cursor: 1..2048 chars
```

Prefixes могут использоваться server-side для удобства, но client contract не зависит от UUID/layout внутри handle.

## 2.3 `DialogPolicyInput`

Discriminated union:

```json
{"behavior":"dismiss"}
```

или

```json
{"behavior":"accept","prompt_text":"optional text"}
```

Rules:

- discriminator: `behavior`;
- enum: `dismiss | accept`;
- `prompt_text`: only `accept`, `0..2048` chars;
- `prompt_text` forbidden for `dismiss`;
- omission всей policy → server default `dismiss_and_report` из ADR-0011.

## 2.4 `ModifierKey`

Enum:

```text
Alt
Control
Meta
Shift
```

Array modifiers:

```text
uniqueItems=true
maxItems=4
```

---

# 3. Tool execution metadata

Canonical metadata table:

| Tool | readOnlyHint | destructiveHint | idempotentHint | openWorldHint | Agent retry class |
|---|---:|---:|---:|---:|---|
| `web_search` | true | false | true | true | safe |
| `web_fetch` | true | false | true | true | safe |
| `web_fetch_job` | false | false | false | true | never automatic after uncertain creation |
| `content_get` | true | false | true | false | safe |
| `content_parse` | false | false | true | false | idempotent |
| `content_parse_job` | false | false | false | false | never automatic after uncertain creation |
| `browser_create` | false | false | false | true | never automatic after uncertain creation |
| `browser_get` | true | false | true | true | safe |
| `browser_close` | false | true | true | true | idempotent cleanup |
| `browser_navigate` | false | false | false | true | never automatic after dispatch uncertainty |
| `browser_snapshot` | true | false | true | true | safe |
| `browser_content` | false | false | false | true | never automatic after uncertain artifact creation |
| `browser_tabs` | true | false | true | true | safe |
| `browser_page_create` | false | false | false | true | never automatic after uncertain creation |
| `browser_page_close` | false | true | true | true | idempotent cleanup |
| `browser_screenshot` | false | false | false | true | never automatic after uncertain artifact creation |
| `browser_events` | true | false | true | true | safe |
| `browser_click` | false | true | false | true | never automatic |
| `browser_fill_form` | false | true | false | true | never automatic |
| `browser_type` | false | true | false | true | never automatic |
| `browser_press` | false | true | false | true | never automatic |
| `browser_hover` | false | false | false | true | never automatic |
| `browser_drag` | false | true | false | true | never automatic |
| `browser_wait` | true | false | true | true | safe |
| `browser_upload` | false | true | false | true | never automatic |
| `job_get` | true | false | true | false | safe |
| `job_cancel` | false | true | true | false | idempotent cancellation |

`retryable=true` в `PublicError` не отменяет более строгую tool execution semantics.

---

# 4. `web_search`

## Description

> Ищет страницы и источники в интернете по одному или нескольким независимым поисковым запросам. Возвращает поисковую выдачу: URL, заголовки, snippets и metadata поискового backend-а. Не читает содержимое найденных страниц; для известных URL используйте `web_fetch`.

## Input

```text
queries: array[string]              required, 1..8
  item: trim-non-empty, 1..2048 chars
provider: enum                      default "default"
  default | searxng | yandex
page: integer                       default 1, 1..100
limit: integer                      default 10, 1..20
language: string | omitted          1..64 chars, normalized language tag
region: string | omitted            1..64 chars
safe_search: enum | omitted         off | moderate | strict
time_range: enum | omitted          day | month | year
```

Shared options apply to every query in the batch. Queries requiring different providers/options use separate tool calls.

`region` follows canonical configured SearchRegion ID rules; unsupported provider/region combination returns repairable per-item rejection.

## Result data

```text
SearchBatchData
└── items[] in original query order
    └── BatchItemResult<SearchQueryData>
```

`SearchQueryData`:

```text
query
provider_id
page
requested_limit
results[]
cache:
  cached: bool
  retrieved_at: timestamp
pagination:
  page
  next_page_available: bool | null
usage: bounded provider usage metadata | null
```

`SearchResultItem`:

```text
rank: integer >=1
title: string <=4096
url: string <=8192
snippet: string | null <=8192
host: string | null <=1024
published_at: timestamp | null
```

No cross-provider score field.

---

# 5. `web_fetch`

## Description

> Немедленно получает один или несколько известных HTTP(S)-ресурсов через безопасный HTTP Retrieval. Для каждого ресурса сохраняет raw ContentObject, выполняет L0 Inspection и доступный request-bound L1 Native Parsing. Не запускает Browser, OCR/L2 или durable Job автоматически.

## Input

```text
urls: array[HttpUrlInput] required, 1..8
```

Duplicate URLs are allowed only if caller intentionally requested duplicate independent items; response preserves positions.

## Result data

```text
FetchBatchData
└── items[] in original URL order
    └── BatchItemResult<FetchItemData>
```

`FetchItemData`:

```text
requested_url
final_url
http_status
redirect_count
wire_bytes
entity_bytes
content_encoding | null
raw_content: ContentRef
inspection: bounded object
native_content: ContentRef | null
available_representations: ContentRef[]
preview: string | null <=8000 chars
```

No raw giant HTML/base64 payload.

---

# 6. `web_fetch_job`

## Description

> Создаёт durable Job для получения большого набора известных HTTP(S)-URL. Job переживает разрыв MCP-соединения и выполняет безопасный Retrieval + Content pipeline с persistent item checkpoints. Для небольшого немедленного batch используйте `web_fetch`.

## Input

```text
urls: array[HttpUrlInput] required, 1..256
```

No generic timeout/provider/browser options.

## Result data

```text
job: JobRef
```

Job type fixed to `retrieval_batch`.

Creation response uncertainty must not cause blind repeated creation.

---

# 7. `content_get`

## Description

> Читает уже существующие ContentObjects без повторного HTTP-запроса или браузинга. Для текстовых представлений возвращает ограниченный UTF-8 chunk и opaque cursor. Для бинарного объекта возвращает metadata и доступные производные representations, не выполняя скрытую конвертацию.

## Input

```text
items: array[ContentReadItem] required, 1..8
max_chars: integer default 12000, 1..30000
```

`ContentReadItem`:

```text
content_id: ContentId required
cursor: Cursor | omitted
```

Cursor belongs to exact content object; mismatch/stale/unknown version is rejected per item.

## Result data

```text
items[]
└── BatchItemResult<ContentReadData>
```

`ContentReadData`:

```text
content: ContentRef
text: string | null <= max_chars
returned_chars: integer >=0
next_cursor: Cursor | null
inspection: bounded object
available_representations: ContentRef[]
```

Binary content may have `text=null`.

---

# 8. `content_parse`

## Description

> Немедленно запускает зарегистрированный L1 Native Parser для одного или нескольких существующих ContentObjects. Использует detected format и canonical parser registry; не принимает имя внутренней библиотеки, не запускает OCR/L2 и не создаёт durable Job.

## Input

```text
content_ids: array[ContentId] required, 1..8, uniqueItems=true
```

## Result data

```text
items[]
└── BatchItemResult<NativeParseData>
```

`NativeParseData`:

```text
source: ContentRef
representations: ContentRef[]
reused: bool
parser_capability: stable public capability code | null
```

Internal parser/library IDs are not returned as public control fields.

---

# 9. `content_parse_job`

## Description

> Создаёт durable L1 Native Parsing batch Job для большого набора существующих ContentObjects. Не выполняет OCR/L2. Для небольшого немедленного batch используйте `content_parse`.

## Input

```text
content_ids: array[ContentId] required, 1..256, uniqueItems=true
```

## Result data

```text
job: JobRef
```

Job type fixed to `content_parse_batch`.

---

# 10. `browser_create`

## Description

> Создаёт одну новую изолированную ephemeral BrowserSession с начальной пустой страницей. Не открывает URL автоматически; после создания используйте `browser_navigate`. Сессия имеет собственный server-side TTL и не зависит от жизненного цикла MCP-соединения.

## Input

```json
{}
```

No public Playwright launch/context options in core MCP.

## Result data

```text
session: BrowserSessionRef
page: PageRef
```

Creation is not automatically retryable after uncertain response because a session may already exist.

---

# 11. `browser_get`

## Description

> Возвращает текущее состояние и lifecycle metadata существующей BrowserSession. Не создаёт snapshot и не читает содержимое страницы.

## Input

```text
session_id: BrowserSessionId required
```

## Result data

```text
session: BrowserSessionRef
pages_count: integer >=0
```

No worker routing metadata.

---

# 12. `browser_close`

## Description

> Идемпотентно закрывает одну или несколько BrowserSessions и освобождает принадлежащие им browser resources. Используется также lifecycle cleanup-логикой агента. Закрытие session не удаляет уже сохранённые ContentObjects.

## Input

```text
session_ids: array[BrowserSessionId] required, 1..8, uniqueItems=true
```

## Result data

Per item:

```text
session_id
state: closed | expired | lost | already_terminal
```

Expected terminal/already-terminal state is not protocol error.

---

# 13. `browser_navigate`

## Description

> Выполняет одну явную навигационную операцию в конкретной странице существующей BrowserSession: открыть URL, вернуться назад, перейти вперёд или перезагрузить страницу. Операция меняет browser state; при неопределённом результате после dispatch её нельзя слепо повторять.

## Input

```text
session_id: BrowserSessionId required
page_id: BrowserPageId required
destination: discriminated union required
dialog_policy: DialogPolicyInput | omitted
```

Destination variants:

```json
{"type":"url","url":"https://example.com"}
{"type":"back"}
{"type":"forward"}
{"type":"reload"}
```

No wait-until/browser launch options exposed in core MCP.

## Result data

```text
page: PageRef
page_generation: integer >=0
navigation:
  requested_kind
  final_url
  http_status | null
  download_refs: ContentRef[]
  popup_pages: PageRef[]
```

---

# 14. `browser_snapshot`

## Description

> Получает структурированный semantic snapshot текущей страницы для взаимодействия LLM с интерфейсом. Возвращает snapshot-scoped `element_ref` для действий. Не делает screenshot и не превращает страницу в document content автоматически.

## Input

```text
session_id: BrowserSessionId required
page_id: BrowserPageId required
```

## Result data

```text
snapshot: SnapshotRef
page: PageRef
semantic_view: string <=30000 chars
elements: array[SemanticElement] <=300
full_content: ContentRef | null
truncated: bool
```

`SemanticElement` bounded fields:

```text
element_ref
role: string <=128
name: string <=2048
state: bounded object
value_preview: string | null <=2048
```

No CSS/XPath/internal locator recipe.

---

# 15. `browser_content`

## Description

> Получает rendered содержимое текущей browser page как document-like Content и пропускает его через обычный L0/L1 Content pipeline. Используйте `browser_snapshot` для кликов и формы, а `browser_content` — когда страницу нужно читать и анализировать как документ.

## Input

```text
session_id: BrowserSessionId required
page_id: BrowserPageId required
```

## Result data

```text
raw_rendered_content: ContentRef
native_content: ContentRef | null
available_representations: ContentRef[]
preview: string | null <=8000 chars
```

No hidden navigation.

---

# 16. `browser_tabs`

## Description

> Возвращает read-only список открытых страниц/вкладок BrowserSession. Для действий всегда используйте явный `page_id`; MCP не поддерживает скрытое глобальное состояние «активной вкладки» как prerequisite действий.

## Input

```text
session_id: BrowserSessionId required
```

## Result data

```text
pages: PageRef[] <=8
```

`pages` order is stable for current server snapshot but not a durable identity; use page IDs.

---

# 17. `browser_page_create`

## Description

> Создаёт одну новую пустую страницу в существующей BrowserSession. URL не открывается автоматически; навигация выполняется отдельным `browser_navigate`.

## Input

```text
session_id: BrowserSessionId required
```

## Result data

```text
page: PageRef
```

Uncertain response is not blindly retried because duplicate page can exist.

---

# 18. `browser_page_close`

## Description

> Идемпотентно закрывает указанную страницу BrowserSession. Последнюю оставшуюся страницу закрыть нельзя; для завершения всей сессии используйте `browser_close`.

## Input

```text
session_id: BrowserSessionId required
page_id: BrowserPageId required
```

## Result data

```text
page_id
state: closed | already_closed
remaining_pages: integer >=1
```

Closing the last live page returns structured `last_page_close_rejected`.

---

# 19. `browser_screenshot`

## Description

> Создаёт явный screenshot страницы или конкретного элемента и сохраняет изображение как ContentObject. Не возвращает base64-изображение в MCP result.

## Input

```text
session_id: BrowserSessionId required
page_id: BrowserPageId required
target: discriminated union default {"type":"page","full_page":false}
format: enum png | jpeg default png
quality: integer | omitted
```

Target variants:

```json
{"type":"page","full_page":false}
```

or

```json
{"type":"element","element_ref":"el_..."}
```

Cross-field rules:

- `quality` allowed only for `jpeg`;
- JPEG quality `1..100`, default `85` when format=`jpeg` and omitted;
- `quality` forbidden for `png`;
- element target has no `full_page` field.

## Result data

```text
image: ContentRef
page_generation: integer >=0
width: integer >0
height: integer >0
```

---

# 20. `browser_events`

## Description

> Читает ограниченный диагностический event log BrowserSession: page lifecycle, dialogs, downloads, console, network failures, security blocks и browser lifecycle. Это read-only diagnostics, а не authoritative business history.

## Input

```text
session_id: BrowserSessionId required
page_id: BrowserPageId | omitted
types: array[enum] omitted => all supported safe event groups
after_sequence: integer | omitted, >=0
limit: integer default 50, 1..100
```

Event group enum:

```text
page
dialog
download
console
network
security
browser
```

`types`: 1..7 unique when provided.

## Result data

```text
events[] <= limit
next_sequence: integer | null
gap_detected: bool
```

Event common fields:

```text
sequence
occurred_at
type
page_id | null
trusted_code | null
message | null <=4096
metadata: bounded object
```

Page/provider event text remains untrusted.

---

# 21. `browser_click`

## Description

> Выполняет один click по `element_ref` из актуального `browser_snapshot`. Действие может вызвать навигацию, submit, download или другой внешний side effect. После неопределённого результата не повторяйте click автоматически; сначала проверьте состояние страницы.

## Input

```text
session_id: BrowserSessionId required
page_id: BrowserPageId required
element_ref: ElementRef required
button: enum left | middle | right default left
click_count: integer default 1, 1..2
modifiers: array[ModifierKey] omitted
dialog_policy: DialogPolicyInput | omitted
```

## Result data

```text
action_id
page: PageRef
page_generation
popup_pages: PageRef[]
download_refs: ContentRef[]
dialogs: bounded summaries[]
```

No coordinates/selectors/`force`.

---

# 22. `browser_fill_form`

## Description

> Устанавливает значения нескольких form controls одной страницы в заданном порядке. Не отправляет форму автоматически. Для каждого поля возвращает отдельный результат; при ошибке поздние поля не скрываются и могут быть помечены `not_attempted`.

## Input

```text
session_id: BrowserSessionId required
page_id: BrowserPageId required
fields: array[FormFieldInput] required, 1..32
dialog_policy: DialogPolicyInput | omitted
```

`FormFieldInput`:

```text
element_ref: ElementRef
value: discriminated union
```

Value variants:

```json
{"type":"text","text":"..."}
{"type":"select","values":["..."]}
{"type":"checked","checked":true}
```

Bounds:

- text: `0..10000` chars;
- select values: `1..20`, each `0..2048` chars;
- checked: boolean;
- `fields` order is execution order;
- server validates value kind against actual control semantics from snapshot/current DOM.

## Result data

```text
action_id
fields[] in original order:
  element_ref
  outcome
  error | null
page_generation
```

No submit.

---

# 23. `browser_type`

## Description

> Вводит текст в указанный элемент как последовательность keyboard/input events. Используйте `browser_fill_form` для обычной установки значения; `browser_type` нужен, когда странице важны реальные события ввода, autocomplete или последовательный набор.

## Input

```text
session_id
page_id
element_ref
text: string 1..10000
delay_ms: integer default 0, 0..1000
dialog_policy: DialogPolicyInput | omitted
```

## Result data

```text
action_id
page_generation
```

No hidden clearing of existing value unless browser semantics explicitly imply it; caller uses form fill when replacement is desired.

---

# 24. `browser_press`

## Description

> Нажимает одну клавишу или поддерживаемое сочетание клавиш в странице. `Enter` и некоторые shortcuts могут вызвать submit или другой side effect, поэтому неопределённый результат нельзя слепо повторять.

## Input

```text
session_id
page_id
key: string 1..64
element_ref: ElementRef | omitted
dialog_policy: DialogPolicyInput | omitted
```

`key` runtime валидируется по поддерживаемой keyboard key/chord grammar; arbitrary JavaScript is not allowed.

If `element_ref` omitted, action uses page-level keyboard context.

## Result data

```text
action_id
page_generation
popup_pages[]
download_refs[]
```

---

# 25. `browser_hover`

## Description

> Наводит указатель на `element_ref`, например для hover-menu, tooltip или lazy interaction state. Не принимает координаты.

## Input

```text
session_id
page_id
element_ref
```

## Result data

```text
action_id
page_generation
```

---

# 26. `browser_drag`

## Description

> Выполняет одну drag-and-drop операцию от исходного `element_ref` к целевому `element_ref`. Не принимает screen coordinates и arbitrary mouse script.

## Input

```text
session_id
page_id
source_element_ref
target_element_ref
dialog_policy: DialogPolicyInput | omitted
```

Source and target must belong to current compatible page generation.

## Result data

```text
action_id
page_generation
```

---

# 27. `browser_wait`

## Description

> Ожидает одно явно заданное ограниченное условие в существующей странице. Не является гарантией «полной готовности сайта» и не выполняет JavaScript predicate.

## Input

```text
session_id
page_id
condition: discriminated union required
```

Variants:

### Duration

```json
{"type":"duration","milliseconds":1000}
```

`milliseconds`: `0..10000`.

### URL

```json
{"type":"url","match":"contains","value":"/result","timeout_ms":10000}
```

- `match`: `exact | contains`;
- `value`: `1..4096` chars;
- `timeout_ms`: default `10000`, `100..30000`.

### Element state

```json
{"type":"element_state","element_ref":"el_...","state":"visible","timeout_ms":10000}
```

- state enum: `attached | visible | hidden | enabled | disabled`;
- timeout `100..30000`, default `10000`.

### Page load state

```json
{"type":"load_state","state":"domcontentloaded","timeout_ms":10000}
```

- state enum: `domcontentloaded | load`;
- timeout `100..30000`, default `10000`.

No `networkidle` core contract and no free-form regex/JS predicate.

## Result data

```text
condition_type
satisfied: bool
elapsed_ms
page_generation
```

Timeout returns structured non-success/timeout according application contract, not fake `satisfied=false` success if caller requested successful wait.

---

# 28. `browser_upload`

## Description

> Прикрепляет уже существующий owner-authorized ContentObject к file-input `element_ref` текущей страницы. Не принимает локальный filesystem path. Действие может немедленно вызвать page-side upload/event, поэтому неопределённый результат нельзя повторять автоматически.

## Input

```text
session_id
page_id
element_ref
content_id
```

Only available ContentObject owned/authorized for current principal can be materialized.

## Result data

```text
action_id
content: ContentRef
page_generation
```

---

# 29. `job_get`

## Description

> Возвращает текущее состояние одного или нескольких durable Jobs, progress, retry/attempt summary и terminal result references. Используйте после `web_fetch_job` или `content_parse_job`.

## Input

```text
job_ids: array[JobId] required, 1..8, uniqueItems=true
```

## Result data

Per item:

```text
job: JobRef
progress: JobProgress | null
attempts:
  completed_attempts
  max_attempts
  next_retry_at | null
result_manifest: ContentRef | null
aggregate_outcome | null
error | null
```

No raw queue/worker IDs.

---

# 30. `job_cancel`

## Description

> Запрашивает отмену одного или нескольких durable Jobs. Отмена cooperative: успешный ответ может означать `cancelling`, а не мгновенный `cancelled`. Повторный cancel terminal Job идемпотентен.

## Input

```text
job_ids: array[JobId] required, 1..8, uniqueItems=true
```

## Result data

Per item:

```text
job_id
state: cancelling | cancelled | already_terminal
```

Completed ContentObjects/results are not deleted by cancellation.

---

# 31. Exact catalog invariant

Core catalog consists exactly of:

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

No core aliases:

```text
web_read
web_fetch_many
browser_select
browser_check
browser_download
browser_evaluate
browser_run_code
job_create
```

Any additive tool requires explicit facade review, unique semantic intent and compatibility update.

---

# 32. FastMCP schema acceptance

Automated tests must connect using a real MCP client and retrieve actual registered tool schemas.

For every tool verify:

1. exact tool name;
2. Russian tool description;
3. every public/nested property has description;
4. required fields exact;
5. defaults exact;
6. enums/bounds/list constraints exact;
7. unknown fields rejected;
8. discriminated unions generate valid `oneOf`/equivalent JSON Schema;
9. positive and negative fixtures pass `Draft202012Validator`/actual MCP validation;
10. no hidden `Context`, provider secrets, worker IDs, CSS/XPath, storage keys or framework fields;
11. annotations match §3;
12. runtime Pydantic validation agrees with generated schema.

v0.8 freezes generated fixture only after this contract suite is green.
