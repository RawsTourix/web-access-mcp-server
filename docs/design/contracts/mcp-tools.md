# Exact MCP tool contracts

## Статус

Каноническая freeze-candidate спецификация public MCP tools Web Access.

Semantic owner: `../mcp.md`.

Relevant ADR:

- ADR-0021 — direct/durable split;
- ADR-0022 — semantic catalog invariant;
- ADR-0024 — resource/cost-aware retry classification;
- ADR-0025 — explicit browser scroll.

Common public models: `common-models.md`.

Этот документ фиксирует **точные input DTO, defaults, bounds, cross-field invariants, result data shapes и execution metadata**, которые должны быть воспроизведены actual FastMCP JSON Schema/runtime validation.

---

# 1. Общие schema rules

Для каждого tool:

- top-level input — JSON object;
- `additionalProperties=false`;
- nested objects также reject unknown fields, если прямо не сказано иное;
- descriptions tools/fields — русские;
- identifiers/error codes — английские;
- MCP web URL max `4096` chars;
- opaque resource IDs `1..128` chars;
- cursor `1..2048` chars;
- every array has `minItems/maxItems`;
- numeric bounds machine-readable;
- discriminated union генерирует `oneOf`/equivalent actual JSON Schema;
- omission/default/null semantics explicit;
- runtime Pydantic/application validation повторяет/усиливает schema constraints;
- expected failures return `PublicOperationResult`, not raw protocol exception.

---

# 2. Reusable input types

## 2.1 `HttpUrlInput`

```text
string
1..4096 chars
```

Description:

> Полный HTTP(S)-URL. Сервис повторно проверяет scheme, hostname, port, DNS/IP и redirects по security policy; URL не является разрешением на доступ к private/internal сети.

`format=uri` may be emitted, but runtime safe URL parser is authoritative.

## 2.2 Opaque IDs

```text
ContentId
BrowserSessionId
BrowserPageId
ElementRef
JobId
```

```text
string 1..128
```

Client не разбирает внутренний prefix/UUID layout.

## 2.3 Cursor

```text
string 1..2048
```

Opaque and resource-scoped.

## 2.4 ModifierKey

Enum:

```text
Alt
Control
Meta
Shift
```

Modifier arrays:

```text
0..4
uniqueItems=true
```

## 2.5 `DialogPolicyInput`

Union:

```json
{"behavior":"dismiss"}
```

or

```json
{"behavior":"accept","prompt_text":"optional text"}
```

Rules:

- `behavior`: `dismiss | accept`;
- `prompt_text`: 0..2048 chars, allowed only for `accept`;
- policy object omitted → server default `dismiss_and_report` ADR-0011.

## 2.6 `KeyInput`

Structured key union.

Named key:

```json
{"type":"named","key":"Enter"}
```

Named enum:

```text
Enter
Tab
Escape
Backspace
Delete
ArrowUp
ArrowDown
ArrowLeft
ArrowRight
Home
End
PageUp
PageDown
Insert
Space
F1 F2 F3 F4 F5 F6 F7 F8 F9 F10 F11 F12
```

Character:

```json
{"type":"character","value":"a"}
```

`value`: 1..8 chars in JSON schema; runtime validates exactly one Unicode grapheme/character key representation supported by browser runtime.

Shortcut uses separate modifiers:

```text
Control + character a
```

No free-form Playwright chord/JavaScript expression.

---

# 3. Execution/annotation table

Trusted Agent retry class follows ADR-0024 and may be stricter than basic MCP annotation.

