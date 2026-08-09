# ADR-0001 — Browser Worker transport: direct internal HTTP/RPC

**Статус:** accepted

## 1. Контекст

BrowserSession является stateful resource и принадлежит одному active Browser Worker.

Control Plane должен отправлять каждую browser operation **конкретному owning worker**, сохранять низкую latency, поддерживать cancellation/action status recovery и не выполнять mutating action повторно после неопределённого transport failure.

Одновременно Browser Worker является повышенной security boundary: он исполняет недоверенный JavaScript и не должен без необходимости получать PostgreSQL/Redis/ContentStore credentials.

---

## 2. Требования

Internal transport должен поддерживать:

1. targeted delivery конкретному worker;
2. `action_id` correlation/deduplication;
3. deadline propagation;
4. cancellation;
5. bounded request/response;
6. worker generation validation;
7. session ownership validation;
8. service authentication;
9. backpressure/capacity;
10. recovery terminal action result после потери initial response;
11. различение failure до принятия command и неопределённого состояния после dispatch;
12. graceful worker drain;
13. horizontal API/Browser Worker scaling;
14. streaming transfer browser artifacts без передачи local paths.

---

## 3. Рассмотренные варианты

### A. Direct internal HTTP/RPC

```text
Control Plane
→ resolve owner
→ HTTP/RPC directly to Browser Worker
→ result
```

Redis используется для registry/coordination, но не является транспортом каждого action.

### B. Redis Streams / worker mailbox

```text
Control Plane
→ Redis stream/mailbox конкретного worker
→ worker consumer
→ response stream/mailbox
```

### C. Общая Redis/arq queue

Browser action публикуется в обычную shared task queue и один из workers получает message.

---

## 4. Решение

Принимается вариант **A — direct internal HTTP/RPC**.

Canonical action flow:

```text
Client
→ API replica
→ validate BrowserSession
→ resolve owning worker/generation from shared registry
→ direct authenticated HTTP/RPC command owning worker
→ Browser Worker validates session + generation + action_id
→ execute serialized action
→ return terminal result
→ API maps result to Application/REST/MCP
```

Redis остаётся:

- registry/heartbeat/lease/coordination backend;
- optional cache/control plane accelerator;

но **не является основным transport bus browser actions**.

---

## 5. Почему direct RPC

Browser actions обычно request-bound и интерактивны.

Для них важны:

- низкая latency;
- session affinity;
- immediate response;
- explicit cancellation;
- понятная transport failure boundary;
- возможность запросить status конкретного `action_id`.

Direct RPC выражает эти свойства естественнее общей durable queue.

---

## 6. Почему не Redis Streams

Redis Streams технически способен реализовать mailbox, но требует дополнительного protocol для:

- targeted routing;
- request/response correlation;
- response retention;
- cancellation;
- stale worker generations;
- per-session ordering;
- duplicate messages;
- backpressure;
- cleanup response streams;
- artifact transfer.

При этом Redis становится обязательной data plane dependency **каждого** browser action.

Для интерактивной stateful session это добавляет больше distributed-systems complexity, чем решает.

Streams могут остаться кандидатом для telemetry/events, но не основным action transport.

---

## 7. Почему не arq/shared queue

Shared arq queue не выражает естественно:

```text
этот command обязан попасть именно worker X, владеющему BrowserContext Y
```

Добавление custom routing/mailboxes поверх arq фактически создаёт отдельный protocol внутри queue framework.

Кроме того, browser action не является durable background Job.

Следовательно Jobs и Browser actions используют разные execution paths.

---

## 8. Worker registration

Browser Worker не должен иметь PostgreSQL credentials только ради регистрации.

Предпочтительный flow:

```text
Browser Worker
→ authenticated internal registration/heartbeat API Control Plane
→ Control Plane
→ shared registry/Redis
```

Worker сообщает безопасную metadata:

- worker_id;
- generation;
- advertised internal endpoint;
- ready/draining state;
- capacity;
- browser/runtime/profile revision.

Control Plane валидирует service identity и допустимость endpoint.

---

## 9. Worker identity/generation

Каждый Browser Worker process startup получает новую generation.

Routing entry:

```text
worker_id + generation + endpoint + lease/heartbeat
```

