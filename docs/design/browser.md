# Browser subsystem design

## Статус документа

Этот документ является каноническим владельцем **семантики Browser subsystem**: BrowserSession lifecycle, page identity, browser actions, ordering, result/failure semantics, Browser ↔ Content integration и общих runtime invariants.

Низкоуровневые спорные решения вынесены в ADR и не дублируются здесь подробно.

Обязательные Browser ADR:

- `decisions/ADR-0001-browser-worker-transport.md`;
- `decisions/ADR-0009-browser-worker-registry-and-lease.md`;
- `decisions/ADR-0010-browser-snapshot-element-refs.md`;
- `decisions/ADR-0011-browser-dialog-policy.md`;
- `decisions/ADR-0012-browser-process-per-session.md`;
- `decisions/ADR-0013-browser-session-subprocess.md`;
- `decisions/ADR-0014-browser-egress-proxy.md`.

При конфликте старой process-management формулировки ADR-0012 с ADR-0013 приоритет имеет ADR-0013.

---

# 1. Purpose

Browser предоставляет управляемую stateful browser capability для сценариев, где:

- обычного Search недостаточно;
- Retrieval получил только статический/неполный ресурс;
- нужен JavaScript-rendered state;
- требуется навигация по web application;
- требуется взаимодействие с form/control/page state;
- нужны screenshots/downloads/rendered content;
- вызывающий клиент сознательно выбрал browser workflow.

Browser **никогда не запускается автоматически** как скрытый fallback Retrieval/Content.

---

# 2. Responsibilities

Browser отвечает за:

- создание и завершение `BrowserSession`;
- live state одной browser session;
- page/tab/popup lifecycle;
- navigation;
- structured semantic snapshots;
- opaque snapshot-scoped element references;
- typed browser interactions;
- dialogs;
- downloads/uploads/screenshots/rendered content;
- bounded browser diagnostics/events;
- ownership и authorization;
- worker routing;
- session-level serialization;
- action identity/dedup/status recovery;
- deadlines/cancellation;
- `unknown` outcome для недоказуемого результата mutating action;
- TTL/max lifetime/reaper;
- worker loss/self-fencing;
- network egress isolation;
- observability.

---

# 3. Non-goals

Browser не должен:

- выполнять agent reasoning;
- самостоятельно выбирать сайт из Search results;
- автоматически открываться после `web_fetch`;
- обходить CAPTCHA/anti-bot как гарантированную capability;
- предоставлять stealth/fingerprint evasion baseline;
- предоставлять unrestricted JavaScript evaluation обычному principal;
- предоставлять shell/Python execution;
- хранить persistent user browser profile baseline;
- автоматически подтверждать destructive dialogs;
- автоматически повторять mutating action после неизвестного outcome;
- превращаться в remote desktop;
- позволять client-defined Chromium launch arguments/proxy/network policy.

---

# 4. Browser engine baseline

Baseline:

```text
Playwright Python
+
Chromium
```

Playwright является infrastructure implementation.

Public application/REST/MCP contracts не содержат:

- Playwright objects;
- CSS/XPath selectors baseline;
- BrowserContext IDs;
- Chromium PID;
- CDP target IDs;
- launch args.

---

# 5. Canonical runtime model

Актуальная process model:

```text
Control Plane
    │
    │ direct internal HTTP/RPC
    ▼
Browser Worker supervisor
    │
    ├── BrowserSession subprocess A
    │       └── Playwright
    │           └── Chromium A
    │               └── non-persistent BrowserContext A
    │                   └── Pages
    │
    └── BrowserSession subprocess B
            └── Playwright
                └── Chromium B
                    └── non-persistent BrowserContext B
                        └── Pages
```

Инвариант:

```text
1 BrowserSession
→ 1 owning Browser Worker generation
→ 1 session subprocess
→ 1 Chromium process
→ 1 non-persistent BrowserContext
→ N Pages
```

Browser Worker является supervisor, а не owner Playwright object graph.

Фактические `Browser`, `BrowserContext`, `Page`, `Locator`, `ElementHandle` живут только внутри соответствующего session subprocess.

---

# 6. Почему BrowserSession — отдельный subprocess