| Tool | readOnlyHint | destructiveHint | idempotentHint | openWorldHint | Own-agent retry class |
|---|---:|---:|---:|---:|---|
| `web_search` | true | false | true | true | conservative: no blind retry after possible provider dispatch/cost |
| `web_fetch` | false | false | false | true | no blind retry after uncertain network/resource creation |
| `web_fetch_job` | false | false | false | true | no blind retry after uncertain Job creation |
| `content_get` | true | false | true | false | safe |
| `content_parse` | false | false | true | false | idempotent only with canonical representation reuse |
| `content_parse_job` | false | false | false | false | no blind retry after uncertain Job creation |
| `browser_create` | false | false | false | true | no blind retry after uncertain session creation |
| `browser_get` | true | false | true | true | safe |
| `browser_close` | false | true | true | true | idempotent cleanup |
| `browser_navigate` | false | false | false | true | never automatic after dispatch uncertainty |
| `browser_snapshot` | true | false | true | true | safe |
| `browser_content` | false | false | false | true | no blind retry after uncertain Content creation |
| `browser_tabs` | true | false | true | true | safe |
| `browser_page_create` | false | false | false | true | no blind retry after uncertain page creation |
| `browser_page_close` | false | true | true | true | idempotent page cleanup |
| `browser_screenshot` | false | false | false | true | no blind retry after uncertain Content creation |
| `browser_events` | true | false | true | true | safe |
| `browser_click` | false | true | false | true | never automatic |
| `browser_fill_form` | false | true | false | true | never automatic |
| `browser_type` | false | true | false | true | never automatic |
| `browser_press` | false | true | false | true | never automatic |
| `browser_hover` | false | false | false | true | never automatic |
| `browser_drag` | false | true | false | true | never automatic |
| `browser_scroll` | false | false | false | true | never automatic |
| `browser_wait` | true | false | true | true | safe |
| `browser_upload` | false | true | false | true | never automatic |
| `job_get` | true | false | true | false | safe |
| `job_cancel` | false | true | true | false | idempotent cancellation |

`retryable=true` in application error never overrides stronger tool/phase semantics.

---

# 4. `web_search`

## Description

> Ищет страницы и источники в интернете по одному или нескольким независимым поисковым запросам. Возвращает поисковую выдачу: URL, заголовки, snippets и metadata поискового backend-а. Не читает содержимое найденных страниц; для известных URL используйте `web_fetch`. Некоторые providers (например Yandex) могут расходовать платный provider budget, поэтому потерянный результат не означает разрешение автоматически повторить платный запрос.

## Input

```text
queries: array[string] required, 1..8
  item: trim-non-empty, 1..2048
provider: enum default|searxng|yandex, default "default"
page: integer 1..100, default 1
limit: integer 1..20, default 10
language: string omitted | 1..64
region: string omitted | 1..64
safe_search: off|moderate|strict omitted
time_range: day|month|year omitted
```

Common options apply to all queries. Different provider/options → separate call.

Provider description:

> `default` использует настроенный default provider. `searxng` — бесплатный configured SearXNG backend. `yandex` может быть billable и доступен только при provider policy/budget. Сервис не переключает provider скрыто из-за размера/качества выдачи.

## Result

```text
SearchBatchData
└── items[] in input order
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

No cross-provider score.

---

# 5. `web_fetch`

## Description

> Немедленно получает один или несколько известных HTTP(S)-ресурсов через безопасный HTTP Retrieval. Для каждого ресурса сохраняет raw ContentObject, выполняет L0 Inspection и доступный request-bound L1 Native Parsing. Не запускает Browser, OCR/L2 или durable Job автоматически. Вызов создаёт Content resources, поэтому потерянный result нельзя слепо повторять как безусловно безопасное чтение.

## Input

```text
urls: array[HttpUrlInput] required, 1..8
```

Response preserves input order. Duplicate positions permitted deliberately.

## Result item

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
preview: string | null <=12000
```

No giant raw HTML/base64.

---

# 6. `web_fetch_job`

## Description

> Создаёт durable Job для получения большого набора известных HTTP(S)-URL. Job переживает разрыв MCP-соединения и выполняет безопасный Retrieval + Content pipeline с persistent item checkpoints. Для небольшого немедленного batch используйте `web_fetch`.

## Input

```text
urls: array[HttpUrlInput] required, 1..256
```

## Result

```text
job: JobRef
```

Fixed type `retrieval_batch`.

---

# 7. `content_get`

## Description

> Читает уже существующие ContentObjects без повторного HTTP-запроса или браузинга. Для текстовых представлений возвращает ограниченный UTF-8 chunk и opaque cursor. Для бинарного объекта возвращает metadata и доступные производные representations без скрытой конвертации.

## Input

```text
items: array[ContentReadItem] required, 1..8
max_chars: integer 1..30000, default 12000
```

`ContentReadItem`:

```text
content_id: ContentId
cursor: Cursor omitted
```

## Result item

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

> Немедленно запускает зарегистрированный L1 Native Parser для одного или нескольких существующих ContentObjects. Использует detected format и canonical parser registry; не принимает имя внутренней библиотеки, не запускает OCR/L2 и не создаёт durable Job. Совместимое уже существующее representation переиспользуется.

## Input

```text
content_ids: array[ContentId] required, 1..8, unique
```

## Result item

```text
source: ContentRef
representations: ContentRef[]
reused: bool
parser_capability: stable public capability code | null
```

