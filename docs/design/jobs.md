# Jobs subsystem design

## Статус документа

Этот документ является каноническим владельцем **durable/background execution model, Job lifecycle, attempts, claim/lease/retry/cancellation/progress semantics и Job Worker responsibilities** Web Access MCP.

Он не превращает каждую Application Operation в Job и не определяет окончательный REST/MCP job facade.

---

# 1. Purpose

Jobs предоставляет устойчивую execution model для операций, которые по своей семантике:

- могут выполняться дольше обычного request-bound deadline;
- должны переживать client disconnect;
- требуют durable progress/state/result;
- нуждаются в retry после worker/process failure;
- естественно выполняются background worker-ом.

---

# 2. Основной принцип

```text
Operation ≠ Job
```

Job создаётся только явной application capability.

Нельзя использовать Jobs как универсальный способ выполнить всё «надёжнее».

Короткие Search, Retrieval, Content read/inspection и Browser actions остаются request-bound, если их component contract не требует обратного.

---

# 3. Типичные Job candidates

Предварительные примеры:

- bounded site crawl;
- большой batch Retrieval;
- L1 Content processing, который по execution profile требует durable worker;
- длительное построение derived representations;
- maintenance/reconciliation tasks, если им нужен общий Job framework;
- future composed web workflows, только после отдельного design.

Не все эти job types обязаны появиться в первой версии.

---

# 4. Non-goals

Jobs не должен:

- автоматически создавать Job вместо request-bound operation;
- быть scheduler/agent reasoning engine;
- исполнять произвольный Python payload клиента;
- хранить огромный result прямо в Job row;
- использовать Redis message как source of truth;
- гарантировать exactly-once execution внешнего side effect;
- скрывать mutating Browser actions внутри generic retry loop;
- заменять BrowserSession ownership/routing.

---

# 5. Job как Resource

Используется `Job` resource из `resource-model.md`.

Job имеет:

```text
job_id
owner/principal
job_type
state
input/parameters reference
created_at
updated_at
retry/attempt policy
progress summary
terminal result/error
result resource refs
retention/expiration
```

Public `job_id` opaque.

---

# 6. Job type registry

Jobs subsystem должен иметь registry известных job types.

Концептуально descriptor содержит:

```text
job_type
input schema/application contract reference
worker capability
retry policy
max attempts policy
execution deadline policy
cancellation capability
result kind
resource/cost limits
implementation revision
```

Job type — стабильное application понятие, а не имя arq Python function.

---

# 7. Generic framework, typed jobs

Backend может иметь общий Job lifecycle framework, но payload каждого job type должен быть typed/versioned.

Нельзя создавать public contract:

```json
{
  "task": "anything",
  "arguments": {}
}
```

с arbitrary execution semantics.

Каждый supported job type имеет отдельный application request/result contract.

---

# 8. Job creation operation

Концептуально:

```text
JobApplicationService.create(
    ExecutionContext,
    TypedJobCreateRequest,
) -> OperationResult[JobRef]
```

Creation является request-bound operation.

При success клиент получает durable `job_id`, после чего Job живёт независимо от transport connection.

---

# 9. Creation transaction

В одной PostgreSQL transaction создаются:

```text
Job row/state
+
Outbox record для enqueue
```

После commit client может получить successful JobRef.

Факт успешного ответа не требует, чтобы Redis publish уже завершился синхронно, если outbox гарантирует последующую доставку.

---

# 10. Initial state

После committed creation Job находится в:

```text
created
```

или сразу `queued`, если chosen state model трактует durable outbox как queue admission.

В этом design принимается более явная модель:

```text
created
→ queued
```

где `created` означает durable Job существует, но queue publication/claim ещё не подтверждены.

Outbox publisher после успешной публикации переводит Job в `queued` или фиксирует соответствующий queue-admission event атомарно/идемпотентно.

---

# 11. Job lifecycle

Канонический state set:

```text
created
queued
running
retry_wait
cancelling
succeeded
failed
cancelled
expired
```