Это даёт enforceable lifecycle boundary:

- зависший Playwright event loop одной session не блокирует остальные;
- session можно bounded terminate/kill;
- весь Chromium child tree уничтожается вместе с session runtime;
- snapshot handles не пересекают address space sessions;
- one-session memory leak не требует restart всего worker;
- hard cleanup не зависит от private Playwright PID API.

Subprocess не считается полной security sandbox. Network/container/browser sandbox остаются обязательными.

---

# 7. BrowserSession resource

`BrowserSession` — owner-scoped live Resource.

Минимальные durable coordinates:

```text
browser_session_id
owner_principal_id
state
revision
worker_id
worker_generation
created_at
ready_at
last_activity_at
idle_expires_at
max_expires_at
terminal_at
failure/loss metadata
```

Client не знает internal worker endpoint или process identity.

---

# 8. BrowserSession lifecycle

Canonical states:

```text
creating
→ ready
→ closing
→ closed
```

Terminal alternatives:

```text
creating → failed
ready/closing → lost
ready → expired
```

Terminal resource не resurrected автоматически.

Worker/browser restart не восстанавливает старую BrowserSession.

---

# 9. Session creation

Application flow:

```text
BrowserApplicationService.create_session(...)
```

должен:

1. проверить authenticated principal/scope/quota;
2. создать durable `creating` resource;
3. выбрать compatible ready Browser Worker;
4. записать intended worker identity/generation;
5. вызвать worker create через ADR-0001 transport;
6. worker зарезервирует capacity slot и spawn session subprocess;
7. session subprocess стартует Playwright/Chromium/BrowserContext;
8. создаётся initial blank Page;
9. worker возвращает page identity;
10. Control Plane CAS переводит session в `ready`;
11. возвращается `browser_session_id` + `page_id`.

Crash windows reconciled согласно ADR-0009.

---

# 10. Initial page

Каждая успешная session имеет одну initial blank page.

```text
create session
→ browser_session_id + initial page_id
→ explicit navigate
```

Navigation не скрывает создание session/page.

---

# 11. BrowserPage

Каждая page/tab/popup получает opaque `page_id`, scoped к BrowserSession.

`page_id`:

- server-generated;
- не является Playwright internal ID;
- недействителен вне session;
- становится invalid при page/session loss/close;
- создаётся и для popup/new tab.

Pages baseline являются live child objects session и не обязаны иметь отдельные durable PostgreSQL rows.

---

# 12. Worker ownership и routing

PostgreSQL хранит authoritative:

```text
worker_id
worker_generation
```

Redis хранит ephemeral worker registry/route cache.

Browser Worker heartbeat/lease/self-fencing определены ADR-0009.

Control Plane перед action:

1. проверяет owner/session state;
2. получает authoritative worker generation;
3. разрешает current internal endpoint через registry;
4. проверяет generation;
5. вызывает owning worker напрямую.

Никакой live session failover на другой worker baseline нет.

---

# 13. Session serialization

Все state-sensitive Browser operations одной BrowserSession идут через один serial lane.

```text
Session A: action1 → snapshot2 → action3
Session B: может выполняться параллельно
```

Даже pages одной BrowserContext baseline сериализуются на session level.

Это упрощает:

- cookies/storage ordering;
- popup/dialog events;
- snapshot/action races;
- cancellation;
- status recovery;
- unknown outcome classification.

---

# 14. Action identity

Каждый internal Browser command получает stable `action_id`, связанный с application `operation_id`.

`action_id` используется для:

- duplicate delivery detection;
- status recovery;
- tracing;
- avoiding blind retries;
- worker action ledger.

External MCP caller не обязан генерировать `action_id`.

REST idempotency policy может использовать отдельный client-facing mechanism.

---

# 15. Action status recovery

При потере Control Plane ↔ worker response нельзя сразу повторять действие.

Canonical flow:

```text
lost response
→ query same action_id
→ terminal result known? return it
→ still running? continue/status
→ no evidence after possible side effect? outcome=unknown
```

Особенно важно для:

- click;
- submit-like press;
- navigation с side effects;
- dialog accept;
- form interactions.

`unknown` не превращается в automatic retry.

