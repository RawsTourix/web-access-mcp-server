# Observability и operability design

## Статус документа

Этот документ является каноническим владельцем **structured logging, metrics, tracing, health/readiness/degraded-state model и границы telemetry ↔ durable audit** Web Access MCP.

Он не определяет конкретный внешний monitoring vendor и не превращает telemetry в application source of truth.

---

# 1. Цель observability

Система должна позволять ответить без чтения исходного кода на вопросы:

- какой application operation выполнялся;
- где была потрачена задержка;
- какой provider/worker участвовал;
- какой outcome/error возник;
- был ли retry/cache hit;
- какие capabilities сейчас доступны/деградированы;
- есть ли resource leaks/backlog;
- почему Job/BrowserSession застрял;
- какие security/policy rejections происходят;
- как система ведёт себя под нагрузкой.

---

# 2. Три разных класса наблюдаемости

Нужно различать:

```text
Telemetry
Durable Audit
Application State/Event History
```

Они не являются взаимозаменяемыми.

---

# 3. Telemetry

Telemetry включает:

- structured logs;
- metrics;
- distributed traces;
- runtime diagnostics.

Telemetry может иметь ограниченный retention и не является authoritative application state.

Потеря отдельного metric/log export не должна по умолчанию ломать application operation.

---

# 4. Durable Audit

Audit хранит только те факты, которые по security/compliance/application policy должны переживать обычную telemetry retention.

Примеры-кандидаты:

- mutating/high-risk Browser actions;
- authentication/authorization security events;
- admin/configuration changes;
- provider billing/accounting confirmations;
- resource lifecycle/security-sensitive ownership transitions.

Не каждая Search/Content read operation обязана становиться durable audit row.

Точная audit policy будет уточняться вместе с auth/REST/admin design.

---

# 5. Application event history

Некоторые resources имеют собственный bounded durable lifecycle history:

- Job events/progress;
- BrowserSession lifecycle events;
- Content creation/finalization/reconciliation events при необходимости.

Это часть application/resource contract, а не просто log stream.

Telemetry может отражать эти события, но не заменяет authoritative current state/history.

---

# 6. Идентификаторы корреляции

Observability использует разные IDs по их смыслу:

```text
trace_id / span_id
operation_id
correlation_id
job_id / attempt_id
browser_session_id / action_id
content_id
provider_id
worker_id / generation
```

Нельзя сводить всё к одному `request_id`.

---

# 7. `operation_id`

Каждая application Operation имеет `operation_id` из `application-contracts.md`.

Он должен присутствовать:

- в structured logs текущей operation;
- в application error diagnostic context;
- в downstream provider/worker correlation metadata настолько, насколько это безопасно;
- в trace span attributes.

`operation_id` не используется как metric label из-за высокой cardinality.

---

# 8. Transport request ID

REST/MCP transport может иметь собственный request/message ID.

Он связывается с `operation_id`, но не заменяет его.

Один transport request потенциально может инициировать несколько internal operations в composed flow.

---

# 9. Distributed tracing direction

Целевое направление — OpenTelemetry-compatible tracing.

Tracing должен поддерживать propagation как минимум через:

```text
REST/MCP ingress
→ Application
→ Search/Retrieval upstream calls
→ Browser Worker RPC/message
→ ContentStore/DB/Redis operations
```

Не все library spans обязаны быть включены с первой версии; application-level spans имеют приоритет.

---

# 10. Async Job tracing

Нельзя держать один trace span открытым часы до завершения durable Job.

Предпочтительная модель:

```text
Job create operation trace
→ заканчивается после durable admission

Job attempt
→ новый trace
→ link/correlation к job_id + origin trace context
```

Retry attempt получает отдельный trace, сохраняя `job_id`/attempt metadata.

---

# 11. Browser action tracing

Request-bound Browser action должен по возможности сохранять trace context через Control Plane → owning Browser Worker.

Worker action span должен позволять отделить:

- queue/routing wait;
- target resolution;
- Playwright actionability wait;
- action execution;
- download/content finalization;
- response transport.

