# ADR-0025 — Core Browser facade требует explicit `browser_scroll`

**Статус:** accepted

## 1. Контекст

ADR-0022 freeze candidate содержал bounded `browser_snapshot`, но не отдельную scroll capability.

Snapshot intentionally bounded:

```text
MCP inline semantic view <= bounded chars
refs <= bounded count
```

На длинной/lazy-loaded странице это создаёт функциональную дыру:

```text
нужный interactive element ниже текущей области / появляется после scroll
→ его нет в текущем bounded snapshot/ref inventory
→ agent не может надёжно получить element_ref
```

`browser_content` не решает это, потому что предназначен для чтения rendered document, а не для изменения viewport/UI state и получения interactive refs.

---

## 2. Решение

Добавить отдельный semantic core tool:

```text
browser_scroll
```

и соответствующий REST typed action.

Это реальный уникальный intent, не alias существующей операции.

ADR-0022 catalog superseded **только в части количества/catalog list**: freeze candidate теперь 28 tools.

Остальные правила ADR-0022 сохраняются.

---

## 3. Почему не auto-scroll внутри snapshot

Snapshot не должен скрыто менять page state.

Иначе:

- read operation становится mutating;
- lazy loading/network side effects происходят неожиданно;
- scroll position теряется;
- snapshot result difficult to reproduce;
- Agent Dispatcher metadata неверна.

`browser_snapshot` остаётся read-only относительно page interaction state.

---

## 4. Почему не pixel coordinates scripting

Core MCP не должен превращаться в low-level mouse automation.

Baseline scroll выражается относительно viewport:

```text
direction = up | down | left | right
viewport_units = 0.1 .. 3.0
```

`1.0` означает примерно один текущий viewport по выбранной оси.

Optional `element_ref` позволяет скроллить конкретный scrollable container, когда он однозначно адресован snapshot ref.

Без `element_ref` scroll применяется к page viewport/document scrolling context.

---

## 5. Exact input direction

```text
session_id
page_id
direction: up | down | left | right
viewport_units: number default 0.8, minimum 0.1, maximum 3.0
element_ref: optional
```

No arbitrary x/y coordinates.

No free-form JavaScript.

---

## 6. Execution semantics

Scroll изменяет viewport/page UI state и может косвенно вызвать:

- lazy loading;
- network requests;
- intersection-observer behavior;
- sticky/infinite-scroll transitions.

Поэтому:

```text
readOnlyHint=false
idempotentHint=false
destructiveHint=false
openWorldHint=true
Agent retry=no blind automatic retry after uncertain dispatch
```

Повтор scroll после lost response может прокрутить страницу дважды.

---

## 7. Result

Bounded result:

```text
action_id
page_generation
scroll_state:
  x
  y
  viewport_width
  viewport_height
  at_start_x
  at_end_x
  at_start_y
  at_end_y
```

Coordinates в **result diagnostics** допустимы; они не являются low-level action targeting contract.

Tool не возвращает новый snapshot автоматически.

Agent явно вызывает:

```text
browser_scroll
→ browser_snapshot
```

Это сохраняет observability каждого state transition.

---

## 8. Element/container scroll

Если `element_ref` передан:

- ref проходит обычную exact/stale validation ADR-0010;
- target должен быть scrollable по requested axis;
- unavailable/non-scrollable target returns repairable error;
- no fallback to page scroll silently.

---

## 9. REST

Добавляется typed endpoint:

```text
POST /api/v1/browser/sessions/{session_id}/pages/{page_id}/actions/scroll
```

REST использует ту же semantic model; может иметь более широкий bounded `viewport_units` только если explicitly versioned, но v1 baseline совпадает с MCP для predictability.

---

## 10. Tests

Обязательны:

- page viewport vertical/horizontal scroll;
- scrollable nested container by ElementRef;
- stale ref;
- non-scrollable element;
- infinite/lazy content fixture;
- lost response → no automatic second scroll;
- new snapshot after scroll exposes newly available refs;
- scroll does not auto-snapshot;
- max/min units schema validation.