`lost` используется для execution attempt, а не как основной terminal Job state.

---

# 12. Lifecycle transitions

Основные transitions:

```text
created → queued
created → cancelling
created → cancelled

queued → running
queued → cancelling
queued → cancelled

running → succeeded
running → failed
running → retry_wait
running → cancelling

retry_wait → queued
retry_wait → cancelling
retry_wait → failed

cancelling → cancelled
cancelling → failed

terminal → expired
```

Не все transitions обязаны выполняться напрямую; implementation использует compare-and-set/transaction semantics.

---

# 13. Terminal states

Рабочие terminal execution states:

```text
succeeded
failed
cancelled
```

`expired` — lifecycle/retention state после terminal или abandoned Job согласно policy и не означает execution result.

Terminal result/error сохраняется до установленной retention policy.

---

# 14. JobAttempt

Каждый фактический execution attempt имеет отдельную identity.

Концептуально:

```text
JobAttempt
├── attempt_id
├── job_id
├── attempt_number
├── operation_id
├── worker_id/generation
├── state
├── lease/fencing metadata
├── started_at
├── heartbeat_at
├── completed_at
└── result/error summary
```

Job identity сохраняется между attempts.

---

# 15. Attempt states

Предварительные attempt states:

```text
claimed
running
succeeded
failed
cancelled
lost
```

`lost` означает, что worker/lease исчез до подтверждённого terminal result.

Job policy решает, приводит ли lost attempt к retry_wait или failed.

---

# 16. Queue delivery

Target model из `persistence.md`:

```text
PostgreSQL Job + Outbox
→ at-least-once publish
→ Redis/arq delivery
→ worker claim against PostgreSQL
```

Duplicate queue messages допустимы.

Queue delivery не считается Job ownership сама по себе.

---

# 17. Claim protocol

После получения message worker должен атомарно claim Job/attempt через JobRepository.

Claim проверяет:

- Job существует;
- Job state допускает execution;
- нет current active attempt/lease;
- message не stale/duplicate;
- worker поддерживает required job type/revision;
- cancellation уже не запрещает start.

Только после успешного claim worker начинает application execution.

---

# 18. Duplicate delivery

Если два workers получили duplicate message:

```text
worker A → claim succeeds
worker B → claim rejected as already claimed/stale
```

Второй worker не выполняет job body.

Это обязательный concurrency invariant.

---

# 19. Worker identity/generation

Job Worker имеет identity + generation аналогично другим distributed runtimes.

Attempt хранит owning worker generation, чтобы restart того же logical worker name не считался продолжением старого lease.

---

# 20. Attempt lease

Running attempt должен иметь bounded lease/heartbeat contract, если execution может быть достаточно долгим, чтобы worker crash иначе оставил Job в `running` навсегда.

Worker периодически renew lease/heartbeat.

Reconciler считает attempt потерянным только после установленного grace/lease expiry policy.

---

# 21. Fencing

Если stale worker после lease expiry способен сохранить terminal result поверх новой попытки, нужен attempt/fencing check.

Любое state update running attempt должен подтверждать current `attempt_id`/revision.

Старый lost attempt не может завершить Job после того, как новый attempt уже claimed.

---

# 22. Worker crash

Если heartbeat/lease current attempt expired:

```text
attempt → lost
```

Далее Job policy:

```text
retryable + attempts remain
→ retry_wait

otherwise
→ failed
```

Loss не должен оставлять Job вечным `running`.

---

# 23. Retry policy

Retry задаётся job-type policy, а не generic «повторить всё N раз».

Policy учитывает:

- error category/code;
- attempt count;
- operation semantics;
- external side effects;
- remaining overall Job lifetime/deadline;
- provider cost/rate limits.

---

# 24. Retryable errors

Кандидаты на retry:

- transient provider/network failure;
- worker crash/lost attempt;
- temporary infrastructure unavailability;
- explicitly retryable rate/capacity response с backoff.

Не retry:

- validation/policy rejection;
- unsupported input;
- permanent permission denial;
- malformed content;
- exhausted resource limit;
- unknown side-effect outcome, если повтор небезопасен.

---

# 25. Retry backoff

Retry использует bounded backoff policy.

Возможна экспоненциальная задержка + jitter как implementation direction, но точные параметры configurable per job type.

Retry time фиксируется durable state:

```text
retry_wait
next_attempt_at
```

Нельзя держать worker sleep/process занятым для долгого backoff.

---

# 26. Max attempts

Каждый retryable Job имеет finite max attempts или иной bounded termination policy.

Infinite retry без operator intervention запрещён как default.

`max_attempts` относится к Job type/configuration, а не arbitrary caller override для обычного MCP client.

---

# 27. Overall Job deadline/lifetime

Помимо per-attempt deadline Job может иметь overall execution deadline/max lifetime.

После его истечения новые attempts не создаются.

Job terminal result:

```text
failed: job_deadline_exceeded
```

или `cancelled`, только если cancellation была explicit и подтверждена согласно contract.

---

# 28. Attempt deadline

Worker получает bounded deadline для текущего attempt.

Downstream application/providers должны использовать оставшийся budget аналогично request-bound ExecutionContext.

Attempt timeout может быть retryable или terminal в зависимости от job type/error policy.

---

# 29. Cancellation request

Job cancellation является отдельной application operation:

```text
JobApplicationService.cancel(job_id)
```

Она проверяет ownership/state и durable фиксирует cancellation intent.

---

# 30. Cancellation states

Если Job ещё не начал execution:

```text
created/queued/retry_wait
→ cancelling или напрямую cancelled атомарно
```

Если attempt running:

```text
running
→ cancelling
→ worker получает cooperative cancel signal
```

Terminal Job не отменяется повторно; cancel terminal Job должен быть идемпотентным/no-op result согласно API contract.

---

# 31. Cancellation acknowledgement

Job становится `cancelled` только после того, как система может утверждать, что active execution больше не выполняется и terminal cancellation semantics соблюдены.

Request `cancel()` сам по себе не означает мгновенный `cancelled`.

---

# 32. Worker cancellation

Worker должен регулярно проверять cancellation context в долгих loops/batches и корректно прерывать downstream work там, где это возможно.

Blocking/uncooperative library operations должны иметь process/deadline isolation, иначе cancellation guarantee должна быть честно ограничена.

---

# 33. Cancellation и external side effects

Если Job type выполняет mutating external operation и cancellation произошла после возможного side effect, component contract должен поддерживать `unknown`/partial result semantics.

Generic Jobs framework не превращает это автоматически в `cancelled`.

Поэтому потенциально side-effecting workflow нельзя регистрировать как retryable Job без отдельной execution design.

---

# 34. Progress

Job может публиковать durable/observable progress.

Общая progress model должна быть структурированной и bounded.

Концептуально:

```text
JobProgress
├── phase/code
├── completed | null
├── total | null
├── unit | null
├── message | null
└── updated_at
```

`completed/total` используются только когда operation имеет реальный измеримый объём.

Нельзя выдумывать fake percentage для неопределённого процесса.

---

# 35. Progress monotonicity

Если `completed/total` объявлены для конкретной phase:

- completed не уменьшается без смены phase/restart semantics;
- total не меняется произвольно;
- progress update sequence имеет монотонный event/sequence ID.

Retry attempt может начать новую attempt-specific phase, но Job-level UI должен иметь понятную retry metadata.

---

# 36. Durable progress vs telemetry

Только progress, полезный клиенту после reconnect, хранится durable/compact.

Высокочастотные internal events остаются telemetry.

Нельзя писать каждую обработанную HTTP chunk/event как PostgreSQL Job event.

---

# 37. Job event log

Для client-visible lifecycle полезен bounded durable event log:

```text
created
queued
attempt_started
progress
retry_scheduled
cancellation_requested
succeeded/failed/cancelled
```

