# Browser subsystem design

## Статус документа

Этот документ является каноническим владельцем **BrowserSession lifecycle, browser action protocol, page/target identity, worker ownership, ordering, failure semantics и интеграции Browser ↔ Content** в Web Access MCP.

Он не фиксирует окончательный MCP tool catalog и не определяет конкретный Control Plane ↔ Browser Worker transport. Эти projections/решения проектируются позже.

---

# 1. Purpose

Browser предоставляет управляемую stateful browser capability для случаев, когда обычного Search/Retrieval/Native Parsing недостаточно или клиенту требуется реальное взаимодействие с web application.

Browser отвечает на вопросы:

> Как открыть и сохранить состояние web application между несколькими operations?

> Как наблюдать текущее состояние страницы и выполнить контролируемое browser action?

> Как безопасно завершить browser state и сохранить нужные artifacts вне Browser Worker?

---

# 2. Responsibilities

Browser отвечает за:

- создание managed BrowserSession;
- создание/учёт страниц внутри session;
- navigation;
- structured page observation/snapshot;
- stateful interactions;
- tabs/popups/pages lifecycle;
- bounded console/network diagnostics;
- screenshots;
- downloads/uploads через Content boundary;
- session ownership и routing owning Browser Worker;
- сериализацию действий внутри BrowserSession;
- action identity/deduplication на runtime boundary;
- deadlines/cancellation;
- state/revision metadata;
- `unknown outcome` для неопределённых side effects;
- TTL/max lifetime/reaper;
- worker-loss handling;
- security/egress policy;
- observability.

---

# 3. Non-goals

Browser не должен:

- выполнять agent reasoning;
- автоматически запускаться после Retrieval;
- самостоятельно выбирать сайт из Search results;
- обходить CAPTCHA/anti-bot protection как гарантированную capability;
- поддерживать stealth/fingerprint evasion по умолчанию;
- предоставлять unrestricted shell/Python execution;
- предоставлять unrestricted arbitrary JavaScript execution обычному principal;
- сохранять persistent authentication profile без отдельного design;
- автоматически подтверждать потенциально опасные внешние действия;
- становиться generic remote desktop/browser UI.

---

# 4. Базовый browser engine

Первоначальное направление реализации:

```text
Playwright Python
+
Chromium
```

Application contract не должен раскрывать Playwright objects/locator implementation.

Другой browser engine может быть добавлен позднее только если существует реальная потребность и совместимая application semantics.

---

# 5. BrowserContext как live session substrate

Одна `BrowserSession` концептуально соответствует одному изолированному non-persistent browser context.

Это даёт независимые:

- cookies;
- local/session storage;
- permissions;
- pages/tabs.

При этом BrowserContext является изоляцией browser state, **но не security sandbox всего сервиса**. OS/container/network boundaries остаются обязательными согласно `security.md`.

---

# 6. Ephemeral sessions — canonical default

Базовая BrowserSession создаётся как ephemeral/non-persistent.

Она не должна автоматически сохранять cookies/storage после закрытия.

Persistent browser profiles не входят в базовый Browser contract.

Если они будут добавлены позднее, потребуется отдельный resource/security design с encrypted storage, ownership, revocation, expiration и audit.

---

# 7. Browser Worker владеет live state

Только owning Browser Worker содержит фактические:

```text
Browser
BrowserContext
Page
Locator/runtime targets
pending browser events
```

Control Plane хранит application metadata и routing information, но не Playwright objects.

---

# 8. Browser process model

Этот design не фиксирует, что один Browser Worker обязан иметь ровно один Chromium process.

Worker может управлять:

- одним Browser process с несколькими BrowserContexts;
- bounded pool Browser processes;

если это соответствует capacity/security design.

Инварианты:

- одна BrowserSession имеет ровно один live BrowserContext;
- session принадлежит одному active worker;
- browser process crash корректно отражается на всех затронутых sessions;
- internal pool topology не протекает в public handles.

---

# 9. Основные application operations

Browser backend должен поддерживать семантические операции следующих классов:

```text
Session lifecycle
Page lifecycle/navigation
Observation
Interaction
Files/artifacts
Diagnostics
```

Точные REST/MCP names проектируются позже.

---

# 10. Session creation

Концептуально:

```text
BrowserApplicationService.create_session(
    ExecutionContext,
    BrowserSessionCreateRequest,
) -> OperationResult[BrowserSessionCreated]
```

Creation должна:

1. проверить ownership/policy/capacity;
2. выбрать Browser Worker;
3. создать durable/application session metadata в `creating`;
4. запросить создание live BrowserContext;
5. создать initial blank page;
6. зарегистрировать page identity;
7. перевести session в `ready`;
8. вернуть `browser_session_id` + initial `page_id`.

Crash windows должны быть reconciled согласно persistence/resource design.

---

