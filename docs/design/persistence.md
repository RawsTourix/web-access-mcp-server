# Persistence и consistency model Web Access MCP

## Статус документа

Этот документ является каноническим владельцем **ролей PostgreSQL, Redis, ContentStore, transaction boundaries, durability и recovery/reconciliation principles** проекта.

Он не фиксирует полный SQL DDL, Redis key names или ContentStore bucket layout.

---

# 1. Базовое разделение хранилищ

Каноническая модель:

```text
PostgreSQL
→ authoritative durable structured state

Redis
→ cache / queue / coordination / locks / leases / routing acceleration

ContentStore
→ крупные raw/derived bytes

Browser Worker memory
→ live Playwright state
```

Ни один из этих компонентов не должен неявно подменять роль другого.

---

# 2. PostgreSQL — основной durable source of truth

PostgreSQL хранит структурированное состояние, которое должно переживать restart и быть согласованным между replicas.

Предварительные категории:

- ContentObject metadata/lifecycle;
- BrowserSession durable metadata/lifecycle;
- Job state/attempts/results;
- ownership/principal references;
- provider usage/cost records, если они требуют durability;
- outbox records;
- durable audit/resource lifecycle events, если они входят в contract;
- idempotency records для операций, где они требуются;
- policy/configuration records, если позднее они станут динамическими.

Не каждая request-bound Operation обязана иметь отдельную PostgreSQL row.

---

# 3. Redis не является durable model проекта

Redis используется только там, где допустима его operational semantics.

Допустимые роли:

- cache;
- rate limiting;
- arq queue;
- distributed locks там, где они действительно нужны;
- leases/fencing coordination;
- Browser Worker heartbeat/registry acceleration;
- short-lived routing metadata;
- event/mailbox transport, если это будет выбрано ADR;
- backpressure/capacity counters.

Если durable факт существует только как Redis key и должен переживать restart/flush, architecture считается неверной, если это не отдельное принятое решение.

---

# 4. ContentStore хранит payload, PostgreSQL — metadata

Большие bytes хранятся за `ContentStore` port.

```text
ContentObject metadata
→ PostgreSQL

Content payload
→ ContentStore
```

Предполагаемые adapters:

- local/shared filesystem;
- S3-compatible object storage.

PostgreSQL не используется как универсальный blob store больших HTML/PDF/screenshots/downloads.

---

# 5. Live browser state не персистится как object graph

Playwright runtime objects существуют только в owning Browser Worker memory.

PostgreSQL/Redis могут хранить:

- BrowserSession metadata;
- owner worker reference;
- lifecycle state;
- revision;
- heartbeat/routing information;
- audit/action records.

Они не пытаются сериализовать:

- BrowserContext;
- Page;
- Locator;
- JavaScript heap;
- transient DOM state.

После потери worker live state считается потерянным согласно BrowserSession lifecycle.

---

# 6. Repository ownership

Repositories принадлежат application ports соответствующих модулей.

Пример:

```text
BrowserSessionRepository
ContentRepository
JobRepository
```

Concrete SQLAlchemy implementations находятся в infrastructure.

Transport не обращается к repositories напрямую.

---

# 7. Transaction boundary принадлежит application use case

Repository method не должен неожиданно выполнять `commit()` как скрытый side effect, если operation требует нескольких согласованных writes.

Application transaction boundary должен быть явным.

Предпочтительная модель:

```text
Application Service / Unit of Work
    ↓
несколько repository operations
    ↓
один commit / rollback boundary
```

Точная Python abstraction (`UnitOfWork`, transaction context или эквивалент) определяется implementation design, но semantic ownership transaction фиксируется здесь.

---

# 8. SQLAlchemy Session не протекает в application contract

`AsyncSession` является infrastructure detail.

Application service не должен требовать от REST/MCP transport передать SQLAlchemy Session как часть business contract.

Bootstrap/infrastructure создаёт transaction/unit-of-work implementation и предоставляет application layer стабильный port/context.

---

# 9. Database constraints являются частью consistency defense

Там, где invariant можно гарантировать database constraint-ом, следует использовать его дополнительно к application validation.

Примеры-кандидаты:

- unique idempotency scope/key;
- допустимая identity/resource uniqueness;
- foreign-key consistency;
- uniqueness active ownership records, если модель это допускает.

Application validation не заменяет DB constraint при concurrent writes.

---

# 10. Optimistic concurrency

Mutable durable resources могут использовать revision/version для предотвращения lost update.

Пример:

```text
UPDATE ...
WHERE resource_id = ? AND revision = expected_revision
```

с последующим increment revision.

Необходимость optimistic locking определяется resource-specific design.

BrowserSession является главным кандидатом из-за stale action/state transitions.