Точный retention/coalescing определяется implementation.

Event log не обязан быть full event sourcing source of truth.

Current Job row/state остаётся authoritative snapshot.

---

# 38. Result model

Terminal Job result содержит:

```text
outcome/state
small structured summary/manifest
ContentRef(s) / ResourceRef(s)
error | null
warnings/hints
attempt summary
```

Большие crawl/document outputs сохраняются в ContentStore/ContentObjects.

---

# 39. Partial results

Job type должен явно определить, сохраняются ли partial outputs после failure/cancel.

Например большой Retrieval batch может сохранить successful ContentObjects уже обработанных items и terminal manifest с per-item outcomes.

Нельзя автоматически удалять полезные successful outputs только потому, что Job aggregate failed/was cancelled.

---

# 40. Result immutability

После terminal completion canonical Job result не переписывается последующим retry/worker message.

Late stale attempt updates rejected через attempt/fencing checks.

Retention metadata может изменяться независимо.

---

# 41. Job inputs

Большие inputs передаются через ContentRefs/ResourceRefs, а не giant queue payload.

Queue message должен быть компактным:

```text
job_id
attempt/request metadata
```

Worker загружает authoritative typed input из PostgreSQL/ContentStore через application ports.

---

# 42. Secret inputs

Secrets не копируются без необходимости в Job payload/event tables.

Если Job требует credential/reference, используется scoped secret reference/credential service contract, который будет определён security/auth design.

Queue message не содержит raw long-lived secret.

---

# 43. JobQueue port

Application Jobs объявляет port:

```text
JobQueue
```

с semantics publication/notification, но queue не определяет Job state.

Concrete initial adapter предполагается на Redis/arq.

Arq-specific function names/context не протекают в application contract.

---

# 44. Outbox publisher

Outbox publisher может быть:

- отдельным lightweight process;
- задачей/loop внутри определённого runtime;

но ownership, HA и failure semantics должны быть явными.

Multiple publishers допустимы только при безопасном concurrent claim outbox records.

Точная implementation определяется version design.

---

# 45. Reconciler

Jobs subsystem обязан иметь reconciliation, способный находить:

- `created` Job с недоставленным outbox;
- stale `running` attempt с expired lease;
- `cancelling` Job без live worker;
- retry_wait, готовый к следующему attempt;
- terminal Job с inconsistent attempt state;
- stale queue messages.

Reconciler должен быть идемпотентным и безопасным при нескольких replicas.

---

# 46. Scheduler граница

Job retry/time-based wakeup не превращает Web Access в общий scheduler.

Jobs framework может планировать **внутренний next_attempt_at** конкретного Job.

Generic cron/user scheduling находится за пределами Web Access, если позднее не появится отдельная системная потребность.

---

# 47. Crawl как Job

Site crawl является естественным durable Job candidate, но exact crawl semantics проектируются отдельно внутри Jobs/нового component design, когда потребуется.

Минимальные будущие concerns:

- seed URLs;
- depth/page limits;
- same-origin/domain policy;
- robots policy;
- dedup visited URLs;
- per-host rate;
- ContentObjects;
- cancellation/progress.

`jobs.md` не фиксирует crawl API заранее.

---

# 48. Large Retrieval batch как Job

Если клиент явно выбирает durable large retrieval:

```text
Job
→ вызывает Retrieval application operations/bounded batches
→ сохраняет per-item ContentRefs/outcomes
```

Job Worker не реализует отдельный HTTP stack.

Он использует тот же Retrieval application/infrastructure contract.

---

# 49. Content processing Job

Если Native Parser execution profile = `job_required`:

```text
Content processing Job
→ source ContentRef
→ тот же ContentApplicationService/parser contract
→ derived ContentRefs
```

Job Worker не дублирует parser logic.

---

# 50. Browser workflows и Jobs

Generic durable Browser workflow **не входит в baseline Jobs contract**.

Причины:

