# MCP facade design

## Статус документа

Этот документ является каноническим владельцем **LLM-facing MCP projection** Web Access MCP.

MCP является компактным facade над уже спроектированными application capabilities.

Он не является копией REST API и не должен определять backend architecture.

---

# 1. Главная цель

MCP должен позволять LLM эффективно выполнять почти все практически полезные web-access workflows через небольшой набор однозначных инструментов.

Критерий качества MCP surface:

> модель понимает, какой tool выбрать по краткому каталогу, а после получения полной schema может сформировать корректный вызов без догадок и без знания внутренних технологий сервиса.

---

# 2. Основной consumer

Главный consumer — собственный `internet-search-bot`, где external MCP tools используются через workflow:

```text
mcp_list_tools
→ model видит name/server/description
→ mcp_get_tool_schema выбранного tool
→ model получает description + inputSchema
→ mcp_call_tool
```

Следовательно существуют два уровня agent UX:

1. **Tool description** — discovery/выбор инструмента.
2. **Input JSON Schema** — корректное построение вызова.

Оба уровня являются частью контракта.

Другие MCP-compatible clients также должны корректно использовать сервер без знания архитектуры собственного агента.

---

# 3. Transport

Production builtin integration использует:

```text
Streamable HTTP
```

MCP endpoint является отдельным facade того же application service, что и REST.

Он не владеет BrowserSession/Job/Content lifecycle и не связывает resources с lifetime одного MCP connection.

---

# 4. MCP и REST не вызывают друг друга

```text
MCP tool
→ mapper
→ Application Service
```

Запрещено:

```text
MCP tool → HTTP request на собственный REST endpoint
```

Это создало бы лишний transport hop и две независимые validation/error layers.

---

# 5. Язык agent-facing contract

Преимущественно на русском пишутся:

- tool docstrings/descriptions;
- field descriptions;
- enum/value descriptions, где framework позволяет;
- repairable validation messages;
- warnings;
- structured hint messages;
- human-readable errors.

На английском остаются:

- tool names;
- field names;
- machine-readable codes/enums/IDs;
- Python identifiers.

---

# 6. Один intent — один tool

Не допускаются параллельные aliases:

```text
web_fetch
web_fetch_many
web_read
read_page
get_url
```

Canonical tool один.

Если tool отличается, его назначение должно быть объяснимо отдельным semantic intent.

---

# 7. Batch-first

Stateless independent operations принимают списки.

Canonical examples:

```text
web_search(queries=[...])
web_fetch(urls=[...])
content_parse(content_ids=[...])
browser_close(session_ids=[...])
job_get(job_ids=[...])
job_cancel(job_ids=[...])
```

Один item передаётся как список из одного элемента.

Stateful sequential browser actions не batch-ятся механически.

---

# 8. Простая schema важнее механической полноты backend

MCP intentionally скрывает:

- Redis/cache controls;
- arbitrary timeout knobs;
- raw provider protocol fields;
- HTTP headers/cookies;
- Playwright context options;
- worker routing;
- database/job attempt internals;
- ContentStore backend.

Если параметр редко нужен LLM и является infrastructure control, он остаётся REST/config capability.

---

# 9. Но MCP не должен быть игрушечным

Упрощение означает хороший abstraction, а не потерю полезной мощности.

Через MCP агент должен уметь:

- искать;
- получать известные URL;
- читать сохранённые ContentObjects;
- запускать Native Parsing существующего content;
- создавать browser session;
- навигировать/наблюдать/interact;
- работать с tabs;
- получать screenshots/downloads;
- загружать ContentObject в форму;
- читать console/network events;
- проверять/cancel durable Jobs.

---

# 10. Tool description — discovery contract

Первый абзац description должен отвечать:

> Что делает tool?

Следующий короткий блок при необходимости:

> Когда его использовать и чем он отличается от соседнего tool?

Пример принципа:

```text
web_search
→ найти URL

web_fetch
→ получить содержимое уже известного URL обычным HTTP

browser_navigate/browser_snapshot
→ работать с stateful JavaScript browser session
```