Full page content не добавляется в trace attributes.

---

# 12. Trace sampling

Production tracing должно поддерживать configurable sampling.

High-volume successful Search/Retrieval может sampling-иться сильнее, а:

- errors;
- unknown outcomes;
- security rejections;
- worker loss;
- slow operations

могут сохраняться по отдельной policy.

Точная sampling policy deployment-specific.

---

# 13. Structured logging

Logs должны быть machine-readable structured records.

Canonical fields по возможности включают:

```text
timestamp
level
event/code
message
service/runtime
operation_id
trace_id/span_id
component
outcome/error category
provider/worker/resource refs при необходимости
safe structured details
```

Не следует строить diagnostics на regex parsing свободного текста.

---

# 14. Log event code

Для значимых событий желательно стабильное machine-readable `event`/`code` поле.

Примеры:

```text
search.provider.timeout
retrieval.ssrf.rejected
content.parser.failed
browser.session.lost
browser.action.unknown
job.attempt.lost
outbox.publish.retry
```

Human-readable message может быть русским.

---

# 15. Logging context propagation

Application/runtime code не должен вручную передавать `operation_id` в каждый logger call отдельным аргументом, если context propagation может быть реализована централизованно.

Допустимо использовать contextvars/log context adapter.

При этом background task обязан явно восстановить/создать свой execution context, а не случайно наследовать context другого request после reuse worker-а.

---

# 16. Redaction

Используются требования `security.md`.

По умолчанию в logs не попадают:

- Authorization/Cookie;
- provider API keys;
- browser storage/cookies;
- request/response body;
- page content;
- uploaded/downloaded bytes;
- query parameters с secret/token;
- local paths;
- raw stack trace в user-visible error.

---

# 17. Search query logging

Search query может содержать personal/sensitive information.

Полный query text не является обязательным production log field.

Для диагностики допускаются configurable:

- length;
- hash/fingerprint;
- redacted preview в secure debug environment;
- provider_id;
- result count.

Metric labels никогда не содержат raw query.

---

# 18. URL logging

Полный URL может содержать secrets/PII в query string.

По умолчанию telemetry использует:

- scheme;
- normalized host;
- redacted path/query policy;
- URL fingerprint при необходимости.

Raw URL может попадать только в защищённый diagnostic context согласно policy.

---

# 19. Metrics principles

Metrics должны иметь низкую/контролируемую cardinality.

Разрешённые типичные labels:

```text
component
operation_type
outcome
error_category
provider_id
runtime_type
job_type
browser_profile
cache_result
```

Запрещены как labels:

- operation_id;
- job_id;
- session_id;
- content_id;
- raw URL;
- search query;
- user ID, если cardinality unbounded.

---

# 20. Metrics implementation direction

Целевой внешний формат должен быть Prometheus/OpenMetrics-compatible или эквивалентно стандартный для выбранного deployment.

Metrics endpoint относится к operational surface и не является application REST API.

Точная Python instrumentation library фиксируется implementation/version plan.

---

# 21. Общие operation metrics

Минимально:

```text
operations_total{component, operation_type, outcome}
operation_duration_seconds{component, operation_type}
operation_inflight{component, operation_type}
operation_errors_total{component, error_category}
```

Набор/имена могут быть уточнены implementation style guide, но semantics должны сохраняться.

---

# 22. Search metrics

Минимально:

- query items total;
- provider calls total;
- provider latency;
- cache hits/misses;
- provider errors/timeouts/rate limits;
- results count distribution;
- retries;
- billable calls/usage units;
- provider readiness.

---

# 23. Retrieval metrics

Минимально:

- fetch items total;
- request latency;
- bytes received;
- redirects;
- timeout stage;
- HTTP status class;
- SSRF/policy rejects;
- response-too-large/decompression rejects;
- Content ingest failures;
- per-host/global concurrency utilization без raw host high cardinality metrics по умолчанию.

---

# 24. Content metrics

Минимально:

- ingested bytes/objects;
- detected format family;
- parser calls/duration/outcomes;
- parser execution profile;
- derived representation bytes;
- parser timeout/crash/unsupported;
- reuse/cache hits derived representation;
- ContentStore latency/errors;
- orphan/reconciliation events;
- retention cleanup.

Format label должен быть bounded registry value.

---

# 25. Browser metrics

Минимально:

- active sessions;
- session create/close/expire/lost;
- sessions per worker;
- worker capacity/utilization;
- action total/duration/outcome/type;
- action queue wait;
- stale target;
- unknown outcome;
- popups/downloads/uploads;
- blocked network requests;
- worker heartbeat/drain/loss;
- reaper cleanup;
- browser/page crashes.

---

# 26. Jobs metrics

Минимально:

- jobs by state/type;
- creates/admission rejects;
- queue latency;
- attempts;
- retries;
- attempt duration;
- lease expiry/lost attempt;
- cancellation latency;
- outbox backlog/oldest age;
- outbox publish retries;
- duplicate queue messages;
- claim conflicts;
- reconciler actions;
- terminal outcomes.

---

# 27. Database/Redis/ContentStore metrics

Infrastructure instrumentation должна показывать:

- DB pool utilization;
- query/transaction latency;
- transaction rollback/error;
- Redis operation latency/error;
- queue depth;
- cache hit/miss;
- ContentStore latency/bytes/error;
- storage capacity/usage где доступно.

Нельзя создавать metric label по SQL text/Redis key/resource ID.

---

# 28. Health model — три уровня

Нужно различать:

```text
liveness
readiness
capability status/degraded state
```

Один `/health` boolean недостаточен.

---

# 29. Liveness

Liveness отвечает только:

> Жив ли process/runtime и способен ли он выполнять собственный event loop/control logic?

Liveness **не должна** падать только потому, что:

- PostgreSQL временно недоступен;
- SearXNG недоступен;
- Redis недоступен;
- Browser Worker pool пуст.

Иначе orchestrator создаёт restart storm вместо восстановления dependency.

---

# 30. Readiness

Readiness отвечает:

> Может ли конкретный runtime безопасно принимать новый класс работы, для которого он зарегистрирован?

Readiness учитывает только dependencies, обязательные для runtime/capability correctness.

Control Plane может оставаться ready/degraded для Search/Retrieval, даже если Browser capability недоступна.

---

# 31. Capability-aware status

Control Plane должен иметь detailed status model:

```text
service_status = ready | degraded | unavailable

capabilities:
  search: ready/degraded/unavailable
  retrieval: ...
  content: ...
  browser: ...
  jobs: ...

providers/dependencies:
  postgres
  redis
  content_store
  searxng
  yandex
  browser_pool
```

Точный REST representation проектируется позднее.

---

# 32. Degraded не равен unready

Пример:

```text
Yandex unavailable
SearXNG ready
→ Search = ready/degraded
→ Web Access остаётся serving
```

или:

```text
Browser workers unavailable
→ Browser = unavailable
→ Search/Retrieval могут оставаться ready
```

Это позволяет capability-level degradation вместо полного outage.

---

# 33. Mandatory dependencies configuration

Некоторые dependencies могут стать обязательными по deployment policy.

Например будущая auth architecture может сделать PostgreSQL/security service обязательными для всех public operations.

Readiness должна учитывать configured mandatory dependencies, а не жёстко считать PostgreSQL всегда optional/always required.

---

# 34. Control Plane readiness

Control Plane readiness требует как минимум:

- configuration/bootstrap завершён;
- event loop работает;
- mandatory security/policy dependencies доступны;
- transport server способен принимать request;
- system не находится в shutdown/drain.

Отдельные capability dependencies отражаются detailed status.

---

# 35. Job Worker readiness

Job Worker ready, если:

- bootstrap завершён;
- поддерживаемые job type revisions загружены;
- PostgreSQL/JobRepository доступны;
- queue/coordination доступна;
- worker не draining;
- capacity позволяет claim работу.

Отсутствие конкретного external provider может сделать отдельный job type degraded, но не обязательно весь worker unready, если он обслуживает несколько типов.

---

