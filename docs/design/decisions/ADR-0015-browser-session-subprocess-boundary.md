# ADR-0015 — BrowserSession выполняется в отдельном session subprocess

**Статус:** accepted

**Supersedes:** process-management часть [ADR-0012](ADR-0012-browser-process-per-session.md). Сам инвариант «отдельный Chromium process на BrowserSession» сохраняется и усиливается.

## 1. Контекст

ADR-0012 правильно зафиксировал, что одна `BrowserSession` не должна делить один Chromium process с другими sessions baseline. Однако первоначальная формулировка предполагала, что один Browser Worker process непосредственно владеет несколькими объектами Playwright и запускает отдельный Chromium для каждой session.

Для production lifecycle этого недостаточно.

Требуется гарантировать, что зависшую BrowserSession можно:

- остановить независимо от других sessions;
- сначала завершить graceful;
- затем принудительно terminate/kill;
- уничтожить весь принадлежащий session browser process tree;
- очистить session temp state;
- не зависеть от private/non-stable process handles Playwright;
- не убить весь Browser Worker из-за одной зависшей browser runtime.

Публичный Python Playwright API гарантирует lifecycle `Browser`, но архитектура Web Access не должна строить OS-level hard-kill отдельного Chromium tree на private internals SDK.

## 2. Решение

Browser Worker становится **supervisor runtime**.

Каждая BrowserSession выполняется в отдельном короткоживущем Python subprocess:

```text
Browser Worker supervisor
├── Session subprocess A
│   └── Playwright
│       └── Chromium process A
│           └── BrowserContext A
│               └── Pages A
├── Session subprocess B
│   └── Playwright
│       └── Chromium process B
│           └── BrowserContext B
│               └── Pages B
└── ...
```

Инвариант:

```text
1 BrowserSession
→ 1 session subprocess
→ 1 Playwright runtime ownership boundary
→ 1 Chromium process
→ 1 non-persistent BrowserContext
→ N Pages
```

`Browser Worker` не хранит Playwright `Page`/`BrowserContext`/`ElementHandle` объектов чужих session subprocess в собственном address space.

## 3. Почему subprocess является lifecycle boundary

Session subprocess даёт Web Access собственный OS process handle, которым владеет supervisor.

Это позволяет:

1. отправить cooperative close/cancel;
2. дождаться bounded grace period;
3. вызвать terminate;
4. после второго bounded периода вызвать hard kill;
5. дождаться reap child process;
6. очистить session temp directory;
7. независимо перевести BrowserSession в terminal state.

Для этого не требуется получать PID Chromium через private Playwright implementation.

После уничтожения session subprocess OS/container process-tree policy должна уничтожать его Chromium descendants.

## 4. Ответственность Browser Worker supervisor

Supervisor отвечает за:

- worker registration/heartbeat/lease;
- capacity accounting;
- placement уже назначенной worker-у session;
- запуск session subprocess;
- выдачу subprocess internal endpoint/channel identity;
- routing action к правильному subprocess;
- bounded action request/response;
- subprocess health monitoring;
- session process termination/reaping;
- worker drain;
- coarse lifecycle/event forwarding Control Plane;
- orphan/stale temp cleanup при startup.

Supervisor **не исполняет Playwright actions самостоятельно**.

## 5. Ответственность session subprocess

Session subprocess является единственным owner live browser state конкретной BrowserSession:

```text
Playwright runtime
Browser
BrowserContext
Pages
snapshot maps
ElementHandle identity anchors
locator recipes
action serialization queue
action ledger
dialog state
browser events
temporary downloads/screenshots before handoff
```

Все snapshot-scoped `ElementHandle` из ADR-0010 остаются внутри этого process.

## 6. Внутренний supervisor ↔ session protocol

Это **не публичный REST/MCP protocol**.

Минимальные команды:

```text
initialize session
execute action
get action status/result
close session
health/ping
```

Каждая command включает как минимум:

```text
session_id
action_id / command_id
session revision/generation coordinates where applicable
deadline
payload
```

Exact IPC transport между supervisor и session subprocess является implementation detail v0.4, но должен быть:

- local-only;
- bounded;
- request/response oriented;
- cancellation-aware настолько, насколько операция допускает cancellation;
- не доступен из внешней container network.