- BrowserSession имеет отдельного owning Browser Worker;
- mutating actions могут иметь unknown outcomes;
- retries опаснее;
- lifecycle/TTL сильно отличается.

Если позднее понадобится durable browser workflow, он требует отдельного design и не должен просто исполняться arq worker-ом как список click commands.

---

# 51. Worker capability registry

Job Worker registration/health может указывать supported job types/revisions.

Queue routing может использовать разные queues/pools по capability в будущем.

Job public contract не должен зависеть от hostname/container queue name.

---

# 52. Worker graceful drain

При drain Job Worker:

- перестаёт claim новые Jobs;
- продолжает current attempts до bounded shutdown policy;
- обновляет heartbeat/draining state;
- если attempt не может завершиться, lease expiry/retry semantics восстанавливают Job;
- не оставляет ложный terminal success.

---

# 53. Worker process termination

SIGTERM/container shutdown должен давать bounded grace period.

Если attempt не подтверждён terminal до process death:

- lease истекает;
- attempt → lost;
- Job retry/fail policy применяется reconciler-ом.

Нельзя полагаться только на `finally` handler worker-а как гарантию consistency.

---

# 54. Capacity/backpressure

Jobs system должен иметь bounded admission:

- principal concurrent jobs;
- global queued/running capacity;
- job-type capacity;
- worker pool saturation;
- payload/resource limits.

При превышении лимита create operation возвращает `rejected/capacity` или rate-limit semantics согласно policy.

Не допускается бесконечное накопление новых Jobs без quotas.

---

# 55. Priority

Generic user-controlled arbitrary priority не является baseline.

Если появится несколько системных классов приоритета, они должны быть allowlisted policy concepts, чтобы один client не мог вытеснить остальных значением `priority=999999`.

---

# 56. Fairness

Multi-user design должен позволять fairness/admission по principal, а не только FIFO общей очереди.

Точный scheduling algorithm можно отложить до multi-user/load design, но Job model не должна делать fairness невозможной.

---

# 57. Job expiration/retention

После terminal state Job metadata/results сохраняются согласно retention policy.

После expiration:

- Job handle может возвращать `expired`/tombstone semantics;
- associated ContentObjects живут по собственной retention policy;
- Job cleanup не должен случайно удалять explicitly retained ContentObject другого lifecycle class.

---

# 58. Cancellation result retention

Cancelled Job сохраняет terminal manifest/error/progress summary достаточное время для диагностики.

Cancellation не означает мгновенный hard DELETE.

---

# 59. Job errors

Job-specific codes должны различать как минимум:

```text
job_not_found
job_expired
job_already_terminal
job_capacity_unavailable
job_type_unsupported
job_claim_conflict
job_worker_lost
job_deadline_exceeded
job_attempts_exhausted
job_cancel_requested
job_cancel_failed
job_result_unavailable
```

Component-specific underlying error сохраняется/маппится в terminal result.

---

# 60. Observability

Jobs telemetry должна включать:

- created/queued/running counts;
- queue admission latency;
- attempt duration;
- attempts per Job;
- retries/retry reasons;
- lease expirations;
- worker loss;
- cancellation latency;
- outbox backlog/age;
- queue delivery duplicates;
- claim conflicts;
- terminal outcomes;
- Job age;
- result Content bytes/references;
- reconciler actions.

Job ID не используется как metric label.

---

# 61. REST projection expectations

REST позднее должен предоставить богатый Job API:

- create typed job;
- get Job state/result;
- list/filter owner Jobs;
- cancel;
- progress/events pagination/cursor;
- result resource refs;
- authorized operational diagnostics.

Не нужен generic endpoint, принимающий arbitrary Python task name.

---

# 62. MCP projection expectations

MCP не должен заставлять LLM вручную управлять queue internals.

Варианты projection определяются позже:

- domain-specific long-running tool возвращает `job_id`;
- generic `job_get`/`job_cancel` для lifecycle;
- native MCP Tasks могут быть дополнительной projection, если выбранная FastMCP/MCP версия и agent client стабильно их поддерживают.