# 36. Browser Worker readiness

Browser Worker status должен различать:

- alive;
- browser runtime initialized;
- accepting sessions;
- at capacity;
- draining;
- failed.

`at_capacity` не означает process unhealthy; placement просто не назначает новые sessions.

---

# 37. Dependency probes не должны создавать side effects/стоимость

Health check не должен:

- выполнять billable Yandex Search;
- открывать реальный внешний Browser URL;
- создавать durable Job;
- записывать большой ContentObject.

Используются дешёвые passive/lightweight probes или recent observed health.

---

# 38. Provider health

Search Provider status может основываться на комбинации:

- configuration validity;
- lightweight readiness call, если provider имеет безопасный endpoint;
- recent actual call results;
- circuit-breaker state, если он будет введён;
- explicit operator disable.

Health не должен автоматически переключать provider в application request.

---

# 39. Health freshness

Detailed status должен различать:

- текущую проверку;
- cached/recent health observation;
- timestamp последнего успешного/неуспешного probe.

Нельзя выдавать старый «healthy» как current fact без timestamp/TTL policy.

---

# 40. Startup diagnostics

При startup каждый runtime логирует безопасную configuration summary:

- runtime type/version;
- enabled components/providers;
- schema/migration compatibility;
- storage backend type;
- browser profile/runtime version;
- feature/capability revisions.

Secrets/credentials/URLs с tokens не логируются.

---

# 41. Version/build metadata

Operational status должен позволять узнать:

- application version;
- git/build revision, если доступно;
- schema compatibility revision;
- runtime type;
- startup time.

Это важно при rolling deployment и mixed replicas.

---

# 42. Configuration revision

Если provider/policy/browser profile configuration имеет revision, она должна быть observable в safe form.

Это помогает понять, почему разные результаты были получены до/после configuration change.

---

# 43. Slow operation diagnostics

Для operation, превысившей configured slow threshold, log/trace должен показывать decomposition настолько, насколько это возможно:

- queue wait;
- DB wait;
- provider latency;
- parser time;
- Browser actionability wait;
- ContentStore transfer.

Slow threshold configurable и не меняет operation deadline.

---

# 44. Error aggregation

Repeated identical infrastructure errors должны быть metric/alert friendly, но logs могут использовать rate limiting/coalescing, чтобы outage provider-а не создавал бесконечный log flood.

Coalescing не должно скрывать первый/последний error и total count.

---

# 45. Alerts

Design должен позволять alerting как минимум на:

- control plane unavailable;
- PostgreSQL connectivity/pool exhaustion;
- Redis unavailable/queue backlog;
- ContentStore failures;
- default Search provider unavailable;
- Browser Worker pool zero-ready;
- high BrowserSession lost rate;
- high unknown-outcome rate;
- outbox oldest pending age;
- Job retry storm/lease loss;
- reaper/resource leak backlog;
- security rejection anomaly;
- disk/storage capacity exhaustion.

Точные thresholds/SLO задаются deployment/release policy.

---

# 46. SLO/SLI foundation

До production release необходимо определить измеримые SLI:

- availability по capability;
- latency percentiles request-bound operations;
- Job queue/admission/completion latency;
- Browser session creation/action latency;
- error/unknown outcome rates;
- resource leak/reconciliation backlog.

Design не фиксирует arbitrary target numbers до нагрузочного baseline.

---

# 47. No content in metrics

Page text, search snippets, filenames, document text и browser console message не являются metric labels.

Если нужно измерять parser format/provider — используется bounded normalized enum.

---

# 48. Diagnostic endpoints и authorization

Detailed diagnostics могут раскрывать:

- provider names/status;
- queue/backlog;
- worker topology;
- storage usage;
- build/config revisions.

Такая информация не обязана быть публичной.

REST design должен разделить:

- basic liveness/readiness для orchestrator;
- authorized detailed operational diagnostics.

---

# 49. MCP observability surface

MCP agent не должен получать инфраструктурный monitoring toolbox без необходимости.

Если capability недоступна, MCP получает нормализованный application error/hint.