Предпочтение implementation: local Unix domain socket на Linux production image либо эквивалентный authenticated local IPC. Если cross-platform development требует TCP loopback fallback, он должен быть random-port + unguessable per-session credential и не слушать external interfaces.

## 7. Action status recovery

ADR-0001 определяет direct Control Plane → Browser Worker RPC и повторное получение результата по `action_id`.

При session subprocess architecture:

```text
Control Plane
→ Browser Worker supervisor
→ Session subprocess action ledger
```

Supervisor не повторяет mutating action только из-за потерянного downstream response.

Если ответ subprocess потерян:

1. supervisor запрашивает status того же `action_id`;
2. если terminal result известен — возвращает его;
3. если action всё ещё выполняется — использует тот же execution;
4. если subprocess погиб после потенциального side effect и доказать outcome невозможно — возвращается `unknown`.

## 8. Session subprocess crash

Если session subprocess завершился неожиданно:

- supervisor reaps process;
- Chromium descendants должны быть уничтожены process-tree/container semantics;
- BrowserSession становится `lost` либо `failed` в зависимости от стадии/evidence;
- все pages/snapshots/refs становятся invalid;
- action in-flight получает `unknown`, если side effect нельзя исключить;
- другие sessions worker-а продолжают работать.

Session не восстанавливается автоматически на новом subprocess.

## 9. Chromium crash при живом subprocess

Если Playwright сообщает browser disconnect/crash:

- subprocess прекращает принимать новые actions;
- формирует terminal session failure/loss report;
- пытается bounded cleanup;
- завершается;
- supervisor завершает/reaps его при необходимости.

Новый Chromium для той же BrowserSession автоматически не запускается.

## 10. Session close

Canonical close:

```text
Control Plane cleanup/explicit close
→ supervisor marks session closing
→ session subprocess cooperative close
→ reject new actions
→ resolve/cancel current action according semantics
→ finalize/abandon temporary artifacts
→ dispose snapshots/handles
→ close pages/context/browser
→ subprocess exits
→ supervisor reaps child
→ terminal state persisted
```

Если cooperative close превышает `closing_grace`:

```text
terminate subprocess
→ second bounded grace
→ hard kill if still alive
→ reap
```

Cleanup result отдельно фиксирует, был ли close graceful или forced.

## 11. Process tree

Production Linux container должен использовать process supervision/reaping semantics, которые гарантируют отсутствие orphan child processes.

Requirements:

- Browser Worker запускается с init/subreaper support (`tini`, Docker `init: true` или эквивалент);
- session subprocess создаётся как отдельная process group/session там, где это необходимо для bounded tree termination;
- worker shutdown уничтожает все session process groups;
- container termination не оставляет Chromium descendants на host;
- tests проверяют реальные process trees.

Implementation не полагается на Python garbage collection.

## 12. Temp directory ownership

Каждый session subprocess получает отдельный generated temp root:

```text
<browser-temp-root>/<worker-generation>/<session-id>/
```

Путь:

- создаёт supervisor;
- не задаёт client;
- доступен только worker/session runtime;
- не является ContentStore;
- очищается после process termination;
- stale directories удаляются startup/reaper policy.

## 13. Content handoff

Session subprocess не получает прямые credentials PostgreSQL/Redis/ContentStore.

Для screenshot/download/rendered HTML:

```text
Session subprocess
→ bounded temporary artifact
→ supervisor/control-plane handoff protocol
→ Content application ingest/finalization
→ ContentObject
→ acknowledgement
→ temp artifact cleanup
```

Exact artifact transfer может использовать bounded local stream/internal RPC; он не должен требовать S3/DB credentials внутри untrusted browser session runtime.

Большой artifact не кодируется целиком в JSON/base64.

## 14. Network boundary

ADR-0014 остаётся обязательным.

Session subprocess/Chromium находится в Browser Worker container/network namespace и:

- не имеет direct public Internet route;
- использует configured browser egress proxy;
- не получает internal service credentials;
- не получает DB/Redis credentials;
- не выбирает proxy из client input.

Local IPC supervisor-а не должен быть доступен page JavaScript через browser network stack.

## 15. Resource limits

Supervisor применяет per-session process limits насколько позволяет deployment:

- memory/cgroup/container-worker ceiling;
- open files;
- temp bytes;
- pages;
- action queue;
- lifetime.

Baseline может не создавать отдельный cgroup на каждый subprocess в Docker Compose, но application capacity + container limits + process-per-session metrics обязательны.