Implementation acceptance must prove canonical duplicate/concurrent reuse before idempotent Agent classification is enabled.

---

# 9. `content_parse_job`

## Description

> Создаёт durable L1 Native Parsing batch Job для большого набора существующих ContentObjects. Не выполняет OCR/L2. Для небольшого немедленного batch используйте `content_parse`.

## Input

```text
content_ids: array[ContentId] required, 1..256, unique
```

## Result

```text
job: JobRef
```

Fixed type `content_parse_batch`.

---

# 10. `browser_create`

## Description

> Создаёт одну новую изолированную ephemeral BrowserSession с начальной пустой страницей. Не открывает URL автоматически; после создания используйте `browser_navigate`. Сессия имеет server-side TTL и не зависит от lifecycle MCP-соединения.

## Input

```json
{}
```

## Result

```text
session: BrowserSessionRef
page: PageRef
```

No core MCP launch/context knobs.

---

# 11. `browser_get`

## Description

> Возвращает текущее lifecycle-состояние существующей BrowserSession. Не создаёт snapshot и не читает page content.

## Input

```text
session_id: BrowserSessionId
```

## Result

```text
session: BrowserSessionRef
pages_count: integer >=0
```

No worker/routing metadata.

---

# 12. `browser_close`

## Description

> Идемпотентно закрывает одну или несколько BrowserSessions и освобождает browser resources. Используется lifecycle cleanup-логикой агента. Закрытие session не удаляет уже финализированные ContentObjects.

## Input

```text
session_ids: array[BrowserSessionId] required, 1..8, unique
```

## Result item

```text
session_id
state: closed | expired | lost | already_terminal
```

---

# 13. `browser_navigate`

## Description

> Выполняет одну явную навигационную операцию в конкретной странице существующей BrowserSession: открыть URL, назад, вперёд или reload. Операция меняет browser state; после неопределённого результата её нельзя повторять автоматически.

## Input

```text
session_id
page_id
destination: discriminated union
dialog_policy: DialogPolicyInput omitted
```

Variants:

```json
{"type":"url","url":"https://example.com"}
{"type":"back"}
{"type":"forward"}
{"type":"reload"}
```

## Result

```text
action_id
page: PageRef
page_generation
navigation:
  requested_kind
  final_url
  http_status | null
popup_pages: PageRef[]
download_refs: ContentRef[]
dialogs: bounded summaries[]
```

No hidden create/wait heuristic.

---

# 14. `browser_snapshot`

## Description

> Получает структурированный semantic snapshot текущей страницы для взаимодействия LLM с интерфейсом. Возвращает snapshot-scoped `element_ref`s. Не делает screenshot, scroll или document extraction автоматически.

## Input

```text
session_id
page_id
```

## Result

```text
snapshot: SnapshotRef
page: PageRef
semantic_view: string <=30000
elements: SemanticElement[] <=300
full_content: ContentRef | null
truncated: bool
```

`SemanticElement`:

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

> Получает rendered содержимое текущей browser page как document-like Content и пропускает его через обычный L0/L1 Content pipeline. Используйте `browser_snapshot` для взаимодействия, а `browser_content` — когда страницу нужно читать как документ. Операция создаёт Content resources.

## Input

```text
session_id
page_id
```

## Result

```text
raw_rendered_content: ContentRef
native_content: ContentRef | null
available_representations: ContentRef[]
preview: string | null <=12000
```

No hidden navigation.

---

# 16. `browser_tabs`

## Description

> Возвращает read-only список открытых страниц BrowserSession. Для действий всегда используется explicit `page_id`; скрытое состояние «активной вкладки» не требуется.

## Input

```text
session_id
```

## Result

```text
pages: PageRef[] <=8
```

---

# 17. `browser_page_create`

## Description

> Создаёт одну новую пустую страницу в существующей BrowserSession. URL не открывается автоматически.

## Input

```text
session_id
```

## Result

```text
page: PageRef
```

---

# 18. `browser_page_close`

## Description

> Идемпотентно закрывает указанную страницу BrowserSession. Последнюю оставшуюся страницу закрыть нельзя; для завершения всей сессии используйте `browser_close`.

## Input

```text
session_id
page_id
```

## Result

```text
page_id
state: closed | already_closed
remaining_pages: integer >=1
```

Last page → structured `last_page_close_rejected`.

---

# 19. `browser_screenshot`

## Description

> Создаёт screenshot страницы или конкретного элемента и сохраняет изображение как ContentObject. Не возвращает base64 image inline.

## Input