BrowserSession owner metadata фиксирует generation, на которой создан live BrowserContext.

Restart того же logical worker identity с новой generation **не наследует** старые sessions.

---

## 10. Session ownership validation

Каждый internal command содержит минимум:

```text
session_id
action_id
expected_worker_id
expected_worker_generation
session ownership token/revision, если он будет введён final protocol
operation/deadline context
typed command
```

Worker проверяет, что session действительно существует у него и принадлежит текущей generation.

Нельзя выполнить command только потому, что caller знает `session_id`.

---

## 11. Action endpoint model

Exact URL paths не являются application contract, но internal protocol conceptually предоставляет:

```text
execute action
get action status/result
cancel action
fetch temporary artifact
health/capacity
```

Например реализация может выглядеть как:

```text
POST /internal/v1/sessions/{session_id}/actions
GET  /internal/v1/sessions/{session_id}/actions/{action_id}
POST /internal/v1/sessions/{session_id}/actions/{action_id}/cancel
GET  /internal/v1/artifacts/{artifact_id}
```

Конкретные names фиксируются implementation plan, не public REST/MCP.

---

## 12. Response-loss recovery

Direct RPC позволяет существенно усилить `unknown outcome` semantics.

Если initial action response потерян:

```text
Control Plane
→ НЕ повторяет action
→ запрашивает action status/result по тому же action_id
```

Возможны исходы:

### Terminal result найден

Возвращается первоначальный result без повторного исполнения.

### Action ещё running

Control Plane может bounded дождаться/повторно проверить до application deadline.

### Worker недоступен / ledger потерян

Если action мог выполниться:

```text
outcome = unknown
```

Blind retry запрещён.

---

## 13. Worker action ledger

Browser Worker хранит bounded session-scoped ledger recent `action_id`.

Ledger содержит достаточно данных для:

- duplicate detection;
- current status;
- terminal result replay;
- payload hash/conflict detection.

Ledger живёт не дольше BrowserSession/необходимого bounded retention.

Он не обязан быть глобально durable: если worker погиб вместе с session state, session всё равно становится `lost`.

---

## 14. Cancellation

HTTP client disconnect сам по себе не считается надёжным cancellation signal.

Control Plane использует explicit cancel command по `action_id`, если application cancellation requested.

Worker cooperative-cancel Playwright task.

Если action мог создать side effect, итог может остаться `unknown`.

---

## 15. Session-level ordering

Worker не полагается на порядок поступления параллельных HTTP connections.

Все commands BrowserSession проходят внутреннюю serial queue/lock.

`action_id` и session sequence/revision используются для diagnostics/stale checks.

---

## 16. Registry и lease

Redis/shared registry сообщает, доступен ли worker для новых/существующих commands.

Important design decision:

> BrowserSession **не переносится на нового worker после потери owner**.

Следовательно lease используется для обнаружения availability/loss, а не для автоматического failover live BrowserContext.

Это существенно упрощает fencing: система не пытается иметь двух конкурирующих owners одной live session.

---

## 17. Transient heartbeat loss

Краткая потеря heartbeat не обязана мгновенно переводить все sessions в `lost`.

Нужен grace/lease expiry interval.

Пока owner считается temporarily unavailable:

- новые actions могут возвращать worker unavailable/retryable error;
- session не reassigned;
- если та же generation восстанавливает heartbeat до final loss decision, session может продолжить работу.

После подтверждённого loss/grace expiry session → `lost` и больше не resurrected.

---

## 18. Service authentication

Worker internal RPC принимает только Control Plane service identity.

Baseline может использовать отдельный scoped bearer/service token; production может перейти на mTLS/workload identity без изменения Browser application contract.

Internal network location сама по себе недостаточна.

---

## 19. Least privilege Browser Worker

Принято направление:

> Browser Worker не получает прямой PostgreSQL/Redis/ContentStore credential, если implementation не докажет необходимость.

Предпочтительно он знает только:

- Control Plane internal registration endpoint/credential;
- собственный internal RPC credential/config;
- Browser config;
- public internet egress.

Это уменьшает impact вредоносной страницы/browser sandbox escape.

---

## 20. Artifact transfer

Screenshot/download/rendered artifact сначала существует как temporary worker artifact.

