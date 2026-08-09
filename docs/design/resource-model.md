# Модель ресурсов Web Access MCP

## Статус документа

Этот документ является каноническим владельцем **addressable resource model, ownership, opaque handles, lifecycle и provenance relations** проекта.

Он определяет общие свойства `ContentObject`, `BrowserSession`, `Job` и будущих ресурсов.

Точные SQL tables, Redis keys и transport schemas находятся за пределами этого документа.

---

# 1. Что считается Resource

`Resource` — логически адресуемая сущность Web Access, которая:

- имеет стабильную identity;
- имеет owner/principal context;
- имеет lifecycle;
- может переживать один transport request;
- может использоваться последующими application operations через opaque handle/reference.

Основные ресурсы:

```text
ContentObject
BrowserSession
Job
```

Не каждая внутренняя структура является Resource.

Например:

- SearchResult item не обязан иметь отдельный resource handle;
- transient HTTPX response не является Resource;
- Playwright Locator не является публичным Resource.

---

# 2. Общая Resource identity

Каждый addressable Resource получает opaque identifier.

Концептуально:

```text
ResourceRef
├── resource_type
└── resource_id
```

Примеры:

```text
content / cnt_...
browser_session / brs_...
job / job_...
```

Префиксы приведены как читаемый пример и не являются окончательным wire format.

---

# 3. Handle opacity

Public resource identifier:

- не обязан совпадать с database primary key;
- не раскрывает worker identity;
- не раскрывает filesystem path;
- не содержит secret/credential;
- не требует знания внутренней структуры со стороны клиента;
- может безопасно использоваться как stable reference в REST/MCP contract.

Клиент не должен парсить resource identifier для принятия решений.

---

# 4. Знание handle не является authorization

При каждом обращении к Resource Web Access проверяет:

```text
resource exists
+
resource state permits operation
+
principal/owner/policy permits access
```

Opaque/unpredictable ID является defense-in-depth, а не заменой access control.

---

# 5. Общая Resource metadata

Для addressable resources должна быть концептуально доступна общая metadata:

```text
resource_id
resource_type
owner reference
created_at
updated_at/state_changed_at при необходимости
expires_at | null
revision/version при необходимости
lifecycle state
```

Не каждый тип обязан физически хранить одинаковый набор columns.

Общая семантика важнее одинаковой ORM inheritance model.

---

# 6. Owner model

Resource имеет одного канонического owner context или явно определённую ownership policy.

На раннем этапе owner может представлять:

- service/client principal;
- будущего user principal;
- system-owned internal resource.

Модель должна позволять перейти к multi-user системе без замены resource identity/lifecycle contracts.

Точная authentication/authorization schema будет определена security/auth design.

---

# 7. Parent/child resources

Не каждая addressable дочерняя сущность требует отдельной глобальной ownership model.

Например `BrowserPage` может быть session-scoped child:

```text
BrowserSession
└── BrowserPage(s)
```

Page identity действительна только вместе с BrowserSession и наследует её ownership/lifecycle.

При закрытии BrowserSession все child pages перестают быть live resources.

---

# 8. Resource lifecycle и metadata retention различаются

Очень важно различать:

```text
live resource lifetime
```

и

```text
durable metadata/audit retention
```

Например BrowserSession может быть:

```text
closed
```

и уже не иметь BrowserContext, но metadata о её существовании/закрытии может сохраняться некоторое время для:

- audit;
- diagnostics;
- reconciliation;
- idempotent cleanup response.

Удаление live payload/state не обязано мгновенно удалять все durable records.

---

# 9. Terminal Resource state не равен физическому DELETE

Для stateful/durable resources полезно сохранять terminal state:

```text
closed
expired
lost
failed
cancelled
succeeded
```

Физическая очистка metadata выполняется отдельной retention policy.

Это позволяет отличить:

```text
resource никогда не существовал
```

от:

```text
resource существовал и уже expired/closed/lost
```

пока retention window это позволяет.

---

# 10. Idempotent cleanup

Cleanup operation для временного ресурса должна по возможности быть идемпотентной.

Повторный cleanup уже закрытого ресурса не должен случайно превращаться в internal error.

Компонентный design определяет, возвращается ли:

- succeeded + already_closed metadata;
- специальный terminal result;
- другой нормализованный ответ.

Но cleanup не должен создавать новый side effect при повторе.

