# ADR-0012 — BrowserSession владеет отдельным Chromium process

**Статус:** accepted

## 1. Контекст

Browser Worker должен обслуживать несколько одновременных BrowserSession.

Варианты:

- один Chromium process + много BrowserContext;
- пул Chromium processes;
- отдельный Chromium process на каждую BrowserSession.

BrowserContext хорошо изолирует cookies/storage, но не является самостоятельной OS/security boundary. Кроме того, crash общего browser process потеряет все contexts внутри него.

Web Access использует Browser как более тяжёлую capability после Search/Retrieval, поэтому максимальная плотность sessions не является главным критерием первой реализации.

---

## 2. Решение

Baseline v0.4:

```text
BrowserSession
→ one Playwright Browser process
→ one non-persistent BrowserContext
→ one initial Page
→ optional additional pages/popups
```

Browser Worker управляет несколькими такими session runtimes в одном worker process/container, но Chromium process у каждой session отдельный.

---

## 3. Почему separate browser process

Преимущества:

- browser process crash теряет только одну session;
- меньше cross-session blast radius;
- cleanup проще: закрытие session завершает её browser process;
- session-specific process/resource accounting понятнее;
- никакого shared persistent browser cache/state между sessions;
- проще диагностировать zombie/leak;
- worker можно масштабировать ограниченным количеством дорогих sessions.

---

## 4. Почему не shared BrowserContext pool baseline

Один Browser process с множеством contexts экономичнее, но:

- browser crash теряет все sessions worker-а;
- общая browser-process state/security blast radius шире;
- profile/process resource leak затрагивает соседние sessions;
- позже сложнее доказать per-session cleanup.

Optimization не должна опережать измерения.

Если load tests покажут, что process-per-session является главным bottleneck, shared/pool mode можно добавить отдельным ADR при сохранении public BrowserSession contract.

---

## 5. BrowserContext

Даже внутри отдельного process создаётся отдельный non-persistent BrowserContext.

Не используется persistent `user_data_dir` baseline.

Причины:

- ephemeral state;
- no disk persistence by default;
- clean session lifecycle;
- future persistent profiles остаются отдельной capability.

---

## 6. Browser launch

Worker использует один Playwright runtime, но вызывает `browser_type.launch()` на session create.

Launch config server-controlled:

- Chromium executable/version from pinned Playwright image;
- sandbox enabled;
- headless baseline;
- no arbitrary client args;
- bounded temp/profile dir;
- no extension loading;
- approved proxy only if future policy explicitly enables it.

---

## 7. Session runtime object

Worker memory conceptually:

```text
BrowserSessionRuntime
├── session_id
├── browser process handle
├── browser context
├── pages registry
├── snapshot/ref maps
├── action queue/lock
├── event buffers
├── recent action ledger
├── temp artifacts
└── lifecycle/deadlines
```

Ничего из Playwright object graph не сериализуется в PostgreSQL/Redis.

---

## 8. Capacity baseline

Initial default per Browser Worker:

```text
max_sessions = 4
```

Operator configurable.

Hard ceiling задаётся deployment/profile и должен быть измерен load tests; code не предполагает, что 4 — universal optimum.

Worker дополнительно имеет:

- max pages/session;
- max pending action queue;
- temp-storage limits.

---

## 9. Initial page

После process + context create worker создаёт одну blank page.

Result:

```text
session_id
initial page_id
```

Navigation отдельна.

---

## 10. Session close

Canonical cleanup order:

1. mark runtime closing/reject new actions;
2. cancel/finish current action according policy;
3. finalize/cleanup pending artifacts;
4. dispose snapshot ElementHandles/maps;
5. close pages/context;
6. close Browser process;
7. delete temp profile/session directory;
8. report terminal close result.

Browser process должен быть bounded-killable, если graceful close завис.

---

## 11. Browser process crash

Playwright/browser disconnect/crash для session:

```text
that BrowserSession → lost/failed according evidence
```

Другие sessions worker-а должны продолжить работу, если worker process healthy.

Worker emits event/heartbeat capacity update.

---

## 12. Worker crash

Если сам Browser Worker process/container погиб:

- все child Chromium processes также должны быть уничтожены container/process-group semantics;
- все sessions worker generation → lost after ADR-0009 lease/grace;
- new worker generation не наследует их.

Docker init/process tree configuration должна предотвращать orphan Chromium после worker death.

---

## 13. Process groups

Browser process lifecycle должен позволять принудительно уничтожить весь Chromium child tree конкретной session, а не только top-level wrapper process.

Implementation обязана использовать Playwright close + OS/container process-group cleanup fallback, проверенный integration tests.

Не полагаться только на garbage collection.

---

## 14. Temp directories

Каждая session имеет отдельный generated temp root.

Он содержит только ephemeral browser-owned state/artifacts.

Requirements:

- no user path;
- bounded disk;
- cleanup on close;
- startup/reaper cleanup stale dirs after worker crash;
- not mounted as persistent ContentStore.

---

## 15. Downloads

Browser download сохраняется во временном session space только до Content handoff.

После successful ContentObject finalization temp download удаляется.

Session close не должен удалить уже persisted ContentObject.

---

## 16. Memory/resource accounting

Worker tracks per-session coarse metrics:

- browser process alive;
- pages;
- temp bytes;
- creation/action timing.

Precise per-process RSS/CPU может собираться operationally where platform supports it.

Worker rejects new session before host/container memory exhaustion according capacity policy, а container memory limit остаётся defense in depth.

---

## 17. Security

Separate process не считается достаточной sandbox boundary сам по себе.

Остаются обязательными:

- Chromium sandbox;
- non-root container;
- browser egress restrictions;
- no DB/Redis/ContentStore credentials worker baseline;
- process/container limits;
- no host filesystem/socket access.

Но separate process уменьшает cross-session blast radius внутри worker.

---

## 18. Local development

Process-per-session остаётся тем же behavior в local profile, чтобы development не тестировал принципиально другую lifecycle model.

Local `max_sessions` может быть меньше, если laptop resources ограничены.

---

## 19. Performance strategy

Не оптимизировать process density до v0.4 load baseline.

Измерить:

- launch latency;
- RAM/session;
- action latency;
- max stable sessions/worker;
- cleanup latency;
- worker drain time.

Только после этого возможен ADR shared browser/pool.

---

## 20. Tests

1. two sessions use different Chromium processes;
2. cookies/storage isolated;
3. crash browser process A does not kill B;
4. session close kills its process tree;
5. worker crash leaves no orphan Chromium after container/process cleanup;
6. max_sessions enforced;
7. capacity release after close;
8. temp dirs isolated/cleaned;
9. repeated create/close soak no zombie processes;
10. rolling drain closes all child processes by deadline.

---

## 21. Consequences

Плюсы:

- сильнее isolation/crash containment;
- ясный ownership;
- simpler cleanup;
- Browser remains intentionally expensive fallback;
- easier leak debugging.

Минусы:

- больше RAM/CPU;
- выше session creation latency;
- меньше sessions на worker;
- больше Chromium process churn.

Trade-off принимается до появления измерений, доказывающих необходимость pooling.

---

## 22. Не определяется

- exact Chromium launch args;
- hard max_sessions production;
- OS process inspection library;
- future shared process mode;
- persistent profiles.