---

# 16. Session subprocess action protocol

Worker supervisor передаёт action соответствующему session subprocess через локальный bounded framed protocol из ADR-0013.

Session subprocess владеет:

- Playwright action execution;
- snapshot/ref maps;
- dialogs;
- page/browser events;
- temporary artifacts.

Supervisor владеет:

- network-facing internal RPC;
- action correlation/ledger;
- process lifecycle;
- capacity;
- routing к child;
- artifact forwarding.

---

# 17. Session revision и page generation

`BrowserSession.revision` — server-controlled monotonic coordinate accepted operations/state transitions.

Она **не является DOM revision**.

`page_generation` меняется при document replacement/navigation boundary, после которой старые refs заведомо invalid.

SPA DOM mutation может происходить без generation change; поэтому exact ElementRef validation остаётся обязательной.

---

# 18. Semantic snapshot

Основным представлением страницы для agent/programmatic interaction является structured semantic snapshot.

Snapshot должен включать bounded:

- `snapshot_id`;
- `page_id`;
- `page_generation`;
- session revision;
- URL/title;
- meaningful semantic/accessibility structure;
- actionable element inventory;
- states/labels;
- truncation/full-content metadata.

Screenshot является дополнительным visual artifact, но не основным targeting mechanism.

---

# 19. ElementRef

Actionable element получает opaque `element_ref`.

Он scoped к:

```text
BrowserSession
+ Page
+ Snapshot
+ Page generation
```

Core client не получает CSS/XPath.

Exact strategy определена ADR-0010:

- private locator recipe;
- snapshot-time `ElementHandle` identity anchor;
- re-resolve through Locator;
- exact DOM identity verification;
- Locator actionability;
- no heuristic retargeting.

Если original node исчез/заменён, возвращается `stale_target`, даже если существует визуально похожий элемент.

---

# 20. Snapshot lifetime

Refs являются ephemeral capability references.

Initial design limits из ADR-0010:

```text
max snapshots/page = 3
snapshot/ref TTL = 5 minutes
max refs/snapshot = 300
```

Exact operational ceilings version-configurable.

Eviction обязан dispose ElementHandles внутри session subprocess.

Historical stored snapshot ContentObject может пережить ref lifetime; такие refs больше не гарантированно actionable.

---

# 21. Snapshot size

Snapshot generation всегда bounded.

Если facade inline budget превышен:

```text
preview/bounded inline snapshot
+
full structured representation → ContentObject
```

Agent может читать full ContentObject отдельно.

Нельзя отправлять unbounded DOM/accessibility tree через MCP result.

---

# 22. Browser interactions

Application layer должен иметь typed actions, например semantic classes:

```text
navigate
click
fill form
select option
press key
check/uncheck
type text
hover/wait where justified
page close/switch
```

Exact REST/MCP surface описывают соответствующие facade docs/version specs.

Core Browser interaction не принимает arbitrary Playwright code.

---

# 23. Actionability

Locator-based actions используют Playwright actionability/auto-wait semantics.

Operation deadline ограничивает auto-wait.

`force`/отключение safety checks не является обычной MCP capability.

Если advanced administrative REST capability когда-либо понадобится, она требует отдельного permission/security design.

---

# 24. Dialogs

Диалоги определены ADR-0011.

Default:

```text
unexpected dialog
→ dismiss
→ report bounded event/warning
```

Caller может **заранее для конкретного action** задать explicit accept policy.

Dialog не становится долгоживущим remote resource baseline.

Page dialog text считается untrusted web content.

---

# 25. Browser events

Browser session собирает bounded diagnostic events, например:

- popup/page created/closed;
- dialog;
- download;
- selected console messages;
- selected request/response/network failures;
- browser disconnect;
- blocked security request.

Event stream не является unbounded durable log.

Overflow обозначается gap/drop metadata.

---

# 26. Rendered content

Если клиенту нужен document-like контент после JS rendering:

```text
Browser page
→ rendered HTML/DOM representation
→ temporary artifact
→ Content ingest
→ ContentObject
```

После этого Content Native Parsing может работать с этим ContentObject отдельно.

Browser не вызывает L2/OCR автоматически.

