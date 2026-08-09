# ADR-0013 — BrowserSession runtime subprocess

**Статус:** accepted

**Заменяет:** ADR-0012 в части process ownership/kill boundary. Принцип «отдельный Chromium process на BrowserSession» сохраняется и усиливается.

## 1. Контекст

ADR-0012 принял отдельный Chromium process на BrowserSession ради crash containment и меньшего cross-session blast radius.

При детализации implementation обнаружилась важная граница: публичный Python Playwright API не должен использоваться как источник private OS PID/process-tree contract для точечного hard-kill зависшего Chromium.

Если Browser Worker supervisor сам владеет всеми Playwright Browser objects, гарантированный kill одной зависшей session может потребовать private Playwright internals или уничтожить весь worker.

Нужно сделать hard cleanup enforceable обычными OS process primitives.

---

## 2. Решение

Каждая BrowserSession выполняется в отдельном **Browser Session Runtime subprocess**:

```text
Browser Worker supervisor
    │
    ├── session subprocess A
    │      └── Playwright runtime/driver
    │             └── Chromium process A
    │                    └── BrowserContext/Pages
    │
    └── session subprocess B
           └── Playwright runtime/driver
                  └── Chromium process B
```

Browser Worker supervisor не хранит Playwright `Browser/Page/ElementHandle` objects конкретной session.

Они живут только внутри session subprocess.

---

## 3. Responsibility split

### Browser Worker supervisor

Владеет:

- internal HTTP/RPC server;
- registration/heartbeat/lease;
- worker capacity;
- subprocess registry;
- session process lifecycle;
- action ledger/correlation на coordinator level;
- IPC transport;
- artifact streaming наружу;
- process tree terminate/kill fallback.

### Browser Session Runtime subprocess

Владеет:

- Playwright startup/shutdown;
- Chromium process;
- BrowserContext;
- Pages;
- snapshot/ref maps;
- ElementHandles;
- Playwright Locators;
- serialized action execution;
- browser event collection;
- session-local temporary artifacts.

---

## 4. Почему это лучше прямого multi-browser supervisor

- hard-kill boundary = обычный child process;
- зависший Playwright driver не блокирует supervisor;
- session-specific Python memory leak исчезает вместе с subprocess;
- Playwright/Chromium crash affects one session;
- child environment можно минимизировать отдельно;
- snapshot ElementHandles естественно остаются рядом с Playwright objects;
- supervisor остаётся небольшим control process.

---

## 5. IPC baseline

Browser Worker ↔ Session Runtime использует **локальный framed JSON IPC** поверх subprocess stdin/stdout или эквивалентных OS pipes.

Baseline direction:

```text
supervisor
→ newline/framed JSON command
→ session subprocess
→ newline/framed JSON result/event
→ supervisor
```

Большие artifacts не передаются inline JSON.

---

## 6. Почему не Redis/internal HTTP для child

Session subprocess находится в том же worker/container.

Ему не нужен:

- Redis;
- TCP listener;
- service authentication;
- PostgreSQL.

Local pipe:

- меньше attack surface;
- не требует port management;
- автоматически связан с parent child process;
- удобен для hard kill.

---

## 7. IPC protocol

Versioned envelope:

```text
protocol_version = 1
session_id
action_id
command_type
payload
deadline/timeout metadata
```

Result:

```text
protocol_version
action_id
status
result/error
temporary_artifacts[]
events[]
```

No pickle.

Unknown protocol/command rejected.

---

## 8. Session subprocess entrypoint

Например:

```text
python -m web_access.workers.browser_session
```

Supervisor запускает через `asyncio.create_subprocess_exec`.

No shell invocation.

---

## 9. Environment allowlist

Session child получает только необходимые environment/config fields:

- Playwright/browser paths;
- browser profile config;
- temp root;
- logging/tracing correlation minimum;
- safe runtime limits.

**Не передаются:**

- PostgreSQL credentials;
- Redis credentials;
- Yandex/Search secrets;
- external REST/MCP bearer principal registry;
- Browser Worker bootstrap credential;
- ContentStore credentials.

---

## 10. Process group/tree

Supervisor запускает child так, чтобы иметь собственную process-tree cleanup boundary.

POSIX:

- separate process session/group where practical;
- terminate/kill entire session process group fallback.

Windows local development:

- child tree tracked;
- `psutil`-style recursive process cleanup допустим как cross-platform fallback.

Добавить dependency:

```text
psutil
```

только Browser Worker image/runtime.

Integration tests должны доказать отсутствие orphan Chromium/driver processes после forced kill.

---

## 11. Playwright startup inside child

Session Runtime самостоятельно:

```text
async_playwright().start()
→ chromium.launch(...)
→ browser.new_context(...)
→ context.new_page()
```

и хранит objects до session close.

Session child не запускает MCP/FastAPI.

---

## 12. Action serialization

Поскольку один child обслуживает одну BrowserSession, main child event loop выполняет только один mutating/action command одновременно.

Supervisor также не отправляет два concurrent commands без session queue discipline.

Double serialization является defense-in-depth против IPC bug.

---

## 13. Action ledger placement