Description не должен быть длинной implementation документацией.

---

# 11. Cross-references между соседними tools

Если два tools легко перепутать, descriptions должны явно разводить их.

Пример для `web_search`:

> Результаты поиска содержат ссылки и поисковые snippets, но не являются прочитанным содержимым целевых страниц. Для получения выбранных URL используйте `web_fetch`.

Пример для `web_fetch`:

> Выполняет обычное HTTP(S)-получение и Native Parsing. Не запускает управляемый браузер и не выполняет JavaScript. Если полученного статического содержимого недостаточно, используйте browser tools по результатам diagnostics/hints.

---

# 12. Field descriptions обязательны

Каждое публичное input property, включая nested items, должно иметь русскоязычное описание.

Описание объясняет:

- смысл;
- единицы/формат;
- default/omission semantics;
- ограничения;
- связи с другими полями, если есть.

Тип `string` без description недостаточен.

---

# 13. Machine-readable constraints

Если существует invariant, он по возможности выражается JSON Schema:

- `minItems` / `maxItems`;
- `minLength` / `maxLength`;
- numeric bounds;
- `enum`;
- `format`;
- discriminated `oneOf`/union;
- required fields.

Prose не заменяет machine-readable constraint.

---

# 14. Cross-field constraints

Pydantic/runtime validation и фактическая MCP JSON Schema должны согласовываться.

Если разрешено ровно одно из полей/variant:

```text
runtime validator
+
actual schema oneOf/discriminator
+
positive/negative schema tests
```

Это следует проверенному подходу MCP schema testing существующих сервисов проекта.

---

# 15. Unknown fields

Input models должны запрещать неизвестные fields.

LLM typo не должно молча игнорироваться.

Validation result возвращает repairable field error.

---

# 16. Null/omitted/default

Каждое optional field имеет ясную semantics.

Если omission означает configured/default behavior, это написано прямо.

Не следует создавать `null` как отдельное третье состояние без необходимости.

---

# 17. Agent-facing enums

Enums выражают собственные stable concepts Web Access.

Например:

```text
safe_search = off | moderate | strict
```

Не следует выдавать LLM raw provider/browser enum вроде Yandex `lr` или Playwright private locator type.

---

# 18. Dynamic infrastructure values

Не все runtime values должны становиться dynamic schema enum.

Например:

- enabled provider health;
- worker IDs;
- Content parser IDs;

обычно не нужны в MCP schema.

Schema должна оставаться versionable/stable.

---

# 19. Tool result envelope

Expected application outcomes возвращаются как structured tool result, а не только как thrown MCP exception.

Концептуально:

```json
{
  "operation_id": "...",
  "outcome": "succeeded",
  "data": {},
  "error": null,
  "warnings": [],
  "hints": []
}
```

Это позволяет LLM исправлять validation/policy errors и понимать `unknown`/partial semantics.

---

# 20. MCP protocol errors vs application errors

MCP-level protocol/transport failure используется для ситуаций, где tool call невозможно корректно обработать как application operation.

Ожидаемые domain/application failures:

- invalid URL;
- provider unavailable;
- stale element_ref;
- session expired;
- unsupported Native Parser;

возвращаются structured result envelope.

---

# 21. Result size

Tool result всегда bounded.

Большие данные возвращаются через:

- preview;
- metadata;
- ContentRef;
- cursor для последующего `content_get`.

Нельзя вставлять гигантский HTML/PDF text/base64 screenshot в один tool result.

---

# 22. Structured hints

Hints являются особенно полезной частью agent-facing MCP.

Примеры:

```text
browser_may_be_required
advanced_processing_may_be_required
snapshot_refresh_recommended
verify_browser_state
processing_requires_job
alternative_representation_available
```

Hint содержит trusted code/message/context отдельно от untrusted page/document content.

LLM сама решает, следовать ли hint.

---

# 23. Warning vs Hint vs Error

MCP schema должна сохранять различие:

