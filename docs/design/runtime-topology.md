# Runtime Topology Web Access MCP

## Статус документа

Этот документ является каноническим владельцем **process topology, runtime boundaries, ownership live state и направления масштабирования** проекта.

Он не фиксирует окончательный протокол Browser Worker routing, Redis keys, точные replica counts или container manifests. Эти детали определяются позже в `deployment.md` и отдельных ADR.

---

# 1. Цель topology

Архитектура должна позволять:

- локальный запуск одним `docker compose`;
- независимое масштабирование control plane, durable workers и browser workers;
- отсутствие скрытой привязки resource lifecycle к одному API process;
- graceful restart отдельных компонентов;
- сохранение durable metadata при потере process;
- контролируемую деградацию при недоступности зависимостей.

---

# 2. Базовая topology

```text
                         ┌───────────────────────┐
                         │      REST clients     │
                         └──────────┬────────────┘
                                    │
                         ┌──────────▼────────────┐
                         │    API/MCP ingress    │
                         │   control plane × N   │
                         └───┬────────┬──────────┘
                             │        │
                   ┌─────────┘        └───────────────┐
                   ▼                                  ▼
          request-bound work                   browser routing
                   │                                  │
          ┌────────┼─────────┐                        ▼
          ▼        ▼         ▼                Browser Worker × N
       Search   Retrieval  Content                    │
          │        │         │                       Chromium /
          │        │         │                       Playwright
          │        │         │
          └────────┼─────────┘
                   │
                   ▼
       PostgreSQL / Redis / ContentStore
                   ▲
                   │
             durable jobs
                   │
            Job Worker × N
```

SearXNG и другие providers находятся за Search adapters и могут быть отдельными services.

---

# 3. Runtime classes

В целевой архитектуре различаются как минимум три основных исполняемых runtime-а.

## 3.1. Control Plane

Предварительный executable:

```text
web-access-api
```

Содержит:

- FastAPI;
- FastMCP;
- REST facade;
- MCP facade;
- application services;
- request-bound orchestration;
- доступ к repositories/cache/coordination adapters;
- routing к Browser Worker;
- enqueue durable Jobs.

Control Plane должен быть преимущественно stateless относительно live resources и пригоден для горизонтального масштабирования.

---

## 3.2. Job Worker

Предварительный executable:

```text
web-access-worker
```

Предназначен для durable/background операций.

Возможные классы работы:

- crawl;
- large batch processing;
- длительные background operations;
- операции, которым по contract требуется переживать client disconnect.

Job Worker не должен быть обязательным execution path каждой короткой операции.

---

## 3.3. Browser Worker

Предварительный executable:

```text
web-access-browser-worker
```

Является владельцем live browser state.

Только Browser Worker хранит фактические:

- Playwright `Browser`;
- `BrowserContext`;
- `Page`;
- runtime locators/handles;
- transient browser execution state.

Browser Worker имеет отдельный lifecycle и scaling model от Job Worker.

---

# 4. Почему Job Worker и Browser Worker разделены

Queue worker и stateful browser owner решают разные задачи.

## Job Worker

Работа может быть получена подходящим worker согласно queue semantics.

```text
job → любой совместимый worker
```

## Browser Worker

Следующее действие конкретной BrowserSession должно попасть именно к worker/runtime, который владеет живым BrowserContext.

```text
browser action
→ owning worker
```

Обычная shared work queue не гарантирует это свойство без дополнительного routing layer.

Поэтому Browser Worker не должен быть случайным arq consumer общей очереди browser actions.

---

# 5. Control Plane statelessness

Control Plane может иметь process-local caches/clients/pools, но не должен считать их authoritative состоянием пользовательских resources.

Недопустимая целевая модель:

```python
BROWSER_SESSIONS = {
    session_id: playwright_context,
}
```

внутри каждого API process как единственное место знания о BrowserSession.

При N replicas следующий client request может попасть на другой API instance.

---

# 6. Browser session routing

Целевая topology требует возможности определить owning Browser Worker по opaque `browser_session_id`.

Абстрактная схема:

```text
API replica
   ↓
BrowserApplicationService
   ↓
BrowserSession routing metadata
   ↓
BrowserWorkerClient
   ↓
owning Browser Worker
```

Точный механизм пока не фиксируется.

Кандидаты для отдельного ADR:

- direct internal HTTP/RPC к worker;
- Redis Streams/mailbox;
- другой explicit message/routing protocol.

Решение должно сравнивать:

- latency;
- ordering;
- cancellation;
- backpressure;
- worker crash behavior;
- unknown outcome;
- connection management;
- horizontal scaling;
- operational complexity.

---

# 7. Browser Worker identity

Каждый Browser Worker должен иметь runtime identity, пригодную для:

- registration;
- health/heartbeat;
- routing;
- graceful drain;
- detection worker loss;
- diagnostics.

Публичный BrowserSession handle не обязан раскрывать worker identity.

---

# 8. Browser worker lifecycle

Концептуально:

```text
starting
→ ready
→ accepting sessions
→ draining
→ stopped
```

При graceful drain:

- новые BrowserSession не назначаются worker-у;
- существующие sessions либо корректно завершаются, либо обрабатываются согласно migration/loss policy;
- shutdown имеет bounded timeout;
- server-side cleanup выполняется best effort.

Прозрачная миграция live Playwright state между workers не предполагается по умолчанию.

---

# 9. BrowserSession loss

Если owning Browser Worker погиб и live context утерян:

```text
BrowserSession → lost
```

Система не должна притворяться, что восстановила:

- DOM;
- JavaScript heap;
- popup state;
- текущие tabs;
- заполненные формы;
- transient browser state.

Если позднее появится частичное восстановление из persistent profile/storage state, оно должно быть отдельной явной capability и не менять факт потери исходной live session.

---

# 10. Browser process model

Точный внутренний pool model будет определён в `browser.md`.

На уровне topology фиксируется только:

- browser execution находится вне API process;
- один Browser Worker может владеть несколькими BrowserSessions в пределах resource policy;
- одна BrowserSession имеет одного active owner runtime;
- mutating actions внутри одной session должны иметь определённый ordering;
- разные sessions могут исполняться параллельно.

---

# 11. SearXNG topology

SearXNG рассматривается как отдельный search backend/service за `SearchProvider` adapter.

```text
Control Plane
→ SearchApplicationService
→ SearXNGProvider
→ SearXNG service
```

Web Access не должен зависеть от process-local запуска SearXNG внутри API runtime.

Локальный Compose может поднимать SearXNG рядом, но application boundary остаётся сетевой/provider-oriented.

---

# 12. PostgreSQL

PostgreSQL является durable structured storage.

Он должен быть доступен runtime-ам, которым по contract требуется durable metadata.

Предварительно:

- Control Plane использует repositories;
- Job Worker использует durable Job/state repositories;
- Browser lifecycle metadata может сохраняться через repositories;
- Browser Worker не обязан иметь прямой unrestricted DB access, если coordination protocol позволяет избежать этого.

Точная DB access topology проектируется в `persistence.md`/`browser.md` с принципом минимально необходимого доступа.

---

# 13. Redis

Redis является shared infrastructure для ограниченных задач.

Возможные роли:

- cache;
- rate limiting;
- arq queue;
- locks;
- leases/fencing;
- worker registry;
- short-lived routing metadata;
- event/coordination transport.

Конкретный runtime получает только те Redis capabilities, которые ему нужны.

---

# 14. ContentStore

ContentStore является shared durable/managed storage для крупных raw/derived representations.

В локальном deployment:

```text
shared filesystem volume
```

может быть допустимым adapter.

В горизонтально масштабируемом deployment предпочтителен storage, доступный всем необходимым runtime-ам, например S3-compatible object storage.

Application contract не должен зависеть от выбранного deployment backend.

---

# 15. Request-bound execution path

Типовой короткий вызов:

```text
Client
→ REST/MCP transport
→ Application Service
→ provider/repository/content adapter
→ OperationResult
→ Client
```

Примеры:

- Search;
- HTTP Retrieval;
- Content read/inspection/native parsing в допустимых пределах;
- Browser action, который маршрутизируется owning worker и возвращает результат в рамках текущего request.

Request-bound не означает отсутствие operation identity/telemetry.

---

# 16. Durable execution path

Типовой Job lifecycle:

```text
Client
→ Control Plane
→ durable Job state в PostgreSQL
→ queue publication
→ Job Worker
→ application execution
→ durable result/state/events
→ Client poll/read result
```

Точный dual-write contract `PostgreSQL ↔ Redis` пока не фиксируется и должен быть спроектирован отдельно.

---

# 17. Commit-before-enqueue как исходный ориентир

Рабочая архитектура KudaGo показывает безопасную базовую идею:

```text
сначала durable state
→ затем enqueue
```

Но Web Access design должен отдельно определить crash window между commit и enqueue и recovery strategy.

До этого нельзя считать простой dual write окончательным production contract.

Будут рассмотрены:

- retry/reconciliation;
- transactional outbox;
- другие устойчивые варианты.

---

# 18. Operation cancellation topology

## Request-bound

Client disconnect/deadline может инициировать cooperative cancellation, если операция это допускает.

## Durable Job

Client disconnect не отменяет Job.

Cancellation выполняется через отдельную job operation/state transition.

## Browser Action

