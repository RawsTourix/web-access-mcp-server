# Общие application contracts Web Access MCP

## Статус документа

Этот документ является каноническим владельцем **общей модели выполнения application operations**.

Он определяет сквозные contracts, которыми должны пользоваться Search, Retrieval, Content, Browser, Jobs, REST и MCP.

Компонентные документы могут добавлять собственные inputs/results/errors, но не должны создавать несовместимые модели operation identity, outcome, batch semantics, hints, warnings, deadline/cancellation и retry.

---

# 1. Основная единица выполнения — Operation

`Operation` — один логически завершённый вызов application capability.

Примеры:

- выполнить один batch Search;
- получить batch известных URL;
- выполнить Content Inspection;
- создать BrowserSession;
- выполнить один browser action;
- закрыть BrowserSession;
- создать durable Job;
- запросить Job cancellation.

Operation не равна:

- HTTP request;
- MCP connection;
- durable Job;
- database transaction;
- worker process.

Один transport request обычно инициирует одну application Operation, но architecture не должна зависеть от этого как от жёсткого правила.

---

# 2. Operation identity

Каждая application Operation получает уникальный `operation_id`.

Требования:

- генерируется на application boundary или передаётся trusted execution context;
- не зависит от REST/MCP transport connection;
- не переиспользуется для отдельного нового execution attempt;
- пригоден для logs, tracing, diagnostics и provenance;
- не обязан быть durable database row для каждой короткой операции.

`operation_id` не является `job_id`.

Если Job исполняется несколькими attempts, каждый execution attempt может иметь собственный `operation_id`, а `job_id` остаётся identity durable Job resource.

---

# 3. Correlation identity

Помимо `operation_id` система может использовать `correlation_id`/trace context для связывания цепочки нескольких operations.

Например:

```text
MCP call
→ Search operation
→ несколько provider HTTP calls
```

или:

```text
REST call
→ Browser operation
→ Browser Worker action
→ ContentObject creation
```

Correlation identity не заменяет identity конкретной Operation.

---

# 4. ExecutionContext

Каждая Application Operation получает общий execution context.

Концептуально:

```text
ExecutionContext
├── operation_id
├── correlation / trace context
├── principal context
├── owner context, если применимо
├── deadline
├── cancellation context
├── idempotency context, если поддерживается операцией
└── policy context
```

Точная Python-модель будет определена implementation design, но семантика полей является общей.

---

# 5. PrincipalContext

`PrincipalContext` описывает субъект, от имени которого выполняется операция.

На ранних версиях principal model может быть минимальной, но contract должен позволять дальнейшее расширение до multi-user режима.

Application code не должен извлекать principal напрямую из FastAPI/FastMCP objects.

Transport adapter формирует trusted PrincipalContext и передаёт его application layer.

---

# 6. OwnerContext

OwnerContext используется, когда операция создаёт или обращается к addressable resource.

Ресурс не становится доступным только по знанию handle.

Application layer должен иметь возможность проверить:

```text
principal
+
resource owner
+
policy
```

Точная owner model определяется `resource-model.md`.

---

# 7. Deadline

Deadline является сквозным ограничением времени операции.

Внешний transport может задавать deadline/timeout policy, но application layer работает с нормализованным deadline/budget.

Deadline должен по возможности передаваться:

```text
Transport
→ Application
→ Provider / HTTP Retrieval / Browser Worker
```

Нельзя запускать downstream request с timeout, который заведомо превышает оставшийся application deadline без отдельной причины.

---

# 8. Cancellation

Cancellation является cooperative contract, а не гарантией мгновенного прекращения внешнего side effect.

Нужно различать:

- cancellation requested;
- execution фактически остановлен до side effect;
- execution завершился несмотря на cancellation;
- side effect outcome неизвестен.

Terminal outcome `cancelled` допустим только когда система может корректно утверждать, что operation завершена как отменённая согласно её semantics.

Если mutating action мог выполниться, но подтверждение потеряно, используется `unknown`, а не ложный `cancelled`.

---

# 9. OperationOutcome

Канонические общие outcomes:

```text
succeeded
partial_success
failed
rejected
cancelled
unknown
```

## `succeeded`

Operation выполнена согласно contract.

Warning/hint не меняет succeeded в failed.

## `partial_success`

Применяется на aggregate уровне для batch/composite operation, когда хотя бы один независимый item успешен, а хотя бы один имеет другой terminal outcome.

## `failed`

Operation не выполнена из-за execution/upstream/infrastructure failure и система уверена в итоговом состоянии настолько, чтобы не использовать `unknown`.