```text
Warning
→ ограничение текущего результата

Hint
→ возможный следующий шаг

Error
→ причина non-success outcome
```

Нельзя сливать всё в `message: string`.

---

# 24. Tool annotations

Каждый tool получает корректные MCP annotations там, где FastMCP/MCP версия их поддерживает.

Annotations должны согласовываться с trusted execution semantics собственного агента.

Минимально учитываются:

- readOnly;
- destructive/external side effect;
- idempotency;
- open-world interaction.

Tool output не назначает себе trusted retry policy агента.

---

# 25. Builtin integration metadata

Для собственного агента Web Access подключается как `builtin` MCP service.

Agent-side trusted descriptor определяет:

- capability/operation kind;
- safe/idempotent/never-automatic retry class;
- timeout profile;
- presentation profile;
- required permissions/budgets;
- remote-resource behavior;
- cleanup operation.

MCP schema должна быть совместима с этим descriptor, но сама не становится источником trust metadata.

---

# 26. Remote BrowserSession handle

`browser_create` возвращает opaque `browser_session_id`.

Agent trusted integration знает, что:

```text
resource_type = browser_session
cleanup tool = browser_close
```

Service result не может подменить cleanup tool произвольным текстом.

---

# 27. Content/Job handles

ContentRef и JobRef также structured/opaque.

Content обычно очищается server retention policy и не требует agent lifecycle cleanup.

Active Job может поддерживать explicit `job_cancel`, но Job lifecycle не должен автоматически привязываться к AgentCycle без отдельной trusted policy.

---

# 28. MCP progress

Server может использовать MCP technical progress для реально долгих request-bound tools, если transport/client поддерживает его стабильно.

Но:

- canonical user progress собственного агента создаёт Agent Runtime;
- server progress не задаёт финальный UI text;
- web content не используется как trusted progress message;
- durable long-running work предпочтительно возвращает Job handle вместо удержания MCP call бесконечно.

---

# 29. Tool naming convention

Tool names:

- lowercase `snake_case`;
- отражают semantic capability;
- без version number в обычном имени;
- без provider name, если operation provider-agnostic;
- без `many` для batch-first tools.

Namespaces по смыслу:

```text
web_*
content_*
browser_*
job_*
```

---

# 30. Предлагаемый core tool catalog

На основании полного backend design предлагается следующий compact baseline:

```text
Web
  web_search
  web_fetch

Content
  content_get
  content_parse

Browser lifecycle/observation
  browser_create
  browser_close
  browser_navigate
  browser_snapshot
  browser_content
  browser_tabs
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

Jobs lifecycle
  job_get
  job_cancel
```

Это **design baseline**, а не требование реализовать все tools в одной первой version.

Version roadmap определит появление capabilities по этапам.

---

# 31. Почему нет `web_read` / `web_read_many`

Получение известных URL имеет один intent:

```text
web_fetch(urls=[...])
```

Один URL — список из одного элемента.

Никаких параллельных single/many tools.

---

# 32. Почему `web_fetch` не имеет browser mode

`web_fetch` всегда означает ordinary Retrieval + allowed L0/L1 Content processing.

Он не принимает:

```text
mode = auto
mode = browser
```

Browser запускается только отдельными browser tools.

Это сохраняет прозрачную orchestration.

---

# 33. `web_search`

Предлагаемая MCP semantics:

```text
web_search(
    queries: list[str],
    provider = "default",
    page = 1,
    limit = <default>,
    language = null,
    region = null,
    safe_search = null,
    time_range = null,
)
```

MCP намеренно использует **общие options для всего batch**, а не массив сложных query objects.

Если модели нужны разные providers/pages/options, она делает отдельные tool calls.

Это упрощает schema без появления `search_many`.

---

# 34. `web_search.provider`

MCP может использовать agent-facing enum:

```text
default
searxng
yandex
```

где `default` маппится в application configured default provider.

Наличие enum value не гарантирует runtime readiness/configuration конкретного provider; unavailable provider возвращает structured error.

Если provider registry станет extensible динамически, schema strategy пересматривается без добавления arbitrary provider dict.