# 11. Initial blank page

Успешная BrowserSession создаёт одну initial page.

Это делает lifecycle детерминированным:

```text
create session
→ session_id + page_id
→ navigate page
```

Navigation не должна скрыто создавать первую page в зависимости от внутреннего состояния.

---

# 12. BrowserSession handle

`browser_session_id` является opaque Resource handle.

Client не знает:

- owning worker;
- BrowserContext ID;
- Chromium process;
- filesystem profile path.

Каждая operation валидирует session ownership/state.

---

# 13. BrowserPage identity

Каждая live page/tab получает opaque `page_id`, scoped к BrowserSession.

`page_id`:

- не является Playwright internal ID;
- недействителен вне session;
- удаляется/становится terminal при закрытии page;
- создаётся также для popup/new-tab events;
- наследует ownership BrowserSession.

---

# 14. Page lifecycle

Предварительные live states:

```text
open
closing
closed
lost
```

Page является session child, поэтому потеря/закрытие BrowserSession инвалидирует все live pages.

Точная persistence page state может быть process-local + session metadata; durable Page rows не являются обязательным foundation requirement.

---

# 15. Popup/new page handling

Если web application создаёт новую page/popup:

1. Browser Worker перехватывает событие;
2. назначает новый `page_id`;
3. добавляет page в session registry;
4. operation result/event сообщает о созданной page;
5. subsequent actions используют новый page_id явно.

Нельзя терять popup только потому, что action был направлен на parent page.

---

# 16. Active/default page

Application может хранить `active_page_id` как convenience state, но **каждая state-sensitive browser operation должна иметь однозначный target page**.

MCP facade позднее может скрывать `page_id` в простом single-page сценарии, но backend contract не должен зависеть от неявного global current tab.

---

# 17. Session-level serialization

Все browser operations одной BrowserSession проходят через один логический serial execution lane.

```text
Session A: action1 → action2 → snapshot3
Session B: может исполняться параллельно
```

Даже операции разных pages одной session по умолчанию сериализуются.

Причины:

- cookies/storage shared context;
- popups/network events могут затронуть context;
- упрощается ordering;
- уменьшаются races между snapshot и mutating action;
- понятнее `unknown outcome`/revision semantics.

Позднее safe parallel read operations можно разрешить отдельным design, но они не являются baseline.

---

# 18. BrowserOperationId / action_id

Каждый dispatched Browser Worker command получает стабильный `action_id`, связанный с application `operation_id`.

`action_id` нужен для:

- duplicate internal delivery detection;
- tracing;
- worker action ledger;
- восстановления результата после transport retry, если он уже известен;
- предотвращения случайного двойного исполнения mutating command.

Public REST/MCP client не обязан самостоятельно генерировать internal action_id.

---

# 19. Worker-side action deduplication

Owning Browser Worker должен иметь bounded session-scoped ledger recent action IDs.

При повторной доставке того же `action_id`:

- если terminal result известен → вернуть сохранённый terminal result;
- если action ещё executing → вернуть/дождаться того же execution согласно protocol;
- если outcome был потерян и доказать его нельзя → вернуть `unknown`, а не исполнить действие снова;
- несовместимый payload с тем же action_id → conflict/rejected.

Точная durable/ephemeral ledger implementation зависит от выбранного worker transport.

---

# 20. Session command revision

BrowserSession имеет монотонную logical `revision`, отражающую принятые server-controlled transitions/commands.

Revision **не означает версию DOM**: JavaScript может менять DOM самостоятельно без команды Web Access.

Revision используется для:

- diagnostics;
- ordering;
- stale client state detection;
- связывания snapshots/actions;
- optimistic checks там, где они полезны.

Нельзя обещать, что одинаковая revision гарантирует неизменный DOM.

---

# 21. Page generation

Для page полезно иметь `generation`, которая меняется при document replacement/navigation lifecycle, делающем старые element references заведомо недействительными.

`page_generation` отличается от session revision.

Она позволяет быстро rejected stale snapshot targets после navigation.

Точный trigger generation increment определяется implementation/browser event model.

---

# 22. Structured Browser Snapshot

Основным agent/programmatic представлением страницы является **структурированный semantic snapshot**, а не screenshot.

Snapshot должен позволять понять:

- URL/title;
- page identity/generation;
- meaningful visible/interactive structure;
- roles/names/text;
- actionable element references;
- relevant state (`checked`, `disabled`, `expanded`, value и т.п.);
- document/frame context настолько, насколько это требуется action protocol.

Implementation может опираться на accessibility/ARIA/DOM semantics Playwright, но public schema не должна быть копией private Playwright object tree.

---

# 23. Snapshot identity

Каждый snapshot получает opaque/session-scoped `snapshot_id`.

Snapshot metadata включает:

```text
session_id
page_id
page_generation
session revision
created_at
```