```text
session_id
page_id
target: union, default page/full_page=false
format: png | jpeg, default png
quality: integer omitted
```

Target:

```json
{"type":"page","full_page":false}
```

or

```json
{"type":"element","element_ref":"el_..."}
```

Cross-field:

- `quality` only JPEG;
- JPEG quality 1..100, default 85;
- quality forbidden PNG;
- element target has no `full_page`.

## Result

```text
image: ContentRef
page_generation
width >0
height >0
```

Screenshot resource/byte limits enforced server-side.

---

# 20. `browser_events`

## Description

> Читает ограниченный диагностический event log BrowserSession: page lifecycle, dialogs, downloads, console, network failures, security blocks и browser lifecycle. Это diagnostics, не authoritative business history.

## Input

```text
session_id
page_id omitted
types omitted | unique array 1..7
after_sequence integer omitted >=0
limit integer 1..100, default 50
```

Event groups:

```text
page
dialog
download
console
network
security
browser
```

## Result

```text
events[] <= limit
next_sequence: integer | null
gap_detected: bool
```

Event common:

```text
sequence
occurred_at
type
page_id | null
trusted_code | null
message | null <=4096
metadata bounded
```

Site text remains untrusted.

---

# 21. `browser_click`

## Description

> Выполняет один click по `element_ref` из актуального snapshot. Действие может вызвать navigation, submit, download или внешний side effect. После неопределённого результата сначала проверьте page state, не повторяйте click автоматически.

## Input

```text
session_id
page_id
element_ref
button: left | middle | right, default left
click_count: integer 1..2, default 1
modifiers: unique ModifierKey[] 0..4 omitted
dialog_policy omitted
```

## Result

```text
action_id
page: PageRef
page_generation
popup_pages[]
download_refs[]
dialogs[] bounded
```

No coordinates/selectors/force.

---

# 22. `browser_fill_form`

## Description

> Последовательно устанавливает значения нескольких form controls одной страницы. Не submit форму автоматически. Выполнение fail-fast: после первой ошибки дальнейшие поля не изменяются и возвращаются как `not_attempted`.

## Input

```text
session_id
page_id
fields: FormFieldInput[] 1..32
dialog_policy omitted
```

`FormFieldInput`:

```text
element_ref
value: discriminated union
```

Value:

```json
{"type":"text","text":""}
{"type":"select","values":["value"]}
{"type":"checked","checked":true}
```

Bounds:

- text 0..10000 chars;
- select values 1..20, each 0..2048;
- fields executed in order;
- value kind validated against actual control semantics.

## Result

```text
action_id
fields[] in input order:
  element_ref
  outcome: succeeded | failed | not_attempted
  error | null
page_generation
```

Earlier successes remain observable after later failure.

---

# 23. `browser_type`

## Description

> Вводит текст в элемент как последовательность keyboard/input events. Используйте `browser_fill_form` для обычной установки значения; `browser_type` нужен для autocomplete/event-sensitive UI.

## Input

```text
session_id
page_id
element_ref
text: string 1..10000
delay_ms: integer 0..1000, default 0
dialog_policy omitted
```

No implicit clear.

## Result

```text
action_id
page_generation
```

---

# 24. `browser_press`

## Description

> Нажимает одну структурированно заданную клавишу с optional modifiers. `Enter`/shortcuts могут вызвать submit/navigation, поэтому lost result нельзя повторять автоматически.

## Input

```text
session_id
page_id
key: KeyInput
modifiers: unique ModifierKey[] 0..4 omitted
element_ref: ElementRef omitted
dialog_policy omitted
```

If `element_ref` omitted → page-level keyboard context.

Examples:

```json
{"key":{"type":"named","key":"Enter"}}
```

```json
{"key":{"type":"character","value":"a"},"modifiers":["Control"]}
```

## Result

```text
action_id
page_generation
popup_pages[]
download_refs[]
```

---

# 25. `browser_hover`

## Description

> Наводит указатель на `element_ref`, например для hover menu, tooltip или lazy UI state. Не принимает координаты.

## Input

```text
session_id
page_id
element_ref
```

## Result

```text
action_id
page_generation
```

---

# 26. `browser_drag`

## Description

> Выполняет одну drag-and-drop операцию от исходного `element_ref` к целевому `element_ref`. Не принимает screen coordinates или script.

## Input

```text
session_id
page_id
source_element_ref
target_element_ref
dialog_policy omitted
```

Both refs current/compatible page generation.

## Result

```text
action_id
page_generation
```

---

# 27. `browser_scroll`