---

# 35. `web_search` description principle

Пример смыслового description:

> Ищет в интернете по одному или нескольким независимым запросам и возвращает поисковые результаты: заголовки, URL, snippets и metadata. Используйте для поиска подходящих источников. Snippet не является прочитанным содержимым целевой страницы; для получения выбранных URL используйте `web_fetch`.

Точный текст будет зафиксирован в implementation schema tests.

---

# 36. `web_fetch`

Предлагаемая MCP semantics:

```text
web_fetch(
    urls: list[HttpUrl]
)
```

MCP mapping использует backend processing level:

```text
native
```

то есть:

```text
safe Retrieval
→ Content L0
→ доступный L1 Native Parsing
```

без L2 и без Browser fallback.

---

# 37. `web_fetch` result

Per URL result должен быть полезен LLM сразу:

- requested/final URL;
- HTTP status;
- detected content format;
- small metadata;
- наиболее полезное доступное native representation/preview;
- ContentRefs raw/derived;
- warnings/hints.

Большой text возвращается preview + ContentRef/cursor.

---

# 38. Canonical native representation selection в MCP

MCP может иметь детерминированный format-specific preferred representation:

```text
HTML/article-like → Markdown/text representation
PDF native text → text
JSON/XML/tabular → structured/text representation
image/binary without native text → metadata + ContentRef
```

Это transport presentation rule, а не reasoning heuristic.

Client может использовать `content_get` для выбора другой доступной representation.

---

# 39. `content_get`

Назначение:

> Прочитать уже существующий ContentObject/derived representation без повторного HTTP/Browser acquisition.

Batch-friendly input лучше представить как список read items, потому что у каждого ContentObject может быть собственный cursor:

```text
items[]:
  content_id
  cursor | null

representation = auto | text | markdown | structured
```

`cursor` opaque.

Tool возвращает bounded chunks + `next_cursor`.

---

# 40. `content_parse`

Назначение:

> Запустить доступный L1 Native Parsing для одного или нескольких уже существующих raw ContentObjects.

Input:

```text
content_ids[]
```

Tool не принимает parser ID от обычной LLM: registry сам выбирает canonical parser по detected format.

Result:

- inspection;
- derived ContentRefs;
- available representations;
- unsupported/job-required diagnostics/hints.

No OCR/L2 fallback.

---

# 41. `browser_create`

Создаёт одну ephemeral BrowserSession и initial blank page.

Baseline MCP input может быть пустым либо содержать только реально нужные stable future options.

Не следует сразу публиковать Playwright profile/context knobs.

Result:

```text
browser_session_id
initial page_id
session state/lifetime metadata
```

---

# 42. Почему `browser_create` не принимает URL baseline

Backend create и navigate имеют разные lifecycle/failure semantics.

MCP не должен скрывать partial result:

```text
session создана, navigation failed
```

ради экономии одного tool call.

После create модель вызывает `browser_navigate` явно.

Если позднее usage покажет значимую пользу composed `browser_open`, это отдельное facade decision.

---

# 43. `browser_close`

Batch-first cleanup:

```text
browser_close(session_ids: list[str])
```

Идемпотентный tool для явного cleanup.

Agent trusted lifecycle hook использует этот tool для BrowserSession handles.

Per-session result сохраняет `closed/already_terminal/lost` semantics.

---

# 44. `browser_navigate`

Один tool покрывает navigation intent.

Input может использовать discriminated destination:

```text
{"type":"url", "url":"https://..."}
{"type":"back"}
{"type":"forward"}
{"type":"reload"}
```

Это семантически одна область navigation и не требует четырёх почти одинаковых tools.

---

# 45. `browser_snapshot`

Возвращает semantic structured snapshot конкретной page.

Input:

```text
session_id
page_id
```

Result содержит:

- snapshot_id;
- page_generation/revision metadata;
- semantic tree;
- `element_ref`s.

Screenshot не включается автоматически.

---

# 46. `browser_content`

Назначение отличается от snapshot:

> Получить rendered содержимое текущей browser page как документ и передать его в Content Native Parsing.

Flow:

```text
rendered DOM/HTML
→ Content ingest(native)
→ ContentRefs/preview
```

Используется, когда browser уже отрендерил JS page и агент хочет прочитать её как документ, а не взаимодействовать по accessibility snapshot.

---

# 47. `browser_snapshot` vs `browser_content`

Descriptions должны явно различать:

```text
browser_snapshot
→ интерактивная структура страницы и element_refs

browser_content
→ содержимое страницы как документ для чтения/анализа
```

Это два реальных intent, поэтому два tools оправданы.

---

# 48. `browser_tabs`

Один semantic tool для tab/page management.

Input использует discriminated command:

```text
list
new
select(page_id)
close(page_id)
```

Tool всегда возвращает актуальный bounded список pages/active page metadata.

---

# 49. `browser_click`

Input:

```text
session_id
page_id
element_ref
```

Tool description предупреждает:

- ref должен происходить из актуального snapshot;
- action может иметь внешний side effect;
- `unknown` нельзя blindly retry.

No CSS/XPath baseline input.

---

# 50. `browser_fill_form`

Один tool заполняет несколько полей одной формы/semantic action.

Input:

```text
session_id
page_id
fields[]:
  element_ref
  value
```

Value schema должна поддерживать typed значения для text/select/checkbox/radio настолько, насколько snapshot contract позволяет.

Tool **не submit** форму автоматически.

Per-field result сохраняет partial mutation semantics.

---

# 51. `browser_type`

Отдельный tool оправдан, потому что `type` не равен `fill`.

Используется, когда странице нужны реальные keyboard/input events/последовательный ввод.

Input содержит target element_ref + text.

---

# 52. `browser_press`

Отдельный keyboard action.

Target element_ref может быть optional, если key должен отправляться page-level keyboard context.

Tool считается потенциально side-effecting: `Enter` может submit форму.

---

# 53. `browser_hover`

Нужен для:

- hover menus;
- tooltips;
- lazy interaction states.

Input target — element_ref.

Не объединяется с click, потому что semantics различаются.

---

# 54. `browser_drag`

Input:

```text
source_element_ref
target_element_ref
```

Используется только для явного drag-and-drop intent.

---

# 55. `browser_wait`

Использует typed/discriminated wait condition, а не одну free-form строку.

Future variants:

- bounded duration;
- URL condition;
- element state;
- text/state condition;
- page load condition.

Schema должна объяснять, что wait не является гарантией semantic completion всего сайта.

---

# 56. `browser_screenshot`

Explicit visual artifact operation.

Input:

- session_id/page_id;
- optional element_ref;
- approved format/view mode options.

Result — image ContentRef + metadata.

No giant base64 result.

---

# 57. `browser_upload`

Input:

```text
session_id
page_id
element_ref
content_id
```

ContentObject ownership проверяется server-side.

No local filesystem path.

Tool potentially side-effecting и never-automatic retry после dispatch.

---

# 58. Downloads не требуют отдельного `browser_download` baseline tool

Download возникает как следствие click/navigation/other explicit action.

Action result/event возвращает ContentRef сохранённого download.

Отдельный tool вида «скачай ссылку» дублировал бы `web_fetch` или click semantics.

Если сайт имеет прямой URL файла — `web_fetch` предпочтительнее Browser.

---

# 59. `browser_events`

Объединяет чтение bounded browser event streams:

```text
console
network
page lifecycle
other safe diagnostics
```

Input:

```text
session_id
page_id | null
types[]
after_sequence | null
limit
```

Один tool лучше отдельных `browser_console` + `browser_network`, потому что underlying operation одна — чтение browser event log с filter.

Untrusted event text ясно отделяется от trusted server metadata.

---

# 60. Dialog tool пока не фиксируется

`browser.md` оставляет dialog protocol открытым.

Поэтому MCP catalog не должен преждевременно публиковать `browser_handle_dialog` до выбора backend semantics.