## `rejected`

Operation не была принята к выполнению из-за validation, policy, permission, unsupported capability или другого precondition rejection.

`rejected` отделяется от execution failure.

## `cancelled`

Operation корректно завершена как отменённая.

## `unknown`

Система не может достоверно определить terminal effect/outcome.

Особенно важно для mutating Browser actions и других side-effecting operations после transport/runtime failure.

---

# 10. Outcome и Error — разные понятия

Outcome описывает итог операции.

`OperationError` описывает причину/класс проблемы.

Например:

```text
outcome = rejected
error.code = validation_error
```

или:

```text
outcome = failed
error.code = upstream_unavailable
```

или:

```text
outcome = unknown
error.code = response_lost_after_dispatch
```

Нельзя выводить retry policy только из error code без учёта operation semantics/outcome.

---

# 11. OperationResult

Концептуальная общая модель:

```text
OperationResult[T]
├── operation_id
├── outcome
├── data: T | null
├── error: OperationError | null
├── warnings[]
├── hints[]
└── execution metadata
```

Component result может содержать дополнительные typed metadata/provenance.

Public contract не должен превращаться в один бесконтрольный `dict[str, Any]` только ради универсальности.

---

# 12. Result invariants

## Succeeded

```text
outcome = succeeded
error = null
```

`data` присутствует, если operation contract предполагает данные.

## Rejected/Failed/Cancelled/Unknown

Для terminal non-success outcome должен присутствовать нормализованный error/reason, если отсутствие error не является частью отдельного documented contract.

## Partial Success

Aggregate result содержит batch data/items и aggregate metadata. Ошибки отдельных items принадлежат item results, а не теряются в одном общем message.

---

# 13. OperationError

Общая error model должна содержать как минимум концептуальные поля:

```text
code
category
message
retryable/disposition metadata
safe details
```

Технический exception/stack trace не является public error contract.

### `code`

Стабильный machine-readable identifier на английском.

### `message`

Понятное человеку/LLM объяснение. Основной язык проекта — русский.

### `details`

Только безопасные структурированные данные, необходимые для исправления вызова или диагностики клиентом.

Secrets, stack traces, внутренние addresses/paths не возвращаются.

---

# 14. Базовые error categories

Компоненты могут вводить более точные codes, но должны маппиться на устойчивые общие категории.

Предварительный набор:

```text
validation
policy
permission
authentication
not_found
expired
conflict
unsupported
rate_limited
capacity
upstream
timeout
infrastructure
resource_lost
cancelled
unknown_outcome
internal
```

Точные code namespaces будут уточняться компонентами.

REST и MCP должны сериализовать одну application taxonomy, а не изобретать разные значения для одной причины.

---

# 15. Validation errors должны быть repairable

Если input некорректен, ошибка должна позволять клиенту/LLM понять, что исправить.

Предпочтительная структура details:

```json
{
  "field": "urls[2]",
  "code": "invalid_scheme",
  "message": "Разрешены только HTTP(S) URL."
}
```

Для нескольких независимых validation issues допускается массив деталей.

Нельзя ограничиваться строкой вида:

```text
invalid input
```

если можно предоставить более точную безопасную причину.

---

# 16. Warning

Warning сообщает значимое ограничение или аномалию текущего результата, но не требует считать operation неуспешной.

Концептуально:

```text
Warning
├── code
├── message
└── details
```

Примеры:

- часть metadata отсутствует;
- server response объявил один MIME, а inspection определил другой;
- content representation была усечена согласно явному limit;
- provider вернул нестандартный response, который удалось нормализовать.

Warning не является рекомендацией следующего действия.

---

# 17. StructuredHint

Hint предлагает возможный следующий шаг.

Концептуально:

```text
StructuredHint
├── code
├── message / reason
├── related_capability | null
└── safe context | null
```

Пример:

```json
{
  "code": "browser_may_be_required",
  "message": "Полученный HTML содержит минимальное статическое содержимое.",
  "related_capability": "browser"
}
```

Hint:

- не является error;
- не меняет outcome;
- не инициирует следующий operation;
- не является web-content instruction;
- генерируется trusted application logic.

---

# 18. Hints о внешних capabilities

Если следующий шаг находится за границей Web Access, hint должен быть нейтральным.

Предпочтительно:

```text
advanced_processing_may_be_required
native_text_unavailable
unsupported_native_format
```

Вместо:

```text
use_liteparse
use_libreoffice
```

если конкретный внешний processor не является частью deployment/application contract.

---

# 19. Provenance references

Application result может ссылаться на provenance без обязательного встраивания полного provenance graph в каждый response.

