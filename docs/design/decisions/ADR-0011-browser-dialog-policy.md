# ADR-0011 — Browser dialogs: explicit per-action policy, safe default dismiss-and-report

**Статус:** accepted

## 1. Контекст

JavaScript dialogs (`alert`, `confirm`, `prompt`, `beforeunload`) блокируют browser page/action до обработки.

Нельзя:

- оставлять dialog висеть неопределённо;
- автоматически `accept` всё;
- скрывать факт dialog от агента;
- превращать dialog в отдельный долгоживущий remote resource без необходимости.

Одновременно агенту иногда нужно сознательно принять confirm/prompt.

---

## 2. Рассмотренные варианты

### A. Всегда auto-dismiss

Безопасно, но невозможно выполнить legitimate workflow с confirm/prompt.

### B. Всегда auto-accept

Неприемлемо: может подтвердить destructive action.

### C. Оставлять pending dialog и отдельным tool отвечать позже

Требует suspended action protocol, отдельного dialog resource/lifecycle и легко создаёт blocked session.

### D. Per-action `dialog_policy` + safe default dismiss-and-report

Action заранее задаёт, как обрабатывать dialog, если он появится. Неожиданный/default dialog dismiss-ится, action result явно сообщает событие.

---

## 3. Решение

Принимается вариант **D**.

Каждый mutating/navigation BrowserAction contract может иметь optional:

```text
dialog_policy
```

Default:

```text
dismiss
```

---

## 4. DialogPolicy schema

Canonical internal/application concept:

```text
behavior = dismiss | accept
prompt_text = str | null
```

Rules:

- `prompt_text` разрешён только с `accept`;
- max prompt text length bounded;
- policy относится **к следующему/текущему action**, а не к session-global future dialogs;
- после action policy исчезает.

---

## 5. Default dismiss semantics

Если dialog появился и caller не передал policy:

```text
worker dismisses dialog
→ records BrowserDialogEvent
→ action result includes warning/event
```

Human-readable message не утверждает, что original operation «не имела side effect» — dialog мог появиться после других JS/network effects.

---

## 6. Explicit accept

Caller может заранее указать:

```text
dialog_policy.behavior = accept
```

для action, от которого ожидает confirm/alert/beforeunload.

Prompt:

```text
prompt_text
```

передаётся только для prompt.

При неожиданном dialog type policy всё равно применяет accept/dismiss according type; incompatible prompt_text игнорировать молча нельзя — validation/rejection.

---

## 7. No pending dialog resource baseline

Dialog не получает `dialog_id` для отдельного follow-up tool.

Причины:

- action должен завершиться bounded;
- page dialog блокирует дальнейшее взаимодействие;
- suspended action + follow-up значительно усложняет worker protocol;
- per-action explicit intent покрывает практический workflow.

Если реальные use cases покажут необходимость inspection-before-answer, это отдельный future design.

---

## 8. `beforeunload`

Default dismiss:

- navigation/close может быть отменён page dialog semantics;
- result сообщает dialog event и фактический final URL/page state.

Explicit accept разрешает navigation/close продолжиться.

Agent должен сначала решить, безопасно ли покинуть страницу.

---

## 9. Action result

Browser action result включает bounded dialog events:

```text
dialog_type
message_preview (untrusted)
default_value_preview (redacted/bounded)
action_taken = accepted | dismissed
timestamp
```

Dialog message является **untrusted page content**.

Не использовать message как trusted hint/instruction.

---

## 10. Multiple dialogs

Один action теоретически может вызвать несколько dialogs.

Same per-action policy применяется ко всем dialogs в пределах bounded action lifetime.

Есть hard `max_dialogs_per_action` (initial default 5).

Превышение:

```text
browser_dialog_limit_exceeded
```

и action/session recovery согласно state.

Это защищает от dialog spam loop.

---

## 11. Dialog outside active action

Если page создаёт dialog asynchronously между actions:

- worker immediately dismisses его;
- сохраняет BrowserDialogEvent в bounded event buffer;
- page не остаётся blocked;
- следующий `browser_events`/snapshot metadata может показать событие.

Нет active caller, который мог бы безопасно принять его.

---

## 12. MCP projection

Чтобы не раздувать core schema, baseline MCP делает `dialog_policy` optional nested field только в tools, где dialog practically возможен/значим:

- `browser_navigate`;
- `browser_click`;
- `browser_press`;
- `browser_fill_form`/`browser_type` по общему BrowserActionOptions mapping, если implementation использует единый input mixin.

Description:

> По умолчанию неожиданные JavaScript-диалоги отклоняются и возвращаются в результате. Укажите `dialog_policy=accept` только если заранее хотите подтвердить диалог, который может появиться из-за этого действия.

Точный schema reuse проверяется на простоту actual FastMCP JSON Schema.

---

## 13. REST projection

REST typed Browser actions могут иметь тот же stable `dialog_policy` object.

Это application concept, не Playwright option leak.

---

## 14. Retry/unknown

Если connection loss произошёл после accept/dismiss и original action мог иметь external side effect:

- ADR-0001 action status recovery используется;
- при недоказуемом result → `unknown`;
- action **не повторяется** только потому, что dialog был default-dismiss.

---

## 15. Security

- default не подтверждает destructive dialogs;
- prompt input bounded;
- page dialog text untrusted;
- no dialog message in trusted progress/log without redaction;
- max dialogs/action;
- asynchronous dialogs auto-dismiss to prevent DoS.

---

## 16. Tests

Required:

1. alert default dismiss;
2. confirm default dismiss;
3. confirm explicit accept;
4. prompt explicit accept with text;
5. invalid prompt_text + dismiss rejected;
6. beforeunload dismiss keeps page;
7. beforeunload accept navigates;
8. async dialog outside action auto-dismiss/event;
9. multiple dialogs bounded;
10. dialog spam limit;
11. action response-loss after dialog follows unknown/status recovery;
12. dialog message treated untrusted/redacted.

---

## 17. Consequences

Плюсы:

- safe default;
- no blocked BrowserSession;
- legitimate confirm/prompt workflows доступны;
- no extra dialog lifecycle/tool;
- semantics одинаковы REST/MCP.

Минусы:

- agent должен предвидеть accept, если confirmation необходима;
- первый default-dismiss attempt иногда придётся повторить сознательно;
- rare workflows, где нужно прочитать dialog до решения, baseline не поддерживает идеально.

Trade-off принимается ради bounded/simple session lifecycle.

---

## 18. Не определяется

- exact field placement/mixin в каждой MCP schema;
- max prompt chars;
- UI rendering dialog events;
- future pending-dialog advanced mode.