После ADR tool может быть добавлен additive change.

---

# 61. Arbitrary JavaScript evaluate не входит core MCP

Tool вида:

```text
browser_evaluate
browser_run_code
```

не входит baseline agent-facing surface.

Если позже нужен trusted advanced capability:

- отдельная permission;
- отдельный tool namespace/profile;
- ясный security warning;
- bounded input/output/time.

---

# 62. CSS/XPath locators не входят core MCP

LLM работает через element_ref semantic snapshots.

Причины:

- меньше хрупких selectors;
- меньше hallucinated DOM assumptions;
- проще stale detection;
- schema понятнее;
- можно менять internal locator implementation.

Advanced REST locator capability при необходимости проектируется отдельно.

---

# 63. `job_get`

Batch-first read:

```text
job_get(job_ids: list[str])
```

Возвращает:

- state;
- progress summary;
- attempts summary при необходимости;
- terminal result/error;
- ContentRefs;
- warnings/hints.

Tool read-only.

---

# 64. `job_cancel`

Batch-first cancellation request:

```text
job_cancel(job_ids: list[str])
```

Tool description поясняет:

- cancellation cooperative;
- response может означать `cancelling`, а не мгновенно `cancelled`;
- terminal Job cancel idempotent.

---

# 65. Job creation tools domain-specific

Не публикуется generic:

```text
job_create(task, args)
```

Когда появится конкретный durable capability, например crawl, он получает отдельный semantic MCP tool:

```text
web_crawl(...)
→ job_id
```

а lifecycle затем управляется `job_get/job_cancel`.

---

# 66. Native MCP Tasks

Если protocol/SDK/client поддержка MCP Tasks станет достаточно стабильной, Job может дополнительно проецироваться как native Task.

Это transport optimization/projection.

Canonical Web Access Job resource и `job_get/job_cancel` semantics сохраняются для REST/совместимости.

---

# 67. Tool catalog не отражает каждый REST endpoint

Например MCP не обязан иметь tools:

- list providers;
- admin status;
- parser registry;
- raw Content streaming;
- Job event pagination;
- worker topology.

Это programming/operator capabilities REST.

---

# 68. MCP schema versioning

Tool schema является versioned public contract.

Backward-compatible changes:

- новые optional fields;
- additive tools;
- расширения results, если client tolerant.

Breaking input semantics требуют controlled integration version/schema change и agent trusted registry compatibility update.

---

# 69. Stable descriptions

Description является contract и меняется осознанно.

Нельзя генерировать tool description из runtime provider status так, чтобы schema/discovery хаотично менялась между requests.

Runtime availability сообщается tool result/error.

---

# 70. Tool registration

FastMCP tools должны регистрироваться по тематическим modules:

```text
transport/mcp/tools/search.py
transport/mcp/tools/retrieval.py
transport/mcp/tools/content.py
transport/mcp/tools/browser.py
transport/mcp/tools/jobs.py
```

Tool handler остаётся тонким mapper/application call.

---

# 71. MCP Context

FastMCP `Context`/transport runtime parameter является hidden infrastructure dependency и не должен появляться в public input schema.

Tool application parameters описываются отдельными Pydantic/Annotated models.

---

# 72. Schema source of truth

Input schema строится из явных agent-facing models, а не из REST models или provider models.

Это позволяет:

- упростить Search batch до `list[str]`;
- убрать REST-only controls;
- сделать browser refs понятными;
- сохранить русские descriptions.

---

# 73. Actual FastMCP schema tests

Тесты должны поднять реальный FastMCP server/client и получить schema через `list_tools`.

Проверяется **то, что реально видит MCP client**, а не только Pydantic model schema.

---

# 74. Обязательные schema tests

Для каждого tool:

1. Tool description непустой и русскоязычный по смыслу.
2. Каждый public property recursively имеет description.
3. Required fields совпадают с runtime.
4. Defaults отражены.
5. Enum values agent-facing.
6. min/max/list limits machine-readable.
7. Unknown fields rejected runtime.
8. Cross-field `oneOf`/discriminators реально валидируются JSON Schema validator-ом.
9. Hidden Context отсутствует.
10. Provider/infrastructure fields не протекают.
11. Tool annotations корректны.
12. Tool name входит в expected catalog snapshot.