---

# 11. Pessimistic locking используется точечно

`SELECT ... FOR UPDATE` или аналогичные DB locks применяются там, где transaction должна сериализовать короткий critical section.

Нельзя удерживать DB transaction/lock во время:

- долгого HTTP request;
- Browser action;
- ожидания внешнего provider;
- upload большого файла;
- длительной queue operation.

External I/O не должно происходить внутри длинной DB transaction без отдельного обоснования.

---

# 12. Redis lock не заменяет database invariant

Если корректность durable state может быть обеспечена PostgreSQL transaction/constraint, Redis lock не должен быть единственной защитой.

Redis locks/leases нужны преимущественно для распределённого runtime coordination, например:

- worker ownership;
- reaper election;
- deduplicated background maintenance;
- resource scheduling.

---

# 13. Fencing

Для lease-based ownership, где stale owner способен выполнить опасное действие после истечения lease, следует рассматривать fencing token/version.

Browser Worker routing является потенциальным кандидатом.

Точный fencing protocol не фиксируется до `browser.md`/ADR.

Важно: простой Redis lock без защиты stale owner не считается автоматически достаточным для single-owner correctness.

---

# 14. Durable Job publication — cross-system consistency problem

Создание durable Job включает минимум две системы:

```text
PostgreSQL
→ authoritative Job state

Redis/arq
→ delivery к worker
```

Нельзя считать два независимых вызова:

```text
DB commit
redis.enqueue
```

атомарными.

Crash между ними создаёт durable Job, который не попал в queue.

---

# 15. Target solution — Transactional Outbox

Для production durable Job publication принимается направление **transactional outbox**.

В одной PostgreSQL transaction создаются:

```text
Job durable state
+
Outbox message/event
```

После commit отдельный publisher/reconciler:

```text
читает pending outbox
→ публикует message в Redis/arq
→ отмечает delivery
```

Это устраняет окно, в котором authoritative Job существует без durable знания о необходимости публикации.

---

# 16. Outbox delivery является at-least-once

Publisher может упасть после фактической публикации, но до отметки outbox delivered.

Следовательно повторная публикация возможна.

Job Worker/queue ingress должны корректно обрабатывать duplicate delivery одного `job_id`/attempt message.

Exactly-once delivery через PostgreSQL + Redis не предполагается.

Корректность строится на:

```text
at-least-once delivery
+
idempotent claim/attempt transition
+
durable Job state
```

---

# 17. Job claim

Worker не должен начинать выполнение только потому, что получил queue message.

Он должен atomically подтвердить через JobRepository, что:

- Job существует;
- находится в допустимом state;
- текущая попытка может быть claimed;
- duplicate/stale message не должен запускать второй concurrent execution.

Точная attempt/lease model определяется `jobs.md`.

---

# 18. Queue message не является source of truth

Redis/arq message является сигналом о работе.

Authoritative состояние Job находится в PostgreSQL.

Потеря/дублирование queue delivery восстанавливается из durable state/outbox/reconciliation.

---

# 19. Outbox cleanup

Delivered outbox records имеют отдельную retention/cleanup policy.

Нельзя бесконечно накапливать outbox rows.

При этом cleanup не должен удалять записи, необходимые для recovery/diagnostics раньше установленного safe window.

---

# 20. Reconciliation обязателен даже с Outbox

Отдельные reconciliation процессы должны уметь находить аномальные durable состояния.

Примеры:

- pending outbox слишком долго не доставлен;
- Job `running`, но worker lease/attempt давно потерян;
- BrowserSession указывает на worker, которого больше нет;
- ContentObject застрял в creation/finalization state;
- payload есть без metadata или metadata без payload.

Outbox уменьшает класс проблем, но не заменяет reconciliation всей системы.

---

# 21. Content write не является атомарным с PostgreSQL

ContentStore и PostgreSQL — разные systems.

Нельзя обещать atomic transaction между ними.

Content creation design обязан учитывать crash windows.

Концептуально нужен lifecycle вроде:

```text
allocate/prepare
→ write/stage payload
→ verify size/hash
→ finalize metadata/payload publication
→ available
```

Точный порядок определяется `content.md` с учётом filesystem/S3 semantics.

---

# 22. Orphan Content cleanup

Нужно уметь обнаруживать:

- blob без authoritative Content metadata;
- metadata, указывающую на отсутствующий payload;
- незавершённый staged upload;
- expired payload, который ещё физически не удалён.

Reaper/reconciliation должен иметь safe algorithm и не удалять действующий payload из-за eventual consistency/временной ошибки storage без подтверждения.

---

# 23. Content hash и integrity

При создании ContentObject желательно вычислять криптографический content hash для:

- integrity verification;
- provenance;
- dedup optimization;
- corruption diagnostics.

Точный algorithm фиксируется implementation/security design.

Hash не заменяет ContentObject identity и ownership.

---

# 24. Deduplication

Physical deduplication ContentStore допустима как optimization.

Требования:

- logical ContentObjects остаются разделены по ownership/lifecycle;
- dedup не раскрывает наличие чужого content;
- deletion одного logical object не удаляет physical bytes, пока существуют другие valid refs;
- race reference counting/GC должен быть transaction-safe.

Если эта сложность не нужна первой реализации, dedup может быть отключён без изменения application contract.

---

# 25. Cache persistence

Cache entries не требуют durable восстановления после Redis loss, если component contract не утверждает обратное.

После cache loss система должна уметь вернуться к source/provider execution.

Cache invalidation/TTL принадлежит соответствующему component design.

---

# 26. Cache keys versioned

Redis/cache key namespace должен позволять безопасно инвалидировать данные при изменении:

- application schema;
- normalization logic;
- provider configuration;
- parser revision;
- security/policy semantics.

Точные key formats не являются design contract, но versionability обязательна.

---

# 27. Cache не обходит ownership/policy

Нельзя выдавать cached private/owner-scoped result другому principal только потому, что cache key совпал по содержимому запроса.

Cache scope должен учитывать security domain операции.

---

# 28. Browser routing metadata

Предварительная модель:

```text
PostgreSQL
→ durable BrowserSession lifecycle metadata

Redis
→ быстрый owner-worker routing / heartbeat / lease metadata
```

Если Redis routing потерян:

- BrowserSession durable record не исчезает;
- система выполняет reconciliation;
- session может перейти в `lost`, если owning worker/state невозможно подтвердить.

Точный protocol определяется `browser.md`.

---

# 29. Worker heartbeat не является proof of session existence

Worker heartbeat говорит о runtime availability, но не подтверждает автоматически наличие каждой BrowserSession.

Recovery/reconciliation должна учитывать:

- worker generation/identity;
- session registration;
- lease/fencing state;
- возможный stale heartbeat/routing record.

---

# 30. Resource expiration

Expiration durable resource должна быть отражена application metadata/state.

Нельзя иметь единственную semantics:

```text
Redis TTL исчез → resource magically expired
```

если resource lifecycle должен быть диагностируемым после expiration.

Redis TTL может использоваться как trigger/optimization, а canonical transition фиксируется durable layer там, где это требуется contract.

---

# 31. Time model

Durable timestamps хранятся в UTC с timezone-aware semantics.

Application не должна полагаться на local server timezone.

Для measuring durations/timeouts runtime использует monotonic clock, где это возможно; wall-clock timestamps используются для persistence/audit.

Если тестируемость требует Clock port, он вводится в `core/application` без протекания framework-specific time APIs.

---

# 32. Soft state и tombstones

Terminal resource metadata может сохраняться после удаления live payload.

Нужен retention policy, позволяющий некоторое время отличать:

- not found;
- expired;
- closed;
- lost;
- removed.

Полный tombstone model определяется resource-specific design.

---

# 33. Audit и telemetry разделены

Не каждый log/trace должен храниться в PostgreSQL.

## Durable audit

Используется только для фактов, которые должны переживать telemetry retention и являются частью security/lifecycle/business requirements.

## Telemetry

Logs/metrics/traces хранятся в observability systems/pipeline и не обязаны становиться application tables.

Не следует создавать operation-history table для каждой мелкой операции только ради debug convenience без явной необходимости.

---

# 34. Provider usage/cost

Если SearchProvider имеет billable usage или quotas, durable accounting должно быть спроектировано так, чтобы:

- не терять подтверждённые billable calls;
- отличать attempted/confirmed usage;
- сохранять provider/request correlation;
- не полагаться только на transient logs.

Точная accounting model принадлежит `search.md`/будущему policy design.

---

# 35. Migration discipline

Schema changes PostgreSQL выполняются через Alembic migrations.

Production application startup не должен самовольно выполнять destructive auto-migration.

Deployment должен иметь явный migration step/process.

Migration design должен учитывать rolling/zero-downtime compatibility для версий, где несколько app replicas временно работают с одной БД.

---

# 36. Expand/contract migrations

Для несовместимых schema changes предпочтителен staged подход:

```text
expand schema
→ deploy code compatible со старым/новым
→ migrate/backfill data
→ switch readers/writers
→ contract old schema
```

Version plan обязан указывать, если migration требует такого перехода.

---

# 37. Persistence schema не является REST/MCP schema

Изменение database layout не должно автоматически требовать изменения public API.