Operator diagnostics остаются REST/metrics/logging surface.

---

# 50. Browser console/network не равны service telemetry

Page console/network event buffers являются Browser application diagnostics и недоверенным web content.

Они не должны автоматически записываться как service logs с тем же trust level.

Например `console.error("password=...")` не должен попасть в production service log автоматически.

---

# 51. Audit integrity

Если отдельный durable audit признан security-critical, его запись должна быть включена в соответствующую transaction/application guarantee или иметь собственный reliable delivery mechanism.

Нельзя назвать обычный best-effort log «audit», если его потеря допустима.

Точный audit persistence design определяется после auth/admin capability design.

---

# 52. Observability failures

Failure telemetry exporter-а:

- не должен блокировать request бесконечно;
- не должен исчерпывать RAM unbounded queue;
- должен деградировать bounded/drop policy с собственным health metric/log;
- не меняет успешный application outcome, если telemetry не является обязательным audit requirement.

---

# 53. Metrics/traces backpressure

Telemetry exporter buffers bounded.

При backend outage система может сбрасывать sampled telemetry согласно policy, но не создавать cascading outage application runtime.

---

# 54. Testability

Observability code должно быть тестируемым через fake/in-memory sinks без real Prometheus/OTel collector.

Application tests не должны зависеть от внешнего monitoring backend.

---

# 55. Unit tests

Необходимо проверить:

1. operation context попадает в structured log context;
2. sensitive fields redacted;
3. metric labels bounded/no resource ID;
4. provider/query/URL privacy policy;
5. liveness не падает из-за optional dependency;
6. degraded capability отражается отдельно;
7. Browser `at_capacity` не считается worker crash;
8. Job async attempt создаёт новый trace/link semantics;
9. untrusted browser console не логируется автоматически;
10. telemetry sink failure не ломает normal operation.

---

# 56. Integration/chaos tests

Сценарии:

- PostgreSQL outage/recovery;
- Redis outage/recovery;
- SearXNG outage;
- Yandex disabled/unavailable;
- ContentStore outage;
- zero Browser Workers;
- Browser Worker at capacity;
- Job Worker loss;
- outbox backlog;
- telemetry collector unavailable.

Detailed health/status должен отражать реальную capability degradation.

---

# 57. Acceptance criteria Observability

Observability считается реализованным, если:

1. Все application operations имеют operation_id и structured timing/outcome telemetry.
2. Logs структурированы и имеют redaction.
3. Metrics не содержат high-cardinality resource/user/query/URL labels.
4. Tracing проходит через provider/Browser Worker boundaries настолько, насколько transport поддерживает.
5. Job attempts имеют отдельные traces, а не бесконечный trace Job lifetime.
6. Liveness не зависит от optional external dependencies.
7. Capability-aware status различает ready/degraded/unavailable.
8. Browser Worker capacity/drain различимы от crash.
9. Durable audit отделён от telemetry.
10. Search/Browser web content не смешивается с trusted service logs.
11. Outbox/job/browser leak backlogs имеют metrics/alertable signals.
12. Telemetry backend failure не создаёт unbounded memory/cascading outage.
13. Operator diagnostics можно защитить authorization отдельно от public liveness.
14. Release/load tests могут измерять latency/error/SLO baseline.

---

# 58. Open questions

До implementation Observability необходимо закрыть:

1. Конкретный logging stack: stdlib JSON formatter vs structured logging library.
2. Конкретный OpenTelemetry SDK/exporters и sampling policy.
3. Prometheus/OpenMetrics library/endpoint integration.
4. Exact health/status schema и endpoint paths.
5. Что считается mandatory dependency для Control Plane первой версии.
6. Durable audit scope и storage после auth/admin design.
7. Trace context propagation через выбранный Browser Worker transport.
8. Job origin trace link storage format.
9. Alert/SLO thresholds после первого load baseline.
10. Нужна ли отдельная operator diagnostics API surface или достаточно REST admin namespace + metrics.

Эти вопросы не меняют основные trust/cardinality/health/telemetry boundaries этого документа.