Cancellation зависит от стадии action и фактической возможности остановить Playwright/upstream side effect.

Cancellation не должна ложно превращать неопределённый side effect в `cancelled`, если его результат неизвестен.

---

# 19. Graceful shutdown Control Plane

При shutdown API/MCP instance должен:

- прекратить принимать новые запросы;
- завершить или bounded-cancel request-bound operations;
- корректно закрыть pools/clients;
- не считать shutdown причиной закрыть все BrowserSessions сервиса;
- не уничтожать durable Jobs.

Resource lifecycle независим от жизни конкретной API replica.

---

# 20. Graceful shutdown Job Worker

Job Worker должен:

- прекратить брать новую работу;
- обработать in-flight jobs согласно queue/job semantics;
- корректно сохранить terminal/interrupted state;
- не оставлять indefinite leases/locks.

Точная retry/fencing semantics определяется в `jobs.md`.

---

# 21. Graceful shutdown Browser Worker

Browser Worker требует отдельной стратегии:

- stop assigning new sessions;
- mark worker draining;
- attempt bounded cleanup/closure;
- корректно отразить lost/closed sessions;
- не допустить silent disappearance live sessions из registry.

Политика drain vs forced loss определяется `browser.md`.

---

# 22. Health и readiness

Каждый runtime должен различать как минимум:

- process alive;
- ready to accept new work;
- degraded but partially functional.

Примеры:

- API жив, но SearchProvider недоступен;
- API жив, PostgreSQL недоступен;
- Browser Worker жив, но не принимает новые sessions из-за capacity;
- Redis недоступен, request-bound Search потенциально работает, а durable Jobs — нет.

Нельзя сводить всё к одному `200 /health` без capability-aware readiness model.

Точная модель проектируется в `observability.md`/`deployment.md`.

---

# 23. Degraded operation

Web Access должен по возможности деградировать по capabilities, а не целиком.

Пример:

```text
Browser workers unavailable
→ Search/Retrieval/Content могут продолжить работу
→ Browser capability reports unavailable
```

Но если security/persistence prerequisite конкретной операции недоступен, operation должна корректно отклоняться, а не обходить обязательную зависимость.

---

# 24. Horizontal scaling Control Plane

Control Plane replicas должны быть взаимозаменяемыми для новых REST/MCP requests.

Это требует:

- shared durable resource model;
- shared/routeable BrowserSession metadata;
- отсутствия обязательного sticky-session предположения;
- opaque resource handles;
- idempotency/retry semantics на application уровне.

Sticky routing может использоваться как optimization, но не как единственная корректность системы без отдельного design decision.

---

# 25. Horizontal scaling Job Workers

Job Workers масштабируются как worker pool согласно queue semantics.

Job type/capabilities могут в будущем позволить разные worker pools, но application Job contract не должен зависеть от конкретного hostname/container.

---

# 26. Horizontal scaling Browser Workers

Browser Worker pool масштабируется по:

- session capacity;
- CPU/RAM;
- browser process limits;
- operational policy.

Placement новой BrowserSession является scheduling problem infrastructure уровня.

LLM/MCP client не выбирает конкретный worker.

---

# 27. Runtime security boundaries

Browser Worker должен рассматриваться как более рискованный runtime из-за выполнения внешнего JavaScript/browser workload.

Желательно минимизировать его доступ к:

- database credentials;
- Redis capabilities;
- secrets;
- host filesystem;
- internal network.

Конкретная container/network security model проектируется в `security.md` и `deployment.md`.

---

# 28. No hidden in-process shortcut as canonical path

Для разработки допустимы test/in-memory adapters.

Но production architecture не должна тайно опираться на то, что:

- API и Browser Worker находятся в одном process;
- filesystem локален одному container;
- один Redis connection/client является глобальным singleton correctness primitive;
- одна API replica существует всегда.

Локальная простота достигается adapters/configuration, а не разрушением boundary.

---

# 29. Entrypoints

Предварительно проект должен иметь тонкие entrypoints:

```text
entrypoints/api.py
entrypoints/job_worker.py
entrypoints/browser_worker.py
```

Они загружают configuration, вызывают bootstrap/composition root и запускают runtime.

Business logic в entrypoints запрещена.

---

# 30. Open decisions

Следующие вопросы намеренно остаются открытыми:

1. Протокол Control Plane ↔ Browser Worker.
2. Browser Worker registry/heartbeat/lease mechanism.
3. Необходимость fencing token для BrowserSession actions.
4. Точная DB access policy Browser Worker.
5. Точная durable Job publication strategy: reconciliation vs outbox.
6. ContentStore default production backend.
7. Capability-aware readiness schema.
8. Browser session placement/capacity algorithm.

Они должны закрываться component design/ADR, а не случайным решением во время реализации.