---

# 75. Tool catalog snapshot test

CI хранит canonical expected tool names/categories.

Случайное появление/исчезновение/rename tool должно ломать contract test и требовать явного design/version update.

---

# 76. Description quality tests

Не всё можно проверить автоматически, но минимум можно enforce:

- минимальная разумная длина;
- наличие ссылки на соседний tool там, где confusion risk зафиксирован;
- отсутствие placeholder `TODO`;
- отсутствие английских agent-facing descriptions без explicit exception.

Final semantic review остаётся human/LLM code review gate.

---

# 77. Result contract tests

Каждый tool test должен проверять:

- success envelope;
- structured validation/rejection;
- warning/hint separation;
- ContentRef/JobRef/BrowserSession handle shape;
- partial batch result;
- bounded output;
- no secret/internal paths;
- unknown outcome там, где применимо.

---

# 78. Agent integration tests

Отдельный suite должен воспроизводить workflow собственного агента:

```text
list tools
→ выбрать tool по description
→ get schema
→ call tool
```

Нужно проверить как минимум:

- tool легко различим с соседними;
- schema достаточна для корректного arguments payload;
- browser handle возвращается в ожидаемом field;
- cleanup tool принимает handle contract;
- mutating Browser tools имеют compatible trusted metadata;
- server restart/reconnect не привязывает remote resource к MCP connection;
- large content не переполняет tool result.

---

# 79. Generic MCP client compatibility

Помимо собственного агента тестируется стандартный FastMCP/MCP client без trusted agent metadata.

Он должен:

- discover tools;
- получить schemas;
- вызвать tools;
- работать с handles по documented schema;
- получить structured error.

Web Access не должен требовать private extension `internet-search-bot` для базовой работы.

---

# 80. Server restart

MCP endpoint restart:

- не должен использовать transport session как source of truth BrowserSession;
- после reconnect существующий resource либо остаётся usable через service resource model, либо честно возвращает `lost/expired`;
- tool catalog/schema совместимость проверяется Agent Runtime.

---

# 81. Service authentication

MCP Streamable HTTP endpoint требует service authentication/network policy согласно builtin contract агента/deployment design.

Credentials не попадают в LLM tool schema/context.

Auth failure является transport/service access error, а не hallucinated tool result.

---

# 82. MCP result trust boundary

Search snippets/page text/browser console/content являются untrusted data.

Server-generated:

- error codes;
- hints;
- warnings;
- resource metadata

являются trusted structural metadata только потому, что созданы application layer, а не потому, что находятся в JSON рядом с web text.

Schema должна структурно разделять эти поля.

---

# 83. Presentation ownership

MCP server не определяет финальные сообщения UI собственного агента вроде:

```text
🔎 Ищу...
🌐 Открываю сайт...
```

Agent Runtime использует trusted presentation profile.

Web Access предоставляет semantic tool identity/result/progress facts.

---

# 84. Tool-level technical progress

Если tool публикует progress, messages должны быть:

- краткими;
- техническими;
- без user-interface emoji/style contract;
- без копирования untrusted page text;
- bounded rate.

Agent может проигнорировать/перерисовать их.

---

# 85. Timeouts

MCP caller не получает arbitrary `timeout_seconds` field в каждом tool.

Timeout profiles задаются agent/service configuration/application policy.

Если semantic wait duration действительно является смыслом operation (`browser_wait`), это отдельный application argument, а не infrastructure timeout.

---

# 86. Limits

Hard schema limits должны быть стабильной частью tool contract.

Operator quotas могут быть строже и возвращать policy/capacity error.

Нельзя генерировать хаотически разные schema maxItems per principal request.

---

# 87. Cost/budget

Billable provider вроде Yandex может быть выбран tool parameter, но permission/budget проверяет Agent Runtime/service policy.