Application Job lifecycle не зависит от наличия MCP Tasks.

---

# 63. Native MCP Tasks boundary

MCP Tasks, если используются, являются transport projection существующего Job resource.

Нельзя строить internal persistence/lifecycle исключительно вокруг protocol-specific MCP Task session state.

REST и internal workers должны видеть тот же canonical Job.

---

# 64. Unit/contract tests

Jobs application tests должны покрывать:

1. create + outbox transaction;
2. outbox publish → queued;
3. duplicate message claim;
4. concurrent claim;
5. attempt lifecycle;
6. lease expiry → lost;
7. retry_wait/backoff;
8. max attempts exhausted;
9. cancellation before start;
10. cancellation while running;
11. terminal cancel idempotency;
12. late stale attempt cannot overwrite terminal result;
13. partial result ContentRefs preserved;
14. owner isolation;
15. Job retention/expiration.

---

# 65. Persistence/fault tests

Обязательные сценарии:

- crash после DB Job+outbox commit;
- publisher duplicate publish;
- Redis unavailable;
- worker crash immediately after claim;
- worker crash after external work but before result commit;
- heartbeat loss with temporary network partition;
- two reconcilers process same stale attempt;
- cancellation vs completion race;
- retry scheduling vs cancellation race;
- terminal update vs stale worker late update;
- ContentStore failure during Job result finalization.

---

# 66. Load tests

До production необходимо проверить:

- большое количество queued Jobs;
- outbox backlog recovery;
- worker pool scale-out/in;
- principal admission limits;
- database hot rows/indexes;
- Redis queue memory;
- retry storm after provider outage;
- cancellation storm;
- reconciler performance.

Retry storm должен подавляться backoff/jitter/capacity policy.

---

# 67. Acceptance criteria Jobs subsystem

Jobs считается реализованным, если:

1. Job создаётся явно, а request-bound operations не auto-promote в Job.
2. Job имеет opaque owner-scoped durable identity.
3. Job + Outbox создаются одной PostgreSQL transaction.
4. Queue delivery at-least-once и duplicate-safe.
5. Worker обязан claim Job в PostgreSQL до execution.
6. Один Job не выполняется двумя active attempts одновременно.
7. Attempts имеют lease/worker generation и stale attempts fenced.
8. Worker crash обнаруживается и приводит к retry/fail согласно policy.
9. Retry finite/configurable per job type.
10. Retry_wait не занимает worker sleep.
11. Cancellation durable и cooperative; terminal `cancelled` не ставится преждевременно.
12. Большой result хранится через ContentRefs.
13. Terminal result immutable для late stale attempt.
14. Reconciler восстанавливает outbox/lease/stuck states.
15. Job Worker использует существующие Search/Retrieval/Content application services, а не дублирует их logic.
16. Generic durable browser click workflow не внедрён без отдельного design.
17. Owner quotas/capacity предотвращают unbounded admission.
18. REST/MCP могут проецировать один canonical Job lifecycle.

---

# 68. Open questions

До implementation Jobs необходимо закрыть:

1. Exact Job/Attempt SQL schema и indexes.
2. Exact UnitOfWork/outbox publisher implementation.
3. Используется ли один arq queue или capability-specific queues/pools.
4. Lease duration/heartbeat policy.
5. Exact fencing/CAS algorithm для attempts.
6. Backoff/jitter policies per initial job types.
7. Как Job Worker получает cancellation signal: DB polling, Redis notification + DB source of truth или другое.
8. Durable progress/event schema и coalescing.
9. Первый набор concrete job types в roadmap.
10. Нужен ли owner Job list/history в первой REST версии.
11. MCP Tasks support strategy после проверки фактических client/SDK capabilities.
12. Нужен ли отдельный Outbox Publisher runtime или HA loop внутри Control Plane/Job Worker.
13. Fairness/scheduling policy для multi-user deployment.

Эти вопросы уточняют implementation, но не меняют принятый durable lifecycle/outbox/attempt model.