---

# 27. Screenshots

Screenshot является Browser-produced binary artifact.

Flow:

```text
session subprocess
→ temporary screenshot
→ supervisor artifact handoff
→ Control Plane Content ingest
→ ContentObject
```

Large binary не передаётся base64 в normal MCP/REST JSON result.

---

# 28. Downloads

Browser download сначала существует только во временном session storage.

До session cleanup нужный download должен быть передан через Content boundary.

После успешной Content finalization:

- permanent payload принадлежит ContentStore;
- session temp copy можно удалить;
- закрытие BrowserSession не удаляет ContentObject.

---

# 29. Uploads

Browser upload не принимает arbitrary host filesystem path.

Input:

```text
owner-authorized ContentRef
→ bounded internal transfer/materialization
→ Playwright file input
```

Session subprocess не получает прямой ContentStore credential/root.

---

# 30. Content handoff security

Browser session subprocess не имеет credentials:

- PostgreSQL;
- Redis;
- SearXNG/Yandex;
- external client auth registry;
- ContentStore.

Artifact handoff идёт через supervisor/Control Plane bounded protocol.

Local path остаётся internal и должен быть проверен относительно generated session temp root.

---

# 31. Session lifetime

Baseline version profile задаёт:

- idle TTL;
- max lifetime;
- creation timeout;
- close grace;
- max pages;
- max queued actions;
- temp/artifact limits.

Client не создаёт infinite BrowserSession.

Серверный TTL/reaper является обязательным даже если Agent Runtime отправляет best-effort cleanup.

---

# 32. Explicit close

Close должен быть idempotent на application level.

Canonical runtime sequence согласно ADR-0013:

1. `closing`, reject new actions;
2. cooperative close child;
3. dispose page/snapshot state;
4. close BrowserContext/Chromium/Playwright;
5. child exits;
6. supervisor reaps process;
7. if grace exceeded → terminate/kill process tree;
8. temp cleanup;
9. durable terminal state.

Capacity slot освобождается только после process reap/cleanup, а не только после DB state change.

---

# 33. Worker loss

Worker generation loss определяется ADR-0009.

После final loss grace:

```text
all live BrowserSessions of generation
→ lost
```

Новая worker generation не наследует session state.

Late stale worker не resurrects lost resources.

---

# 34. Browser/session process crash

Session subprocess/Chromium crash затрагивает только эту BrowserSession.

- session → `lost`/`failed` according stage/evidence;
- refs/pages invalid;
- in-flight mutating action → `unknown`, если side effect нельзя исключить;
- supervisor reaps child;
- другие sessions worker-а продолжают работу.

Worker process/container crash уничтожает все child sessions; durable loss оформляется через worker lease protocol.

---

# 35. Worker drain

Rolling drain:

1. worker перестаёт принимать новые sessions;
2. advertises `draining`;
3. existing session subprocesses получают bounded close;
4. remaining children forced terminate после deadline;
5. worker подтверждает zero live sessions;
6. runtime завершается.

Нельзя убивать worker сразу, если graceful drain возможен.

---

# 36. Network security

Browser egress определён ADR-0014.

Reference topology:

```text
Control Plane ↔ Browser Worker
                  │
                  │ explicit Chromium proxy
                  ▼
            Browser Egress Gateway
                  │
                  ▼
            Public Internet
```

Browser Worker не имеет direct Internet route baseline.

Gateway запрещает private/internal/special destinations.

Chromium/session process не получает internal service credentials.

Application-level URL interception является defense in depth, но не единственным SSRF barrier.

---

# 37. Top-level navigation policy

Explicit client navigation baseline разрешает только:

```text
http
https
```

`file:`, `javascript:`, `data:`, `chrome:` и другие dangerous/non-web schemes rejected.

Internal server-created `about:blank` initial page не является client-accessible arbitrary scheme capability.

---

# 38. Browser capacity

Browser — expensive capability.

Initial version default:

```text
max_sessions_per_worker = 4
```

Окончательный production capacity определяется load tests.

Architecture не предполагает unbounded spawn.

Admission выполняется до host/container exhaustion; worker является final local authority slot availability.

---

# 39. REST projection