Snapshot может быть transient и не обязан становиться durable Resource.

Если snapshot слишком большой для inline result, он может быть сохранён как ContentObject/structured representation согласно общей Content policy.

---

# 24. ElementRef

Интерактивные элементы snapshot получают opaque `element_ref`.

`element_ref` scoped к:

```text
BrowserSession
+ BrowserPage
+ snapshot/page generation
```

Он не должен быть raw CSS/XPath selector и не должен требовать от LLM знания DOM implementation.

---

# 25. ElementRef resolution

Browser Worker хранит/может восстановить безопасный locator recipe для element_ref.

При action:

1. проверяется session/page;
2. проверяется generation/snapshot validity;
3. target разрешается в текущей page;
4. неоднозначный/исчезнувший target rejected как stale/ambiguous;
5. Playwright actionability checks выполняются перед action.

Нельзя «угадывать ближайший похожий элемент», если ref больше не разрешается однозначно.

---

# 26. Snapshot reference lifetime

ElementRefs являются краткоживущими capability references.

Они должны инвалидироваться как минимум при:

- page generation change;
- page close;
- session close/loss;
- explicit snapshot invalidation policy.

Новый snapshot может сделать предыдущий набор refs stale согласно implementation policy.

Exact retention количества snapshot maps определяется Browser Worker memory policy.

---

# 27. DOM меняется без команд

Web applications динамичны.

Даже валидный element_ref может перестать существовать из-за таймера/XHR/SPA update между snapshot и action.

В этом случае result должен быть:

```text
rejected/failed: stale_target | target_not_found | target_ambiguous
```

с hint сделать новый snapshot.

Сервис не должен автоматически искать «похожую кнопку» и кликать её.

---

# 28. Actionability

Для locator-based interactions используются стандартные Playwright actionability/auto-wait semantics.

Например click должен требовать однозначный элемент и соответствующие visibility/stability/event/enabled условия согласно Playwright operation.

Actionability timeout ограничен operation deadline.

---

# 29. `force` не является обычным capability

Опции, отключающие стандартные actionability protections (`force` и эквиваленты), не должны быть доступны обычному MCP interaction contract по умолчанию.

Если advanced REST/admin capability понадобится, она требует отдельной permission/security semantics.

---

# 30. Navigation

`navigate` — явная operation над конкретной page.

Она:

- проверяет target URL security policy;
- выполняет top-level navigation;
- наблюдает redirect/final URL;
- обновляет page generation;
- возвращает navigation metadata;
- сообщает созданные downloads/popups/events, если они возникли;
- не выполняет Content extraction автоматически, если request не имеет отдельной explicit composed semantics.

---

# 31. Browser egress policy

Top-level URL validation недостаточна.

Browser Worker должен применять policy к browser-initiated network requests/subresources настолько, насколько выбранная implementation позволяет, а deployment дополнительно ограничивает private/internal egress.

Blocked subresource:

- не получает доступ к internal network;
- фиксируется в bounded diagnostics;
- не обязательно делает всю navigation failed, если страница продолжила работу.

Top-level target policy violation rejected до navigation.

---

# 32. Interaction classes

Backend должен поддерживать семантические action types, а не один unrestricted `browser_action(dict)`.

Минимальные классы, которые требуется подробно спроектировать в implementation/projection:

```text
click
fill/form fill
type
select
check/uncheck
press key
hover
wait
page/tab management
```

Окончательный MCP tool split проектируется позже.

---

# 33. Fill vs Type

Различаются две semantics:

- `fill` — установить значение form field;
- `type` — эмулировать последовательный keyboard input.

Они не должны быть случайными алиасами.

MCP может предпочесть более высокоуровневый `fill_form` для нескольких независимых полей одного логического form-fill action.

---

# 34. Fill Form как семантический batch

Заполнение нескольких полей формы может быть одной логической operation:

```text
fill_form(fields[])
```

Это допустимый batch, потому что элементы принадлежат одному явному semantic intent.

Но execution result должен учитывать возможность partial mutation:

- какие fields успешно изменены;
- на каком поле произошёл failure;
- aggregate outcome;
- неизвестен ли итог при transport loss.

Fill Form не должен автоматически submit форму.

---

# 35. Click side effects

Click может:

- изменить DOM;
- выполнить navigation;
- открыть popup;
- начать download;
- отправить форму;
- инициировать внешний server-side side effect.

Поэтому click относится к `never_automatic` retry class после dispatch.

Transport failure после dispatch может приводить к `unknown`.

---

# 36. Press key side effects

`press` также потенциально mutating:

- Enter может submit форму;
- shortcut может изменить page/state.

Поэтому нельзя автоматически считать keyboard actions safe retry только потому, что они «локальные».

Retry classification определяется конкретным action type/phase.

---

# 37. Navigation retry