Tool description может предупредить, что provider может быть billable.

LLM не передаёт API key/цену.

---

# 88. No auto-pagination

`web_search` возвращает requested page.

Модель сама решает, запросить ли следующую.

Server не выполняет скрытый multi-page search только потому, что `limit` не достигнут.

---

# 89. No auto-follow links

`web_fetch` получает только явно переданные URLs и redirects HTTP protocol.

Он не открывает links из HTML автоматически.

Browser аналогично не кликает следующий link без agent action.

---

# 90. No implicit resource cleanup в обычном tool call

BrowserSession закрывается только:

- `browser_close`;
- service TTL/reaper;
- server lifecycle policy.

Например `browser_snapshot` не закрывает session после response.

---

# 91. MCP output serialization

Serializer должен быть отдельным transport layer.

Application models не должны вручную строить MCP content blocks.

Serializer отвечает за:

- bounded JSON;
- human-readable preview там, где нужен;
- ContentRef/resource rendering;
- safe conversion enums/timestamps;
- no internal fields.

---

# 92. OutputSchema direction

Если используемая FastMCP/MCP версия стабильно поддерживает structured output/output schemas, их следует использовать для typed results.

Однако application correctness не должна зависеть только от client enforcement output schema.

До implementation проверяется совместимость с текущим MCP client собственного агента.

---

# 93. Acceptance criteria MCP facade

MCP считается спроектированным/реализованным, если:

1. MCP вызывает общий application layer, не REST.
2. Core catalog не содержит single/many duplicates.
3. `web_search` batch = `queries: list[str]` с общими options.
4. `web_fetch` не имеет auto/browser mode и выполняет Retrieval + L0/L1 only.
5. Content имеет generic `content_get/content_parse`, а не format-specific tool explosion.
6. Browser lifecycle explicit и использует opaque session/page/snapshot/element refs.
7. `browser_snapshot` и `browser_content` чётко разделены.
8. Stateful interactions semantic, без giant arbitrary action/tool.
9. Fill Form поддерживает несколько fields без auto-submit.
10. Downloads возвращаются ContentRefs и не требуют duplicate download tool.
11. Console/network сведены в bounded `browser_events`.
12. Arbitrary JS/CSS/XPath не входят baseline LLM surface.
13. Job creation domain-specific; generic lifecycle = `job_get/job_cancel`.
14. Все descriptions/field descriptions agent-facing и преимущественно русские.
15. Actual FastMCP schemas contract-tested recursively.
16. Expected application failures structured/repairable.
17. Giant results заменяются ContentRef/cursor.
18. Structured hints/warnings/errors разделены.
19. Tool annotations и Agent trusted metadata согласованы.
20. BrowserSession handle соответствует builtin remote-resource lifecycle contract агента.
21. MCP reconnect не определяет resource lifecycle.
22. Generic MCP client также способен использовать сервер.

---

# 94. Open questions

До implementation MCP facade необходимо закрыть:

1. Exact final tool names/catalog после Browser dialog/wait decisions.
2. Exact `web_search` maxItems/limit defaults/hard limits.
3. Exact `SearchRegion` MCP schema.
4. Exact `web_fetch` result preferred representation schema.
5. Exact `content_get` cursor/representation model.
6. `content_parse` result/Job-required semantics.
7. Exact Browser Snapshot schema и element_ref wire format.
8. `browser_tabs` discriminated command schema.
9. `browser_wait` variants.
10. Dialog tool после Browser ADR.
11. Whether `browser_drag`/`hover` входят initial tool version или additive later capability.
12. Exact `browser_events` event types/cursor.
13. MCP tool result outputSchema support после проверки FastMCP/client compatibility.
14. Native MCP Tasks projection.
15. Service auth mechanism Streamable HTTP.
16. Agent-side trusted presentation profile/tool metadata mappings в `internet-search-bot`.
17. Exact remote-resource handle field-path metadata для agent registry integration.

Эти вопросы закрываются перед соответствующими version implementation patches, не меняя основных MCP UX principles.