REST предоставляет богатый typed Browser API для:

- session lifecycle;
- pages;
- navigate;
- snapshot;
- typed actions;
- events;
- screenshots/rendered content/downloads/uploads;
- status/diagnostics в разрешённом scope.

REST не предоставляет raw Playwright object model.

Канонический facade design: `rest-api.md`.

---

# 40. MCP projection

MCP предоставляет компактные LLM-oriented Browser tools.

Основные требования:

- русские descriptions;
- no CSS/XPath baseline;
- element refs from snapshot;
- explicit stateful handles;
- one logical mutating action per call;
- structured errors/hints;
- accurate annotations/retry semantics;
- no hidden navigation/browser fallback.

Канонический facade design: `mcp.md`.

---

# 41. Hints

Structured hints допустимы, например:

```text
stale_target
→ hint: получить новый snapshot

session_expiring
→ hint: завершить необходимые действия/создать новую session
```

Hint не выполняет action автоматически.

Page-supplied text не становится trusted hint.

---

# 42. Failure model

Минимальные Browser-specific categories:

```text
session_not_found
session_not_ready
session_expired
session_lost
worker_unavailable
worker_generation_mismatch
worker_capacity_unavailable
page_not_found
page_closed
snapshot_expired
stale_target
target_not_found
target_ambiguous
action_timeout
action_rejected
browser_crashed
browser_dialog_limit_exceeded
browser_egress_denied
artifact_handoff_failed
unknown_outcome
```

Они маппятся в общую `OperationError`/`OperationOutcome` модель.

---

# 43. Retry semantics

Read-only Browser operations могут иметь controlled retry только если повтор не меняет browser state опасным образом.

Mutating interactions baseline:

```text
never blind automatic retry after uncertain dispatch
```

Повтор того же internal `action_id` используется только для result/status recovery, а не для нового исполнения.

---

# 44. Cancellation

Cancellation зависит от стадии:

- до dispatch → safe cancellation;
- queued in session lane → remove/reject if not started;
- running read-only → abort where Playwright/runtime allows;
- running mutating → cancellation не доказывает absence side effect;
- process kill as cancellation fallback может привести к `unknown` + session loss.

Cancellation semantics должны быть явными в result.

---

# 45. Observability

Browser telemetry должна позволять видеть:

- sessions active/creating/closing/lost;
- worker capacity;
- session subprocess count;
- Chromium/process failures;
- action latency/outcomes;
- unknown outcomes;
- snapshot generation/size/truncation;
- stale refs;
- dialogs;
- downloads/screenshots/artifacts;
- egress denials;
- forced kills;
- cleanup/drain latency;
- process/zombie leak counters.

Raw sensitive page content не используется как metric labels.

---

# 46. Acceptance contract

Browser subsystem считается корректным только если доказаны как минимум:

1. owner isolation;
2. one BrowserSession → one session subprocess → one Chromium;
3. separate sessions не делят cookies/storage/process state;
4. worker routing generation-safe;
5. worker self-fencing работает;
6. session serialization/race tests проходят;
7. action status recovery не дублирует click/submit;
8. uncertain mutating result становится `unknown`;
9. snapshot refs exact и stale-safe;
10. navigation invalidates old refs;
11. dialogs bounded/default safe;
12. screenshot/download/rendered content проходят Content boundary;
13. upload требует owner-authorized ContentRef;
14. session TTL/reaper не зависит от MCP connection;
15. forced close действительно kills child tree;
16. repeated create/close soak не оставляет Python/Chromium zombies;
17. worker crash/drain не оставляет orphan processes;
18. Browser egress не достигает private/internal networks;
19. proxy outage не включает direct-network fallback;
20. MCP/REST actual schema tests соответствуют design.

---

# 47. Open evolution points

Не являются blockers baseline:

- persistent authenticated browser profiles;
- shared Chromium/pool optimization;
- advanced locator/evaluate capability;
- BrowserSession migration;
- durable browser workflows;
- visual/VLM page understanding;
- WebRTC-heavy unrestricted profile;
- richer browser tracing/HAR.

Любой из этих пунктов требует отдельного design/ADR и не должен незаметно расширять baseline.