Top-level navigation обычно ближе к idempotent/read operation, но Web Access не должен обещать полную idempotency внешнего URL: GET/navigation может иметь application-level effects на target site.

Automatic retry после явно подтверждённого response loss должен быть консервативным и ограничиваться pre-dispatch/connect stages, если нет более сильной guarantee.

---

# 38. Action result

Canonical browser action result должен содержать наблюдаемые последствия.

Предварительно:

```text
BrowserActionResult
├── action_id
├── session/page identity
├── before/after revision
├── page generation
├── current/final URL
├── created_pages[]
├── closed_pages[]
├── content/download refs[]
├── warnings/hints[]
└── action-specific data
```

Не все поля присутствуют у каждого action.

---

# 39. Unknown outcome

Если action был dispatched owning worker и мог произвести side effect, но terminal result нельзя восстановить:

```text
outcome = unknown
```

Client/agent должен выполнить безопасную read-only verification:

- snapshot;
- pages list;
- current URL;
- другой observation.

Web Access может вернуть hint `verify_browser_state`.

Blind retry запрещён.

---

# 40. Worker transport failure до dispatch

Если Control Plane может доказать, что command не был принят owning worker:

```text
before_dispatch failure
```

может быть retried согласно operation deadline/policy.

Граница «принят worker-ом или нет» должна поддерживаться выбранным internal transport protocol.

Это одно из требований к ADR Control Plane ↔ Browser Worker.

---

# 41. Worker loss

При подтверждённой потере owning worker/browser process:

```text
BrowserSession → lost
```

Все live pages/element refs становятся invalid.

Pending action может получить:

- `unknown`, если side effect мог произойти;
- `failed/resource_lost`, если известно, что action не был выполнен.

Service не создаёт silent replacement session.

---

# 42. Session lifecycle

Используется state model `resource-model.md`:

```text
creating
ready
closing
closed
expired
lost
failed
```

Browser operations разрешены только в states, явно поддерживаемых их contract.

Новые actions не принимаются после `closing`.

---

# 43. Idle TTL

BrowserSession имеет configurable idle TTL.

`last_activity_at` обновляется при принятых session operations согласно единой server policy.

Reaper не должен закрыть session, пока в ней выполняется зарегистрированная in-flight operation.

Точная lease/lock coordination между action и reaper проектируется вместе с worker routing.

---

# 44. Maximum lifetime

Помимо idle TTL должен поддерживаться hard maximum lifetime BrowserSession.

Это защищает от sessions, которые постоянно «поддерживаются живыми» и никогда не освобождают browser resources.

Точное значение configurable.

При приближении expiration result может содержать lifecycle metadata/hint, но Web Access не обязан продлевать lifetime автоматически.

---

# 45. Client waiting/user pause

Web Access не знает понятие AgentCycle/WAITING_USER собственного агента.

Он знает только BrowserSession activity/lifecycle.

Если агент хочет сохранить session между сообщениями пользователя, он должен уложиться в server TTL policy.

После expiration агент создаёт новую session.

---

# 46. Session close

Explicit close:

1. session → `closing`;
2. перестают приниматься новые actions;
3. bounded wait/cancellation current action согласно policy;
4. нужные downloads/artifacts финализируются;
5. BrowserContext закрывается;
6. worker action/ref state очищается;
7. session → `closed`;
8. terminal metadata сохраняется по retention policy.

Повторный close должен быть идемпотентным.

---

# 47. Session expiration

Reaper инициирует server-side close по TTL/max lifetime.

Terminal state:

```text
expired
```

а не обычный `closed`, чтобы последующий client мог понять причину потери live state.

Фактический BrowserContext всё равно освобождается.

---

# 48. Cleanup failure

Если BrowserContext cleanup не подтвердился из-за worker failure:

- session может перейти в `lost`, если live owner исчез;
- cleanup event логируется;
- reconciliation не считает context гарантированно живым;
- server не держит session в вечном `closing`.

Точный bounded closing timeout configurable.

---

# 49. Page listing

Browser backend должен позволять получить текущий список pages:

```text
page_id
title
url
state
is_active
```

без необходимости делать полный snapshot каждой page.

Это read-only observation.

---

# 50. Tab selection

Изменение `active_page_id` является session state operation, но само по себе не обязательно взаимодействует с website.

Backend всё равно должен сериализовать его с другими session operations.

MCP может иметь удобную tabs operation вместо отдельных низкоуровневых calls.

---

# 51. Screenshot

Screenshot является browser-generated artifact.

Flow:

```text
Browser Worker
→ bounded screenshot bytes
→ Content ingest
→ image ContentObject
→ Browser result ContentRef
```

Screenshot не возвращается как огромная base64 строка common application result.

---

# 52. Screenshot semantics

Application options могут включать stable concepts вроде:

- full page vs viewport;
- target element_ref;
- image format/quality, если поддерживается policy.

Playwright-specific arbitrary screenshot options не должны автоматически протекать в common contract.

---

# 53. Rendered HTML / content extraction

Browser может получить rendered DOM/HTML как source для Content subsystem.

Если клиент явно хочет прочитать динамически rendered page как документ:

```text
Browser rendered representation
→ Content ingest/native HTML parsing
→ Content representations
```

Это composed application flow, но не hidden fallback из Retrieval.

MCP projection позже решит, требуется ли агенту отдельный `browser_extract` или snapshot + content operation достаточно.

---

# 54. Downloads

Playwright downloads являются временными browser runtime artifacts и удаляются при закрытии producing BrowserContext, поэтому нужный download должен быть перенесён в Content boundary до teardown session.

Flow:

```text
download event
→ bounded temporary handling
→ Content ingest
→ ContentObject
→ download ref в action/session result
```

Filename остаётся untrusted metadata.

---

# 55. Download capture

Browser runtime должен перехватывать download events централизованно, а не только когда конкретный tool заранее «знает», что download произойдёт.

Каждый download получает temporary internal identity/event.

Policy определяет:

- auto-persist в ContentObject;
- maximum size;
- rejection/cleanup;
- lifetime temporary file.

Базовое направление — сохранять download, инициированный explicit browser action, если он укладывается в Content/security limits.

---

# 56. Upload

Browser upload использует существующий client-owned ContentObject.

Flow:

```text
ContentRef
→ ownership/policy validation
→ bounded staging/stream to owning Browser Worker
→ file chooser/input action
```

Public API не принимает local path Control Plane/Browser Worker.

---

# 57. Upload filename

Browser-facing uploaded filename может использовать безопасную presentation metadata ContentObject, но physical source path не раскрывается.

Если website требует filename, он формируется из sanitized metadata/policy.

---

# 58. Console diagnostics

Browser Worker может собирать bounded console events.

Они считаются недоверенным page-generated content.

Нужна ring-buffer/cursor-like semantics, чтобы:

- не хранить console бесконечно;
- читать новые events после sequence/cursor;
- не дублировать giant history в каждом response.

Точный schema определяется Browser implementation design.

---

# 59. Network diagnostics

Аналогично должен существовать bounded network event log:

- request URL в redacted/authorized форме;
- method;
- resource type;
- response status;
- timing/basic failure;
- blocked-by-policy marker.

Не следует сохранять full request/response bodies/headers по умолчанию.

Sensitive headers redacted.

---

# 60. Diagnostic cursors

Console/network buffers могут использовать monotonic per-session/per-page event sequence.

Client запрашивает:

```text
after_sequence
limit
```

и получает bounded events + next cursor.

Это лучше, чем `get_all_console()` с неограниченным результатом.

---

# 61. JavaScript dialogs

Dialogs (`alert`, `confirm`, `prompt`, `beforeunload`) требуют отдельной детерминированной policy, потому что незакрытый dialog может блокировать browser action.

Baseline не должен молча принимать любые dialogs.

До implementation необходимо выбрать один из явных контрактов:

- default dismiss + captured dialog event;
- per-action dialog expectation/policy;
- explicit pending-dialog resource/action protocol.

Решение должно быть ADR/component decision до публикации Browser tools.

---

# 62. Permissions

BrowserContext permissions (geolocation, clipboard и т.п.) disabled/default-safe согласно profile.

Client не получает unrestricted permission grant API в базовом contract.

Если конкретная capability нужна, она добавляется allowlisted и scoped к session/origin.

---

# 63. Geolocation/device emulation

Не являются обязательными baseline capabilities.

Если REST/programmatic clients позднее требуют emulation:

- typed profile;
- explicit permission/policy;
- стабильные application fields;
- MCP не обязан раскрывать все низкоуровневые knobs.

---

# 64. Browser locale/timezone/viewport

Session create может использовать configured browser profile с predictable defaults.

Не следует на первом уровне передавать весь `browser.new_context(**kwargs)` public client-у.

Нужные stable settings добавляются как typed session profile capabilities.

---

# 65. Session profile

Вместо десятков Playwright launch/context параметров design должен поддерживать operator-defined/browser profiles.

Например:

```text
default
mobile_like (future)
specific locale profile (future)
```

Client выбирает только разрешённый profile ID, если capability нужна.

MCP чаще всего использует default profile.

---

# 66. Browser binary/version

Browser Worker должен использовать version-compatible Playwright package и browser binary.

Worker registration/health должна позволять диагностировать runtime version/profile revision.

Mixed incompatible worker versions не должны бесконтрольно обслуживать одну и ту же contract revision при rolling deployment.

Deployment design уточнит compatibility strategy.

---

# 67. Capacity

Browser subsystem должен иметь explicit capacity model.

Минимально:

- max concurrent sessions per worker;
- max pages per session;
- memory/CPU pressure awareness;
- global/principal session quota;
- action queue bound.

Если capacity исчерпана:

```text
create_session → rejected/failed capacity_unavailable
```

а не unbounded wait/queue в RAM.

---

# 68. Session placement

Control Plane выбирает worker через placement strategy.

Baseline критерии могут включать:

- worker ready/draining;
- available capacity;
- runtime/profile compatibility;
- coarse load.

LLM/client не выбирает worker.

Exact scheduling algorithm не является application contract и требует implementation design.

---

# 69. Worker registry

Для horizontal scaling требуется shared worker registry/heartbeat.

Registry должен позволять определить:

```text
worker identity/generation
ready/draining state
capacity
last heartbeat
browser runtime/profile revision
```

Redis является вероятным infrastructure backend, но final mechanism требует ADR.

---

# 70. Worker generation

Worker identity должна различать restart одного logical instance.

Например stale routing record на старую generation не должен считаться владельцем session после worker restart.

Это важно для корректного перехода BrowserSession в `lost` и возможного fencing.

---

# 71. Lease/fencing direction

BrowserSession owner mapping является кандидатом на lease + fencing token.

Требование:

- stale worker не должен иметь возможность успешно подтверждать новые mutating commands после утраты ownership;
- Control Plane должен отличать current owner generation.

Exact design будет зафиксирован ADR вместе с internal transport.

---

# 72. Control Plane ↔ Browser Worker transport requirements

Независимо от технологии protocol должен поддерживать:

1. targeted delivery owning worker;
2. action_id deduplication;
3. deadline propagation;
4. bounded payload size;
5. service authentication;
6. backpressure/capacity;
7. response correlation;
8. before/after-dispatch distinction настолько, насколько возможно;
9. worker generation validation;
10. cancellation signal;
11. graceful drain;
12. observability.

---

# 73. Internal transport candidates

Кандидаты:

```text
Direct internal HTTP/RPC
Redis Streams/mailbox
другой explicit routed RPC/message protocol
```

Обычная shared arq queue для BrowserSession actions не принимается как baseline, потому что не выражает session affinity/owning worker без дополнительного routing protocol.

ADR должен сравнить кандидатов до implementation Browser Worker protocol.

---

# 74. Service authentication

Browser Worker command endpoint/mailbox доступен только доверенному Control Plane/service principal.

Internal network location сама по себе не является authorization.

Worker также должен проверять session ownership/fencing context, а не доверять произвольному `session_id` из command payload.

---

# 75. Secrets/cookies

Cookies/local storage существуют внутри BrowserContext и не возвращаются в обычный MCP/REST result.

Export/import storage state не входит baseline.

Console/network diagnostics проходят redaction и не должны случайно раскрывать auth headers/cookies.

---

# 76. Current URL и page content как untrusted data

URL/title/text/snapshot nodes/console/network data являются web content/metadata, а не trusted instruction.

Structured server errors/hints сериализуются отдельно.

---

# 77. Browser hints

Допустимые trusted hints:

```text
snapshot_refresh_recommended
verify_browser_state
session_expiring
alternative_page_created
content_downloaded
```

Hints не должны содержать instructions, скопированные из страницы как trusted text.

---

# 78. Browser errors

Компонентные error codes должны различать как минимум классы:

```text
session_not_found
session_closed
session_expired
session_lost
page_not_found
page_closed
stale_target
target_not_found
target_ambiguous
action_not_allowed
actionability_timeout
navigation_timeout
navigation_policy_rejected
browser_capacity_unavailable
worker_unavailable
worker_lost
response_lost_after_dispatch
upload_content_not_found
download_too_large
```

Точная taxonomy будет зафиксирована implementation schemas, сохраняя общие application categories.

---

# 79. Action cancellation

Если action cancelled до dispatch → `cancelled`/safe no-effect.

Если cancellation приходит во время execution:

- worker пытается остановить Playwright task;
- если side effect мог произойти → outcome может быть `unknown`;
- нельзя объявлять `cancelled`, если фактический effect неизвестен.

Это особенно важно для click/press/submit-like actions.

---

# 80. Wait semantics

Browser backend должен поддерживать явное ожидание конкретного условия вместо reliance на arbitrary sleeps, где это возможно.

Кандидаты:

- element state/ref/text condition;
- URL/navigation condition;
- bounded duration;
- page load state.

`networkidle` и другие framework-specific states не должны без анализа становиться универсальным «страница готова» contract.

Exact wait model проектируется с MCP/REST UX.

---

# 81. No automatic waiting for semantic completion

Playwright auto-wait обеспечивает actionability конкретного элемента, но Web Access не должен считать это доказательством, что business workflow страницы завершён.

После click агент может самостоятельно snapshot/wait/check next state.