## Description

> Явно прокручивает page viewport или указанный scrollable container относительно текущего viewport. Используйте после bounded snapshot, чтобы добраться до элементов ниже/выше или активировать lazy-loaded UI; затем получите новый `browser_snapshot`. Scroll не выполняет snapshot автоматически.

## Input

```text
session_id
page_id
direction: up | down | left | right
viewport_units: number 0.1..3.0, default 0.8
element_ref: ElementRef omitted
```

Without element_ref → page/document scroll context.

With element_ref → exact/stale validation + target must be scrollable on requested axis. No silent fallback to page.

No coordinates/JS.

## Result

```text
action_id
page_generation
scroll_state:
  x: number
  y: number
  viewport_width: number >0
  viewport_height: number >0
  at_start_x: bool
  at_end_x: bool
  at_start_y: bool
  at_end_y: bool
```

Repeating after uncertain result may double-scroll; no automatic retry.

---

# 28. `browser_wait`

## Description

> Ожидает одно явно заданное ограниченное условие. Не является гарантией «полной готовности сайта» и не выполняет JavaScript predicate.

## Input

```text
session_id
page_id
condition: discriminated union
```

Duration:

```json
{"type":"duration","milliseconds":1000}
```

`milliseconds`: 0..10000.

URL:

```json
{"type":"url","match":"contains","value":"/result","timeout_ms":10000}
```

- match exact|contains;
- value 1..4096;
- timeout 100..30000 default10000.

Element state:

```json
{"type":"element_state","element_ref":"el_...","state":"visible","timeout_ms":10000}
```

state:

```text
attached | visible | hidden | enabled | disabled
```

Load:

```json
{"type":"load_state","state":"domcontentloaded","timeout_ms":10000}
```

state:

```text
domcontentloaded | load
```

No `networkidle`, regex, free-form text condition or JS predicate core baseline.

## Result

```text
condition_type
satisfied: true on successful outcome
elapsed_ms
page_generation
```

Timeout is structured non-success, not fake successful `satisfied=false`.

---

# 29. `browser_upload`

## Description

> Прикрепляет один или несколько owner-authorized ContentObjects к file-input `element_ref`. Не принимает local filesystem path. Если передано несколько файлов, target control должен поддерживать multi-file input; иначе вызов rejected без silent truncation.

## Input

```text
session_id
page_id
element_ref
content_ids: array[ContentId] required, 1..16, unique
```

All ContentObjects owner-authorized and `available`.

Server materializes only bounded temporary files inside session-private temp root.

## Result

```text
action_id
contents: ContentRef[] in input order
page_generation
```

---

# 30. `job_get`

## Description

> Возвращает текущее состояние одного или нескольких durable Jobs, progress, retry/attempt summary и terminal result references. Используйте после `web_fetch_job` или `content_parse_job`.

## Input

```text
job_ids: array[JobId] required, 1..8, unique
```

## Result item

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

No raw queue/worker ID.

---

# 31. `job_cancel`

## Description

> Запрашивает отмену одного или нескольких durable Jobs. Отмена cooperative: успешный ответ может означать `cancelling`, а не мгновенный `cancelled`. Повторный cancel terminal Job идемпотентен.

## Input

```text
job_ids: array[JobId] required, 1..8, unique
```

## Result item

```text
job_id
state: cancelling | cancelled | already_terminal
```

Completed ContentObjects/results are not deleted.

---

# 32. Exact catalog invariant

Core freeze candidate contains exactly **28 tools**:

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
browser_scroll
browser_wait
browser_upload
job_get
job_cancel
```

No aliases/core tools:

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

Any additive tool requires semantic intent + execution-class + compatibility review.

---

# 33. Actual FastMCP schema acceptance

Tests connect with real MCP client and retrieve actual registered schemas.

For every tool verify:

1. exact name;
2. Russian tool description;
3. every nested property description;
4. required fields;
5. defaults;
6. enums/numeric/list/string bounds;
7. unknown fields rejected;
8. discriminated unions valid Draft 2020-12 JSON Schema/equivalent;
9. positive/negative fixtures pass generated schema + runtime validation;
10. no hidden Context/provider secret/worker ID/CSS/XPath/storage key/framework field;
11. MCP annotations match §3;
12. own-agent trusted retry metadata follows ADR-0024 where stricter than annotation;
13. result remains bounded;
14. form fail-fast, structured key, multi-upload and scroll semantics have dedicated contract tests.

v0.8 freezes generated fixture only after this suite is green.