Worker возвращает **internal opaque artifact handle**, а не local path.

Control Plane:

```text
GET/stream artifact owning worker
→ ContentApplicationService ingest
→ ContentObject
→ acknowledge/cleanup worker temp artifact
```

Large bytes не обязаны находиться в JSON action response.

---

## 21. Почему artifact идёт через Control Plane

Это позволяет Browser Worker не иметь ContentStore credentials и гарантирует, что:

- ownership назначает trusted application layer;
- Content inspection/security единообразны;
- filesystem/S3 backend скрыт от Browser Worker;
- horizontal deployment не зависит от shared local path.

Trade-off — дополнительный internal streaming hop.

Он принимается ради security/architecture simplicity; performance проверяется load tests.

Если измерения покажут bottleneck, можно добавить scoped direct staging adapter отдельным ADR без изменения public Browser contract.

---

## 22. Backpressure

Worker internal endpoint обязан bounded отклонять commands при:

- draining;
- session queue overflow;
- global worker pressure;
- incompatible generation/profile.

Control Plane не создаёт unbounded client queues поверх перегруженного worker.

---

## 23. Timeout/deadline

Control Plane передаёт absolute/normalized deadline или remaining budget.

Internal HTTP timeout должен быть немного согласован с application deadline и оставлять время для:

- status recovery;
- result mapping;
- cleanup.

Proxy/network timeout не должен быть единственным источником action deadline.

---

## 24. Internal API framework

Browser Worker internal RPC может быть реализован через lightweight FastAPI/ASGI app или другой typed async HTTP framework.

Выбор конкретного framework не является существенным ADR, если сохраняются:

- Pydantic/typed protocol;
- async streaming;
- cancellation/status endpoints;
- service auth;
- bounded concurrency.

Использование FastAPI допустимо ради общего Python stack.

---

## 25. Observability

Trace context передаётся direct RPC.

Control Plane/Worker spans позволяют разделить:

```text
routing
network
session queue wait
target resolution
actionability
action
artifact transfer
```

Internal action_id/worker generation присутствуют в structured logs, но не metric labels.

---

## 26. Failure model

### До dispatch/connection

Если Control Plane доказуемо не доставил command — retry согласно operation semantics/deadline возможен.

### Worker rejected до execution

Structured rejection возвращается как application error.

### Worker accepted, response lost

Status recovery по action_id.

### Worker lost после возможного execution

`unknown` для mutating action.

### Worker generation mismatch

Rejected/stale owner; BrowserSession reconciles в lost/unavailable согласно current lifecycle state.

---

## 27. Consequences — плюсы

- минимальная latency browser actions;
- естественная affinity;
- понятный cancellation/status protocol;
- сильная `unknown outcome` handling;
- Redis не находится в data path каждого action;
- Browser Worker можно лишить DB/Redis/ContentStore secrets;
- проще bounded backpressure;
- легче trace request across worker;
- Browser и Jobs остаются разными execution models.

---

## 28. Consequences — минусы

- Control Plane должен уметь сетево достигать каждого Browser Worker;
- worker должен рекламировать routable internal endpoint;
- orchestration/networking сложнее, чем одна общая queue;
- API replica временно зависит от доступности конкретного owning worker;
- artifact transfer через Control Plane создаёт дополнительный bandwidth hop;
- нужен собственный internal RPC protocol/status ledger.

Эти trade-offs принимаются как более предсказуемые, чем mailbox/action-bus complexity Redis Streams.

---

## 29. Не определяется этим ADR

Отдельно остаются:

- exact worker registry Redis schema;
- heartbeat/lease durations;
- exact session ownership token/fencing fields;
- exact internal endpoint paths;
- bearer vs mTLS production auth;
- snapshot/element_ref implementation;
- dialog policy;
- Browser process pool;
- exact artifact TTL/stream protocol.

Они могут быть уточнены implementation design без смены решения direct RPC.

---

## 30. Затронутые документы

Решение является конкретизацией:

- `../browser.md`;
- `../runtime-topology.md`;
- `../security.md`;
- `../deployment.md`;
- `../observability.md`;
- `../persistence.md`.

При implementation эти документы должны ссылаться на ADR, а не снова перечислять альтернативы как равноправные.