Public application Resource/Result model отображается через repositories/mappers.

Нельзя отдавать ORM serialization как REST/MCP contract.

---

# 38. Database failure semantics

При недоступности PostgreSQL capability-aware behavior зависит от операции.

Примеры:

- создание durable Job невозможно → operation отклоняется/падает контролируемо;
- создание BrowserSession, если durable ownership metadata обязательна, невозможно;
- purely request-bound Search потенциально может работать, если design не требует DB для этой операции;
- Content persistence невозможна, если result должен стать durable ContentObject.

Сервис не должен обходить обязательную persistence guarantee ради «частичного продолжения» без explicit degraded contract.

---

# 39. Redis failure semantics

Redis outage не обязан выключать весь Web Access.

Capability impact может быть разным:

```text
cache unavailable
→ direct Search/Retrieval могут продолжить работу

arq unavailable
→ создание/dispatch durable Jobs недоступно

browser routing Redis unavailable
→ Browser actions могут стать недоступны, если выбранный protocol зависит от Redis
```

Точный degraded behavior документируется компонентами и readiness model.

---

# 40. ContentStore failure semantics

Если ContentStore недоступен:

- операции, которым нужен durable ContentObject, не должны возвращать ложный successful durable handle;
- небольшой inline result может быть допустим только если component/application contract явно разрешает работу без persistence;
- partial/staged object не объявляется `available` до подтверждения storage semantics.

---

# 41. Backup и disaster recovery boundary

Production deployment должен отдельно определить:

- PostgreSQL backups/PITR;
- ContentStore durability/versioning/backup по требованиям;
- Redis persistence только там, где operationally полезно, но не как замена durable source of truth;
- последствия потери live BrowserSession state.

Эти deployment details принадлежат `deployment.md`, но storage roles фиксируются здесь.

---

# 42. Data retention является policy

Retention сроки не хардкодятся по всему коду.

Компонентный design определяет категории данных, а configuration/policy задаёт сроки там, где они должны настраиваться.

Нужно отдельно учитывать:

- raw Content;
- derived Content;
- terminal resource metadata;
- Job results;
- outbox;
- audit;
- telemetry.

---

# 43. Repository tests

Каждый persistence adapter должен иметь integration tests с реальным соответствующим backend там, где это важно.

SQLite не считается достаточной заменой PostgreSQL для проверки:

- concurrency;
- JSON/locking semantics;
- transaction isolation;
- PostgreSQL-specific constraints;
- `FOR UPDATE` behavior.

---

# 44. Fault-injection tests

Persistence design считается реализованным только после тестов crash windows.

Минимальные сценарии:

1. Crash после Job/outbox DB commit до Redis publish.
2. Duplicate outbox publication.
3. Worker получает duplicate Job message.
4. Worker dies during claimed Job.
5. Content bytes записаны, DB finalize не произошёл.
6. DB record создан, ContentStore write не завершён.
7. Redis routing metadata потеряна при живом Browser Worker.
8. Browser Worker умер при существующей durable BrowserSession metadata.
9. Reaper запущен конкурентно на нескольких replicas.
10. Database transaction конфликтует по revision.

---

# 45. Acceptance criteria persistence foundation

При реализации общего persistence foundation должно быть подтверждено:

1. Repository methods не выполняют скрытый commit, нарушающий transaction boundary.
2. Application operation может атомарно изменить несколько PostgreSQL records через общий UoW/transaction.
3. Job creation + outbox write находятся в одной DB transaction.
4. Duplicate outbox delivery не запускает duplicate concurrent Job execution.
5. Redis loss не уничтожает durable Job/Content/BrowserSession metadata.
6. ContentStore payload не объявляется доступным до завершения предусмотренного finalize contract.
7. Orphan/stuck resources обнаруживаются reconciliation.
8. PostgreSQL/Redis/ContentStore failures дают capability-aware normalized errors.
9. ORM models не протекают в REST/MCP.
10. Migration process отделён от обычного app startup.
11. Resource ownership не обходится cache/deduplication.

---

# 46. Open questions

До component/version implementation необходимо закрыть:

1. Точная SQLAlchemy UnitOfWork abstraction.
2. Transaction isolation level по критичным операциям.
3. Конкретная outbox table/publisher model.
4. Нужно ли использовать arq напрямую или через собственный JobQueue adapter с отдельным message envelope.
5. Точный Content creation/finalization protocol для filesystem и S3.
6. Browser routing store/lease/fencing design.
7. Точные audit records и retention.
8. Production backup/PITR requirements.
9. Используется ли physical Content deduplication на первых версиях.

Эти вопросы уточняют реализацию, но не отменяют зафиксированные роли storage systems и consistency invariants.