---

# 11. ContentObject

`ContentObject` является addressable сохранённым representation содержимого.

Примеры:

- raw HTTP body;
- PDF;
- HTML;
- extracted plain text;
- Markdown;
- structured native parse;
- screenshot;
- browser download;
- browser export.

ContentObject представляет **одно конкретное representation**, а не абстрактный «документ со всеми форматами сразу».

---

# 12. Content payload immutability

После успешного создания payload конкретного ContentObject должен считаться immutable.

Если нужно получить другое representation или повторно обработать содержимое:

```text
source ContentObject
→ producer/parser/export
→ новый derived ContentObject
```

Не следует незаметно заменять bytes существующего `content_id` новым результатом.

Это улучшает:

- reproducibility;
- cache correctness;
- provenance;
- debugging;
- безопасное использование hash.

Lifecycle metadata объекта при этом может изменяться независимо от payload.

---

# 13. Raw и Derived Content

## Raw ContentObject

Содержимое, максимально близкое к фактически полученному/созданному source.

Пример:

```text
HTTP GET → raw PDF bytes
```

## Derived ContentObject

Новое representation, произведённое из одного или нескольких source objects.

Пример:

```text
raw PDF
→ native PDF parser
→ plain-text ContentObject
```

или:

```text
Browser Page
→ screenshot export
→ PNG ContentObject
```

---

# 14. Content provenance graph

Derived ContentObject хранит связь происхождения.

Концептуально:

```text
raw PDF ────────┬→ native text
                ├→ native metadata/structure
                └→ external OCR result (если такой processor вызывается другим workflow)
```

Web Access должен позволять восстановить, из какого source representation появился derived object.

---

# 15. Content producer metadata

Для derived representation должна быть доступна provenance information типа:

```text
producer type/name
producer version/revision при необходимости
source content refs
created_at
relevant processing parameters
```

Нельзя полагаться только на human-readable filename для определения происхождения результата.

---

# 16. Content identity и hash

ContentObject может иметь content hash для:

- integrity;
- diagnostics;
- deduplication optimization;
- cache/provenance.

Но hash не обязан быть public resource ID.

Два разных ContentObjects могут иметь одинаковые bytes/hash, если ownership/lifecycle/provenance требуют разных logical records.

Deduplication является infrastructure optimization и не должна случайно объединять ownership domains.

---

# 17. Content storage reference

Application model использует `ContentObject`/`ContentRef`, а concrete storage location скрыта за `ContentStore`.

Внутренне metadata может знать storage key/backend.

Public contract не возвращает:

```text
C:\storage\file.pdf
/mnt/data/...
s3://internal-secret-bucket/...
```

как стабильный handle.

---

# 18. Content representations и media type

ContentObject должен позволять отличать:

- declared media type;
- detected format/media type;
- representation role/kind;
- encoding, если применимо.

Точная schema определяется `content.md`.

URL suffix не является source of truth формата.

---

# 19. Content lifecycle

Предварительно ContentObject может быть:

```text
available
expired
removed
failed (для незавершённого creation lifecycle, если такой record нужен)
```

Точный state machine проектируется в `content.md`/`persistence.md`.

Payload retention и metadata retention могут отличаться.

---

# 20. BrowserSession

`BrowserSession` — addressable stateful remote resource, представляющий managed live browser context.

Она:

- создаётся отдельной application operation;
- имеет opaque `browser_session_id`;
- принадлежит owner/principal;
- маршрутизируется owning Browser Worker;
- существует между несколькими transport calls;
- закрывается явно или server-side lifecycle policy;
- не зависит от MCP connection lifetime.

---

# 21. BrowserSession lifecycle

Канонические lifecycle states на текущем design-уровне:

```text
creating
ready
closing
closed
expired
lost
failed
```

`busy` не фиксируется как обязательный durable lifecycle state: execution serialization может быть отдельным runtime concern.

## Основные transitions

```text
creating → ready
creating → failed
creating → lost

ready → closing
ready → expired
ready → lost

closing → closed
closing → lost
```

Дополнительные transitions требуют Browser design update.

---

# 22. `lost` отличается от `closed`

`closed` означает штатно завершённый live resource.

`lost` означает, что Web Access больше не располагает исходным live browser state и не может доказать корректное штатное закрытие/восстановление.

Пример:

```text
owning Browser Worker process погиб
→ BrowserContext исчез
→ BrowserSession = lost
```

Система не должна автоматически создавать новый context и выдавать его за ту же live session.

---

# 23. BrowserSession ownership worker

Live BrowserSession в один момент времени имеет одного active owning Browser Worker.

Routing metadata может храниться вне worker, но фактические Playwright objects находятся у owner.

Будущий fencing/lease mechanism может усиливать правило single active owner; точный protocol определяется Browser design/ADR.

---

# 24. BrowserSession revision

Mutable BrowserSession должна иметь возможность поддерживать монотонную `revision`/state version.

Revision может использоваться для:

- stale-action detection;
- optimistic concurrency;
- snapshot/action consistency;
- diagnostics.

Точный requirement `expected_revision` для browser actions будет решён в `browser.md`.

Сам факт наличия versionable mutable state считается частью resource model.

---

# 25. BrowserPage

BrowserPage является session-scoped child identity.

Требования:

- `page_id` opaque для клиента;
- действует только в пределах BrowserSession;
- ownership наследуется от session;
- закрытие session invalidates live pages;
- page handle не раскрывает Playwright/CDP internal identifier как contract.

Нужна ли durable persistence page metadata, решается Browser design.

---

# 26. Browser output как ContentObject

Крупные browser-generated artifacts не должны жить только внутри Browser Worker.

Примеры:

- screenshot;
- downloaded file;
- exported PDF;
- rendered HTML snapshot, если сохраняется как large content.

Они переносятся через Content application/storage boundary и получают ContentObject identity.

BrowserSession может закрыться после того, как ContentObject уже безопасно сохранён.

---

# 27. Browser downloads

Временный download внутри Playwright runtime не считается долговечным application resource.

До cleanup BrowserSession нужный download должен быть:

```text
validated
→ перенесён в ContentStore
→ зарегистрирован как ContentObject
```

или явно discarded.

Клиент не получает browser-worker local path.

---

# 28. Job

`Job` — durable resource, представляющий background/long-running application work.

Job имеет:

- opaque `job_id`;
- owner/principal;
- job type;
- durable lifecycle state;
- input/reference metadata;
- progress/events при необходимости;
- terminal result/error;
- links/refs на ContentObjects или другие outputs.

---

# 29. Job lifecycle

Предварительный общий state set:

```text
created
queued
running
cancelling
succeeded
failed
cancelled
expired
```

Необходимость состояний `interrupted`, `lost`, retry-attempt states и точные transitions будут определены `jobs.md`.

Terminal result Job не должен зависеть от того, жив ли первоначальный REST/MCP request.

---

# 30. Job result references

Большой Job result должен ссылаться на ContentObject(s), а не безусловно храниться огромным JSON payload в Job row.

Job metadata может содержать небольшой structured summary/manifest.

---

# 31. Job attempts

Job identity и execution attempt identity разделяются.

```text
Job
├── attempt 1 → operation_id A
├── attempt 2 → operation_id B
└── terminal result
```

Это позволяет retry durable work без смены `job_id` при сохранении audit trail.

Точный attempt model проектируется в `jobs.md`/`persistence.md`.

---

# 32. Resource references в OperationResult

Application operation может вернуть lightweight reference вместо inline resource data.

Пример:

```json
{
  "resource_type": "content",
  "resource_id": "cnt_..."
}
```

REST/MCP могут оборачивать reference удобной transport metadata, но logical identity одна.

---

# 33. Resource creation и OperationResult

Создание resource является обычной Operation.

Пример:

```text
browser_session_create Operation
→ outcome = succeeded
→ data = BrowserSessionRef
```

или:

```text
start durable crawl Operation
→ outcome = succeeded
→ data = JobRef
```

Для этого не требуется отдельный общий outcome `accepted`, если component design не покажет реальную необходимость.

---

# 34. Resource conflict/concurrency

Mutable resources должны иметь определённую concurrency model.

В зависимости от типа это может быть:

- single writer;
- optimistic revision check;
- lock/lease;
- serial action queue.

Нельзя оставлять concurrency semantics implicit.

Конкретные правила принадлежат `browser.md`, `jobs.md`, `content.md`.

---

# 35. Expiration

`expires_at` применяется только к ресурсам, для которых expiration имеет смысл.

Expiration означает application lifecycle event, а не просто TTL Redis key.

При expiration должны быть определены:

- terminal state;
- cleanup behavior;
- response последующего доступа;
- metadata retention.

Redis TTL может помогать implementation, но не должен быть единственным источником истины durable expiration, если это противоречит resource semantics.

---

# 36. Retention policy

Каждый resource type должен иметь определяемую policy для:

- live payload retention;
- terminal metadata retention;
- logs/audit references;
- derived content cleanup;
- orphan reconciliation.

Точные сроки не фиксируются здесь и должны быть configurable/обоснованы component design.

---

# 37. Resource deletion

Физическое удаление и logical lifecycle transition различаются.

Например ContentObject может сначала стать `expired`, затем payload удаляется, затем metadata record очищается позже.

API/MCP contract не должен обещать мгновенное физическое уничтожение во всех storage replicas, если architecture не обеспечивает такую гарантию.

Security-sensitive erase requirements, если появятся, проектируются отдельно.

---

# 38. Orphan resources

Система должна предполагать возможность orphan state из-за crash между несколькими infrastructure steps.

Примеры:

- Content bytes записаны, metadata transaction не commit;
- BrowserSession metadata создана, worker context не создан;
- Job durable row создан, enqueue не произошёл.

Persistence/component design обязан предусмотреть reconciliation/cleanup, а не считать такие окна невозможными.

---

# 39. Resource events

Для lifecycle-aware resources может быть полезен event/audit trail:

```text
created
state_changed
expired
closed
lost
cleanup_failed
```

Не каждый event обязан становиться отдельной event-sourcing системой.

Нужно различать:

- authoritative current state;
- durable audit events;
- transient telemetry.

Точная модель определяется persistence/observability/component design.

---

# 40. Resource model не требует shared base ORM class

Общие semantic concepts не означают, что все resources должны наследовать одну огромную SQLAlchemy table/class hierarchy.

Persistence schema проектируется по access patterns и lifecycle каждого resource.

Unified application semantics не должна приводить к искусственной database inheritance.

---

# 41. Cross-owner deduplication запрещено делать неявно

Content deduplication по hash не должна случайно давать одному principal доступ к object другого principal.

Infrastructure может физически дедуплицировать bytes, но logical ContentObject ownership/access остаются разделёнными.

---

# 42. Capability handles остаются сервисными

Web Access не должен принимать внешний произвольный handle и интерпретировать его как внутренний resource без явного import/registration contract.

Opaque handles валидируются только в namespace/type, которым владеет сервис.

---

# 43. Resource model и transport

REST может предоставлять:

- resource URLs;
- metadata endpoints;
- richer lifecycle status.

MCP может предоставлять:

- compact opaque handles;
- agent-facing summary;
- lifecycle hints.

Но transport projections ссылаются на один canonical Resource identity.

---

# 44. Acceptance criteria resource foundation

При реализации resource foundation должны существовать tests, подтверждающие:

1. Resource ID opaque и не требует parsing клиентом.
2. Знание handle без owner/policy не даёт доступ.
3. BrowserSession не закрывается из-за transport disconnect.
4. Browser Worker loss переводит session в `lost`, а не создаёт «тихую новую» session.
5. Повторный cleanup terminal BrowserSession безопасен.
6. Content payload immutable после создания.
7. Derived ContentObject хранит source provenance.
8. ContentStore local path не протекает в public result.
9. Job identity не меняется между execution attempts.
10. Большой Job/browser result может ссылаться на ContentObject.
11. Expiration отражается application state, а не существует только как Redis TTL.
12. Terminal metadata может переживать live payload cleanup согласно retention policy.
13. Cross-owner content deduplication не нарушает isolation.

---

# 45. Open questions

До component implementation необходимо закрыть:

1. Точную Principal/Owner data model.
2. Точный public ResourceRef wire shape.
3. Нужна ли отдельная grouping identity для нескольких representations одного logical source помимо provenance graph.
4. Точный ContentObject lifecycle state machine.
5. Обязательна ли BrowserSession `revision` во всех mutating actions или только в отдельных режимах.
6. Нужны ли durable BrowserPage records.
7. Точный Job lifecycle/attempt model.
8. Retention policies по типам resources.
9. Нужен ли отдельный tombstone record после полного удаления resource metadata.

Эти вопросы не отменяют уже зафиксированные invariants ownership, opacity, lifecycle independence, provenance и content immutability.