Browser не пытается угадать, что «страница уже достаточно загрузилась для задачи».

---

# 82. Snapshot after mutation

Backend не обязан автоматически генерировать полный snapshot после каждого action.

Action result возвращает lightweight observable metadata.

Agent/client запрашивает snapshot явно, если ему нужно новое состояние.

Это уменьшает latency/response size и сохраняет lazy semantics.

MCP facade позднее может выбрать ограниченный convenience projection только если выгода доказана.

---

# 83. Screenshot after mutation

Аналогично screenshot не создаётся автоматически после каждого action.

Screenshot — explicit operation/artifact.

---

# 84. Browser rendered content vs snapshot

Нужно различать:

```text
Semantic Snapshot
→ структура для interaction/reasoning

Rendered HTML
→ source representation для Content Native Parsing

Screenshot
→ visual artifact
```

Они не заменяют друг друга.

---

# 85. Frames

Iframes должны иметь стабильную representation в snapshot/action target model.

Client не должен работать с raw Playwright Frame object.

ElementRef должен содержать/разрешать нужный frame context server-side.

Точные frame handles могут не становиться отдельным public resource, если element refs достаточны.

---

# 86. Shadow DOM

Поддержка shadow DOM опирается на locator/snapshot implementation и не должна требовать отдельного agent tool, если semantic target model способен однозначно адресовать элементы.

Implementation tests обязаны проверить representative shadow DOM behavior.

---

# 87. Dialog/download/popup events и ordering

Browser action может генерировать несколько событий.

Worker должен привязать события, возникающие в action execution window, к `action_id` настолько, насколько это технически возможно.

Это позволяет result сообщить:

- popup created;
- download started/completed;
- dialog observed;
- navigation occurred.

Background events вне action также могут попадать в session event buffers.

---

# 88. Browser event stream

Browser runtime должен иметь внутреннюю ordered event model.

Не обязательно публиковать полный event stream в первой MCP версии, но internal schema помогает:

- diagnostics;
- action attribution;
- UI progress/REST monitoring;
- future streaming.

Events bounded/retained согласно policy и не заменяют authoritative session state.

---

# 89. Persistence

PostgreSQL хранит durable BrowserSession metadata/lifecycle и при необходимости action audit summary.

Redis/coordination хранит routing/worker/lease state.

Browser Worker memory хранит live state.

Не следует сохранять каждый DOM snapshot/action в PostgreSQL по умолчанию.

Large retained snapshot/screenshot использует ContentStore.

---

# 90. Action audit

Не каждое browser action обязано храниться как вечный audit record.

Security-sensitive/mutating actions могут требовать более durable audit, чем read-only snapshots.

Точный audit policy проектируется `observability.md`/future auth policy.

---

# 91. Observability

Browser telemetry должна включать:

- active sessions per worker;
- session create/close/expire/lost;
- action latency/type/outcome;
- action queue wait;
- stale target errors;
- unknown outcomes;
- browser/page crash;
- worker heartbeat/generation;
- capacity rejections;
- blocked network requests;
- downloads/uploads bytes;
- screenshot/content handoff;
- cleanup/reaper;
- worker drain/shutdown.

URL/full page text не используется как metric label.

---

# 92. Browser security acceptance

Implementation должна подтвердить:

- session storage isolation;
- private/internal egress block top-level и subresources;
- non-root/sandbox production worker;
- no Docker socket/host filesystem;
- cross-owner session access denied;
- Content upload ownership validation;
- download path isolation;
- advanced evaluate permission denied по умолчанию;
- bounded tabs/session/actions/downloads;
- session cleanup after client disappearance;
- worker death не даёт stale session использовать новый unrelated context.

---

# 93. Unit/contract tests

BrowserApplicationService tests с fake worker должны проверять:

1. create → ready;
2. create failure → failed/cleanup;
3. explicit close idempotency;
4. expired/lost access;
5. session-level serialization;
6. page identity/popups;
7. stale generation/ref rejection;
8. action_id duplicate delivery semantics;
9. unknown outcome propagation;
10. no automatic retry mutating action;
11. Content upload ownership;
12. download ContentRef result;
13. capacity rejection;
14. owner isolation;
15. reaper/action race.

---

# 94. Browser Worker integration tests

С реальным Playwright/Chromium и controlled test sites:

- context isolation;
- cookies/storage separation;
- navigation;
- SPA dynamic update;
- accessibility/semantic snapshot;
- element refs;
- stale target;
- click actionability;
- form fill;
- popup;
- download;
- upload;
- dialog;
- iframes;
- shadow DOM;
- console/network buffers;
- blocked private subresource;
- page crash/browser crash;
- context close download cleanup;
- worker restart/session loss.

---

# 95. Concurrency/race tests

Обязательные race scenarios:

1. два mutating actions одной session одновременно;
2. close vs action;
3. reaper expiration vs action;
4. worker drain vs create_session;
5. worker death после dispatch до response;
6. duplicate internal command;
7. stale owner generation;
8. popup created while close starts;
9. download finishing during session close;
10. ContentStore failure during download finalization.

---

# 96. REST projection expectations

REST позднее должен иметь богатый Browser API:

- session create/get/close;
- pages/tabs;
- navigation;
- snapshot;
- typed interactions;
- screenshots;
- uploads/downloads/content refs;
- console/network diagnostics with cursor;
- lifecycle/capacity metadata;
- authorized advanced operations отдельным capability surface.

REST не является raw Playwright RPC API.

---

# 97. MCP projection expectations

MCP должен быть значительно компактнее REST.

Ожидаемые принципы:

- explicit session lifecycle либо удобный минимальный create/open pattern без скрытой глобальной session;
- semantic snapshot как основной способ увидеть страницу;
- element_ref из snapshot для actions;
- отдельные semantic operations, а не один giant `browser_action` union;
- fill form может принимать несколько fields;
- no `*_many` для sequential stateful actions;
- no unrestricted CSS/XPath/JS complexity для обычного LLM path;
- Russian descriptions;
- tool descriptions явно различают snapshot/screenshot/rendered content;
- structured `unknown`/stale-target errors;
- ContentRefs для downloads/screenshots.

Точный tool catalog определяется только после REST/backend design review.

---

# 98. Acceptance criteria Browser subsystem

Browser считается архитектурно реализованным, если:

1. BrowserSession имеет независимый от MCP/HTTP connection lifecycle.
2. Session создаётся ephemeral и возвращает initial page_id.
3. Live Playwright state существует только в Browser Worker.
4. Любой Control Plane replica может маршрутизировать action owning worker.
5. Одна session имеет одного active owner generation.
6. Все operations одной session упорядочены.
7. Snapshot выдаёт opaque snapshot-scoped element refs.
8. Stale/ambiguous target rejected без heuristic retargeting.
9. Playwright actionability используется для interaction.
10. Mutating action не получает blind automatic retry после dispatch.
11. Response loss может вернуть `unknown`.
12. Worker death переводит session в `lost`.
13. TTL/max lifetime/reaper освобождают abandoned sessions.
14. Close идемпотентен и сохраняет terminal metadata.
15. Popup/new page получает page_id и не теряется.
16. Screenshot/download становятся ContentObjects.
17. Upload использует owner-validated ContentObject, а не local path.
18. Network/console diagnostics bounded/cursor-based.
19. Browser egress блокирует private/internal destinations defense-in-depth.
20. Advanced arbitrary evaluate не входит обычный capability surface.
21. Session/profile/capacity limits configurable, без hardcoded magic numbers.
22. Controlled real-browser test suite покрывает lifecycle/actions/races/security.

---

# 99. Open decisions requiring ADR/design before implementation

1. **Control Plane ↔ Browser Worker transport.** Direct internal HTTP/RPC vs Redis Streams/mailbox/другой routed protocol.
2. **Worker registry/lease/fencing.** Точный Redis/PostgreSQL split и stale-owner protection.
3. **ElementRef implementation.** Snapshot mapping/locator recipe и invalidation strategy.
4. **Dialog protocol.** Default dismiss vs expected dialog vs pending-dialog flow.
5. **Exact snapshot schema.** Semantic/accessibility representation, frames, truncation/chunking.
6. **Browser process pool model.** One Chromium per worker vs bounded pool.
7. **Session/profile options.** Какие stable settings разрешены first-class.
8. **Exact network interception strategy** для subresources/WebSockets/service workers.
9. **Worker DB access.** Только Control Plane coordination или ограниченный direct repository access.
10. **Action audit durability.** Какие actions обязаны сохраняться.
11. **Browser event buffering/streaming.** Ring buffers vs Redis/event layer для future UI.
12. **Wait condition model.** Stable generic conditions без Playwright-private leakage.
13. **Rendered-content operation.** Отдельная Browser application operation или composition Browser→Content без отдельного public concept.
14. **MCP session UX.** Насколько lifecycle explicit для LLM и можно ли объединить create+navigate на facade уровне, не меняя backend semantics.

Эти решения не меняют принятые resource/lifecycle/worker boundaries и должны быть закрыты до соответствующих implementation patches.

---

# 100. Внешние implementation ориентиры

При реализации необходимо сверяться с актуальной официальной документацией Playwright.

Принятый design опирается на свойства Playwright, согласно которым BrowserContext предоставляет независимое session state, locator actions используют auto-wait/actionability checks, а browser downloads являются временными artifacts контекста и должны быть сохранены до его закрытия.

Эти свойства используются как implementation foundation, но public Web Access contracts остаются собственными и versioned независимо от private Playwright API details.