Общий principle:

- URL/provider origin не теряется;
- Content derived representation знает source ContentObject;
- parser/producer revision может быть восстановлен;
- Browser-produced Content знает browser/session/page origin настолько, насколько это нужно для audit/reproducibility.

Каноническая resource/provenance model определяется `resource-model.md`.

---

# 20. Execution metadata

Общая execution metadata может включать:

- started/completed timestamps;
- duration;
- attempt information;
- cache/freshness marker, если применимо;
- worker/provider reference в безопасной форме;
- trace/correlation reference.

Не все поля обязаны публично сериализоваться каждым transport.

REST может предоставлять более полную operational metadata, чем MCP.

---

# 21. Batch-first semantics

Для естественно независимых операций batch является canonical input form.

Требования:

1. input list непустой;
2. каждый item имеет стабильный index;
3. при необходимости клиент может передать собственный `item_id`, если это будет зафиксировано конкретным contract;
4. порядок result items сохраняет соответствие input order;
5. ошибка одного item не уничтожает результаты других независимых items;
6. каждый item имеет собственный outcome/error;
7. aggregate result содержит summary counts/aggregate outcome.

---

# 22. BatchItemOutcome

Отдельный независимый item использует terminal outcomes:

```text
succeeded
failed
rejected
cancelled
unknown
```

`partial_success` не используется для простого leaf item, если сам item не является отдельным composite result по своему contract.

---

# 23. Aggregate batch outcome

Канонический алгоритм:

1. Все items `succeeded` → `succeeded`.
2. Есть хотя бы один `succeeded` и хотя бы один другой terminal outcome → `partial_success`.
3. Нет `succeeded`, но есть хотя бы один `unknown` → `unknown`.
4. Все items `rejected` → `rejected`.
5. Все items `cancelled` → `cancelled`.
6. Остальные combinations без успешных items → `failed`.

Per-item outcomes остаются source of truth для точной причины.

---

# 24. Batch concurrency не является public semantics

Client задаёт logical batch, а infrastructure может исполнять items последовательно или параллельно в пределах policy.

Нельзя обещать конкретный internal concurrency только потому, что input является списком.

Если клиенту действительно нужен control над concurrency, это должно быть отдельным application requirement, а не случайным infrastructure parameter.

---

# 25. Retry semantics

Каждая operation должна иметь execution semantics, определяющую допустимость автоматического retry.

Предварительные классы:

```text
safe_retry
idempotent_retry
never_automatic
```

## `safe_retry`

Operation не создаёт side effect, а повтор после transient failure безопасен при соблюдении deadline/policy.

Примеры-кандидаты:

- Search;
- Retrieval GET;
- Content read/inspection.

Точный retry всё равно зависит от failure stage/code.

## `idempotent_retry`

Повтор допустим только при гарантированном idempotency contract, например со стабильным idempotency key.

## `never_automatic`

Blind automatic retry запрещён после того, как operation могла быть dispatched/executed.

Пример-кандидат — browser click, способный вызвать внешний side effect.

---

# 26. Idempotency key

Idempotency key не является обязательным для каждой operation.

Если конкретная operation поддерживает idempotency:

- key должен быть scoped по principal + operation semantics;
- duplicate request должен иметь документированное поведение;
- retention idempotency records должна быть определена;
- одинаковый key с несовместимым payload должен приводить к conflict/rejection;
- transport не должен придумывать новый key при retry, если смысл idempotency требует стабильного значения.

Точный механизм определяется компонентным design.

---

# 27. Unknown outcome

`unknown` — обязательная часть модели, а не edge-case логирования.

Пример:

```text
Browser click отправлен owning worker
→ click мог выполниться
→ transport response потерян
```

Неправильно:

```text
connection_error → retry click
```

Правильно:

```text
outcome = unknown
→ вернуть безопасную diagnostic информацию
→ клиент может выполнить read-only verification (например snapshot)
```

---

# 28. Retry должен учитывать execution stage

Даже safe operation не следует бездумно повторять при любом exception.

Failure model по возможности должен различать stages вроде:

```text
before_dispatch
after_dispatch
executing
response_lost
```

Не все stages обязаны публично сериализоваться, но execution layer должен иметь достаточно информации для корректной retry decision.

---

# 29. Rejection до side effect

Validation/policy/permission rejection должен происходить максимально рано, до внешнего side effect.

Если rejection действительно произошёл pre-dispatch, outcome `rejected` даёт клиенту более сильную гарантию, чем generic `failed`.

---

# 30. Request-bound и durable operation

