# ADR-0012 — BrowserSession владеет отдельным Chromium process

**Статус:** superseded in part by [ADR-0015](ADR-0015-browser-session-subprocess-boundary.md)

## Сохраняемое решение

Базовый инвариант остаётся принят:

```text
1 BrowserSession
→ 1 Chromium process
→ 1 non-persistent BrowserContext
→ N Pages
```

Web Access не использует baseline:

- один общий Chromium process для многих BrowserSession;
- BrowserContext pool как основную isolation-модель;
- persistent `user_data_dir`;
- automatic session migration/restart после browser crash.

Причины сохраняются:

- browser process crash должен затрагивать только одну BrowserSession;
- cross-session blast radius должен быть минимален;
- lifecycle/cleanup должен быть измеримым на уровне одной session;
- Browser является намеренно дорогой capability, поэтому плотность sessions не важнее изоляции;
- pooling может появиться только отдельным ADR после реальных load measurements.

## Что superseded

Первоначальная версия ADR предполагала, что один Browser Worker process напрямую владеет несколькими Playwright runtime objects и вызывает отдельный `browser_type.launch()` для каждой BrowserSession.

Эта process-management часть заменена ADR-0015.

Новая модель:

```text
Browser Worker supervisor
→ отдельный Python session subprocess
→ Playwright
→ отдельный Chromium process
→ non-persistent BrowserContext
→ Pages
```

Причина изменения: production lifecycle должен гарантировать bounded terminate/hard-kill конкретной зависшей session и всего её child process tree без зависимости от private Playwright process internals.

## Capacity direction

Initial configurable default остаётся:

```text
max_sessions_per_worker = 4
```

Это стартовый operational профиль, а не универсальная константа. Capacity slot освобождается только после полного завершения/reap session subprocess согласно ADR-0015.

## Security

Отдельный process/subprocess не считается полной sandbox boundary.

Остаются обязательными:

- Chromium sandbox;
- non-root Browser Worker;
- Browser egress boundary из ADR-0014;
- отсутствие DB/Redis/ContentStore credentials в session runtime;
- container/process limits;
- bounded temp storage;
- worker/session cleanup tests.

## Tests, которые остаются обязательными

- две sessions используют разные Chromium processes;
- browser crash одной session не убивает другую;
- cookies/storage isolated;
- process/session close не оставляет Chromium descendants;
- repeated create/close soak не оставляет zombies;
- worker/container shutdown не оставляет orphan processes;
- capacity ограничивается и корректно освобождается.

Полный process-management и hard-kill acceptance contract находится в ADR-0015.