Production orchestrator может усиливать isolation отдельными worker pods/process policies без изменения application contract.

## 16. Playwright startup

В отличие от superseded части ADR-0012, supervisor не держит один общий `async_playwright()` runtime для всех sessions.

Каждый session subprocess самостоятельно:

```text
start Playwright
→ launch Chromium
→ create non-persistent BrowserContext
→ create initial blank Page
```

Это увеличивает startup cost, но делает lifecycle ownership однозначным.

Browser является намеренно дорогой capability; latency измеряется v0.4 load baseline.

## 17. Capacity baseline

Сохраняется первоначальное направление:

```text
max_sessions_per_worker = 4
```

как configurable initial default, а не universal constant.

Capacity slot считается занятым с момента spawn session subprocess до его полного reap/cleanup.

Нельзя освободить slot только потому, что BrowserSession уже помечена `closing` в PostgreSQL.

## 18. Worker drain

Drain:

1. worker перестаёт принимать новые sessions;
2. сообщает `draining` Control Plane;
3. existing session subprocesses получают bounded close;
4. после drain deadline remaining subprocesses terminate/kill;
5. supervisor подтверждает нулевое число child sessions;
6. worker может завершаться.

## 19. Security benefits и ограничения

Плюсы subprocess boundary:

- зависший Playwright event loop одной session не блокирует остальные;
- hard-kill не зависит от private Chromium PID API;
- Python-side parser/browser memory leak scoped к session;
- snapshot handles не пересекают session address space;
- crash containment сильнее.

Но subprocess **не является security sandbox сам по себе**.

Обязательны всё равно:

- Chromium sandbox;
- non-root worker;
- egress proxy/network isolation;
- no internal credentials;
- seccomp/capability restrictions deployment;
- resource limits.

## 20. Local development

Архитектурное поведение не меняется локально: session также запускается subprocess.

На Windows development local IPC/process-group implementation может отличаться от Linux production, но contract tests должны сохранять lifecycle semantics.

Production acceptance выполняется на Linux container profile.

## 21. Required tests

1. две BrowserSession находятся в разных session subprocesses;
2. каждая session запускает отдельный Chromium;
3. зависание event loop/session A не блокирует session B;
4. graceful close завершает subprocess и Chromium descendants;
5. forced terminate завершает зависший subprocess;
6. hard-kill fallback не убивает другую session;
7. unexpected subprocess crash → session lost/failed;
8. action in-flight после crash даёт `unknown`, где side effect нельзя исключить;
9. repeated create/close soak не оставляет child/zombie Chromium/Python;
10. worker crash/container stop не оставляет orphan descendants;
11. worker drain reaps all session subprocesses;
12. capacity slot освобождается только после reap;
13. snapshot ElementHandles никогда не сериализуются supervisor-у;
14. session subprocess не содержит DB/Redis/internal service credentials;
15. Content artifact handoff не требует прямого ContentStore доступа subprocess-а.

## 22. Consequences

Плюсы:

- надёжный per-session hard-kill boundary;
- clear ownership live browser graph;
- меньший crash/hang blast radius;
- отсутствие зависимости от private Playwright process API;
- проще soak/leak testing;
- понятнее rolling drain.

Минусы:

- дополнительный Python process на session;
- выше startup latency и RAM;
- нужен внутренний supervisor/session IPC;
- сложнее worker implementation;
- artifact handoff требует отдельного bounded protocol.

Trade-off принимается, потому что Browser является stateful high-risk capability, а Web Access проектируется как долгоживущий production service, а не локальный Playwright wrapper.

## 23. Что superseded в ADR-0012

Superseded следующие детали ADR-0012:

- один общий Playwright runtime внутри Browser Worker;
- прямое владение worker-ом Playwright `Browser`/`BrowserContext` objects разных sessions;
- предположение, что worker сможет гарантировать per-session process-tree hard-kill через browser process handle.

Сохраняются:

- отдельный Chromium process на BrowserSession;
- non-persistent BrowserContext;
- process-per-session isolation rationale;
- capacity-first подход;
- отсутствие shared Browser pool baseline;
- отсутствие persistent profiles baseline.

## 24. Не определяется

- exact local IPC library/protocol framing;
- exact OS process-group helper library;
- per-session cgroup implementation;
- future process pooling optimization;
- future BrowserSession migration/recovery.