## Request-bound

Результат ожидается в рамках текущего request.

Client disconnect/deadline может привести к cooperative cancellation.

## Durable Job

Создание Job является отдельной request-bound operation, возвращающей Job handle.

Сам Job продолжает жить независимо от transport connection.

Job lifecycle определяется `jobs.md` и `resource-model.md`.

---

# 31. Operation result не должен быть бесконечно большим

Application contract должен позволять вместо огромного inline payload вернуть ContentObject/resource reference.

Особенно это важно для:

- HTML;
- PDF;
- screenshots;
- downloads;
- large extracted text;
- crawl results.

Inline preview/summary и durable content representation должны быть различимы.

Точные thresholds/limits не фиксируются этим документом.

---

# 32. Content/reference semantics не зависят от transport

Если application operation возвращает ContentReference, REST и MCP сериализуют одну и ту же logical identity разными удобными формами, но не создают собственные независимые storage handles.

---

# 33. Cache semantics

Cache является infrastructure optimization, но application result не должен скрывать значимую freshness информацию, когда актуальность важна для смысла операции.

Конкретный Search/Retrieval component design определяет:

- cacheability;
- freshness metadata;
- bypass/refresh semantics, если они нужны клиенту;
- invalidation/TTL policy.

Запрещено возвращать произвольно старый cache как «свежий» result без соответствующей semantics.

---

# 34. Transport mapping

REST и MCP могут по-разному представлять один OperationResult.

REST может отдавать:

- HTTP status mapping;
- полный structured error;
- operational metadata;
- richer resource links.

MCP может отдавать:

- компактный agent-facing envelope;
- русскоязычный message;
- structured repairable error;
- hints;
- content handles.

Но canonical outcome/error code должен происходить из application result.

---

# 35. Human-readable язык и machine-readable codes

Stable identifiers используются на английском:

```text
browser_may_be_required
validation_error
resource_lost
unknown_outcome
```

Human-readable messages для основного agent-facing/runtime contract проекта преимущественно пишутся на русском.

Это позволяет сохранять удобство сопровождения без потери стабильности protocol codes.

---

# 36. Public details должны быть безопасными

OperationResult не возвращает:

- stack trace;
- secrets;
- DB credentials;
- internal Redis keys;
- local filesystem paths;
- worker private addresses;
- raw library exceptions.

Подробная техническая причина может попадать в logs/traces с redaction policy.

---

# 37. Application contracts не зависят от FastAPI/FastMCP

Ни одна общая сущность этого документа не должна требовать import transport framework.

Transport-specific request/context преобразуются в ExecutionContext и typed application input через mapper/dependency layer.

---

# 38. Component extension rules

Search/Retrieval/Content/Browser/Jobs могут добавлять:

- собственные result data models;
- собственные error codes;
- собственные structured hints;
- дополнительные execution metadata;
- resource handles.

Они не могут переопределять:

- смысл `operation_id`;
- базовые outcomes;
- aggregate batch algorithm;
- separation warning/hint/error;
- unknown-outcome invariant;
- transport independence.

---

# 39. Acceptance criteria общего application contract

При реализации foundation должны существовать tests, подтверждающие как минимум:

1. `operation_id` создаётся для каждой application operation.
2. Result outcome соответствует заданным invariants.
3. `succeeded` не содержит primary error.
4. Batch сохраняет input order.
5. Один failed batch item не уничтожает successful siblings.
6. Aggregate outcome вычисляется детерминированно.
7. Structured Hint не меняет outcome.
8. Warning и Hint различаются в schema.
9. Validation error содержит repairable field details.
10. `unknown` не преобразуется автоматически в retry.
11. Transport adapters не возвращают raw infrastructure exception.
12. Deadline/cancellation context проходит в downstream ports, которые его поддерживают.
13. Огромный result может быть вынесен в resource/content reference без смены operation semantics.

---

# 40. Open questions

На этом этапе намеренно остаются открытыми:

1. Точный Python representation `OperationResult` — generic dataclass/Pydantic model/discriminated union.
2. Точная Principal/Owner model до design авторизации.
3. Полная error code taxonomy по компонентам.
4. Универсальный public формат provenance references.
5. Нужен ли обязательный client-supplied `item_id` в batch или достаточно input index.
6. Нужен ли отдельный `accepted` outcome для async Job creation или `succeeded + Job handle` достаточно.
7. Точные idempotency-key requirements для будущих mutating REST operations.

Эти вопросы должны закрываться до соответствующего implementation patch, но не мешают проектировать resource/persistence/component model поверх уже принятых общих semantics.