Authoritative recent action ledger для network response recovery остаётся в **Browser Worker supervisor**, потому что direct RPC status query приходит supervisor-у.

Child может иметь текущий action state, но coordinator знает:

- received;
- dispatched to child;
- running;
- terminal result received.

Если child dies after dispatch before terminal result:

```text
mutating action → unknown
read-only action → failed/lost according semantics
session → lost/failed
```

---

## 14. Snapshot state

Snapshot maps/ElementHandles живут только child-side.

Supervisor видит serialized snapshot result/public refs, но не может сам resolve element_ref.

Следующий action с element_ref пересылается child, который проверяет ADR-0010 identity map.

---

## 15. Browser events

Child собирает page/browser events и отправляет их supervisor-у bounded batches/records через IPC.

Supervisor поддерживает external `browser_events` bounded buffer/sequence.

Если child event stream overflow:

- drop/gap recorded;
- no unbounded stdout pipe memory.

---

## 16. Artifacts

Child пишет screenshot/download/rendered HTML только в **собственный private session temp directory**.

Result возвращает local **relative artifact handle**, не arbitrary path.

Supervisor валидирует artifact находится под assigned session temp root и создаёт internal `bart_*` handle для Control Plane streaming.

Child не знает ContentStore.

---

## 17. Session close

Supervisor sends graceful `close` command.

Child:

1. closes context/pages;
2. closes browser;
3. stops Playwright;
4. flushes final events/artifact metadata;
5. exits.

Если не завершился в `closing_grace`:

```text
supervisor terminate child tree
→ bounded wait
→ kill child tree
```

Теперь эта guarantee не зависит от private Browser PID API.

---

## 18. Session process crash

Supervisor detects EOF/process exit.

- all pending actions classified by dispatch state;
- session becomes `lost`/`failed` according lifecycle;
- temp artifacts cleaned/reconciled;
- worker remains healthy for other sessions;
- capacity slot released.

---

## 19. Worker crash

Container/worker process death destroys supervisor + all child session processes through container/PID tree.

ADR-0009 heartbeat/lease marks sessions lost.

No child independently reconnects to Control Plane.

---

## 20. Resource limits

Per-session subprocess makes OS controls easier.

Supervisor/deployment may enforce:

- session process memory/RSS monitoring;
- process count;
- temp bytes;
- max pages;
- wall lifetime.

Container still sets global worker limits.

Exact per-process cgroup unavailable in ordinary Docker without nested control; hard worker-wide container limit remains defense-in-depth.

---

## 21. Tracing/logging

Child stdout is reserved for framed protocol if chosen, therefore structured logs must use stderr or separate inherited logging pipe/file descriptor.

Protocol parser must never confuse log line with result frame.

Preferred implementation:

```text
stdin/stdout = framed protocol
stderr = structured child diagnostics collected by supervisor
```

Secrets/page content redaction rules remain.

---

## 22. Protocol framing

Plain newline JSON is acceptable only if JSON encoder guarantees one object/line and large payloads/artifacts externalized.

Better baseline:

```text
length-prefixed UTF-8 JSON frames
```

чтобы embedded newlines/text never create framing ambiguity.

Implementation uses 4-byte big-endian length prefix + JSON payload with hard max frame size.

---

## 23. IPC frame limits

Initial:

```text
max command frame = 1 MiB
max result frame = 2 MiB
```

Large snapshot/artifact uses temp artifact/Content path.

Oversized frame terminates protocol/session safely.

---

## 24. Consequences

Плюсы:

- enforceable hard-kill per session;
- session-local Playwright memory/state;
- smaller worker blast radius;
- no reliance on private Playwright process handles;
- clean child secret isolation;
- robust soak/leak cleanup.

Минусы:

- ещё один internal IPC layer;
- Python + Playwright driver process overhead per session;
- higher memory/start latency than shared Playwright runtime;
- supervisor must manage process trees/framing.

Trade-off принимается для correctness/security-first Browser baseline.

---

## 25. Влияние на ADR-0012

Сохраняется решение:

```text
one BrowserSession → own Chromium process/context
```

Но изменяется owner:

```text
было:
Browser Worker process directly owns Playwright objects

стало:
Browser Worker supervisor owns session subprocess;
session subprocess owns Playwright/Chromium objects
```

Если текст ADR-0012 противоречит этому документу, ADR-0013 имеет приоритет.

---

## 26. Tests

1. two sessions → two session subprocesses;
2. each child launches own Chromium;
3. kill child A does not affect B;
4. hung close → terminate/kill tree;
5. no orphan Playwright driver/Chromium;
6. child env lacks DB/Redis/Yandex/Auth secrets;
7. malformed/oversized IPC frame terminates only session;
8. child stdout protocol not corrupted by logs;
9. action response loss/crash yields correct unknown;
10. snapshot refs remain functional inside child lifetime;
11. temp artifacts cannot escape session temp root;
12. repeated create/close soak returns process count baseline.

---

## 27. Не определяется

- exact Python module names;
- exact psutil usage on POSIX vs Windows;
- exact child log forwarding format;
- future shared-browser process optimization.
