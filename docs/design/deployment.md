# Deployment и scaling design

## Статус документа

Этот документ является каноническим владельцем **deployment topology, configuration profiles, process/container boundaries, rolling deployment и operational scaling direction** Web Access MCP.

Он не привязывает production к конкретному orchestrator. Docker Compose является обязательным локальным/reference deployment, но архитектура должна переноситься на другой runtime без изменения application contracts.

---

# 1. Deployment goals

Сервис должен одновременно обеспечивать:

- запуск разработчиком одной командой;
- воспроизводимые images/dependencies;
- отдельные runtime boundaries;
- горизонтальное масштабирование;
- graceful restart;
- least privilege networking;
- безопасное хранение secrets;
- migration discipline;
- capability-aware health;
- возможность managed PostgreSQL/Redis/S3 в production.

---

# 2. Runtime components

Основные deployable workloads:

```text
web-access-api             Control Plane
web-access-worker          Job Worker
web-access-browser-worker  Browser Worker
outbox-publisher           durable Job outbox publisher/reconciler role
migration                  one-shot Alembic workload
```

Infrastructure dependencies:

```text
PostgreSQL
Redis
SearXNG
ContentStore
reverse proxy / ingress
observability backend (external/optional)
```

Outbox publisher может позднее быть объединён с отдельным runtime loop, если HA/ownership semantics остаются корректными; design не требует отдельный container любой ценой.

---

# 3. Control Plane deployment

`web-access-api` запускает один application с:

```text
FastAPI
├── /api/v1/...
└── /mcp (Streamable HTTP)
```

REST и MCP используют общий bootstrap/lifespan/application services.

API image не содержит живой BrowserSession state.

---

# 4. API scaling

Control Plane масштабируется горизонтально:

```text
api-1
api-2
...
api-N
```

за reverse proxy/load balancer.

Корректность не зависит от sticky sessions.

Sticky routing может использоваться как performance optimization только если система остаётся корректной при попадании следующего request на другой replica.

---

# 5. Job Worker scaling

Job Workers образуют worker pool.

Scale factor зависит от:

- queue backlog;
- job type;
- CPU/RAM;
- provider capacity;
- Content processing load.

Worker registration должен сообщать supported job type/revisions.

---

# 6. Browser Worker scaling

Browser Workers масштабируются независимо от Job Workers.

Placement учитывает:

- ready/draining;
- capacity;
- browser/profile revision;
- resource pressure.

Новые sessions не назначаются draining/at-capacity worker-ам.

---

# 7. Browser session affinity — внутренняя

Client/load balancer не обязан знать owning Browser Worker.

```text
client
→ любой API replica
→ shared routing metadata
→ owning Browser Worker
```

Нельзя решать Browser ownership через public sticky cookie client-а.

---

# 8. Reference Docker Compose

Reference Compose должен поднимать минимум:

```text
postgres
redis
searxng
migration
api
job-worker
browser-worker
outbox-publisher/reconciler role
gateway (если используется для stable ingress)
```

ContentStore по умолчанию local development может использовать named/shared volume.

Optional Compose profile может поднимать S3-compatible storage (например MinIO) для integration/scaling tests, но application не зависит от конкретного продукта.

---

# 9. «Одна команда» не означает один process

Local developer UX:

```text
docker compose up --build
```

может запускать все компоненты автоматически.

Это не повод объединять API, Browser Worker, Redis и PostgreSQL в один process/container.

---

# 10. Network exposure

По умолчанию наружу публикуется только ingress/API endpoint.

Не публикуются на host/public interface без отдельной operator необходимости:

- PostgreSQL;
- Redis;
- Browser Worker internal endpoint;
- Outbox publisher;
- internal SearXNG;
- ContentStore internal endpoint/credentials.

---

# 11. Logical networks

Reference deployment должен разделять connectivity по минимально необходимым связям.

Концептуально:

```text
ingress network
  gateway ↔ api

service/control network
  api ↔ browser worker internal protocol
  api/workers ↔ required persistence/coordination

search network/egress
  api ↔ searxng
  searxng ↔ internet search engines

browser egress
  browser worker ↔ public internet
  private/internal egress blocked
```

Точный Docker network layout зависит от выбранного Browser transport и storage access model.

---

# 12. Browser Worker least privilege

Browser Worker production container:

- non-root;
- Chromium sandbox enabled;
- no privileged mode;
- no Docker socket;
- no host PID namespace;
- no unrestricted host filesystem;
- minimal Linux capabilities;
- seccomp/apparmor policy, где platform поддерживает;
- bounded CPU/RAM/PIDs/temp disk;
- private/internal egress restrictions.

---

# 13. Shared memory для Chromium

Chromium должен получать достаточный `/dev/shm`/shared-memory budget.

Security-first deployment не должен автоматически использовать host IPC namespace только ради convenience.

Предпочтителен explicit bounded shared-memory/tmpfs configuration, проверенный load tests.

Конкретные размеры определяются benchmark.

---

# 14. Browser temporary storage

Browser Worker имеет отдельное ephemeral storage для:

- profile/context temp data;
- temporary downloads;
- screenshots до Content handoff;
- browser cache.

Temp storage:

- bounded;
- не shared как public ContentStore;
- очищается на session/worker cleanup;
- может быть tmpfs/ephemeral volume согласно size profile.

---

# 15. Browser Content handoff

Точный путь Browser Worker → ContentStore остаётся связанным с Browser transport/security ADR.

Допустимые направления:

1. Worker stream-ит artifact Control Plane/internal Content ingest endpoint.
2. Worker получает минимально scoped access к ContentStore staging.
3. Другой internal transfer service/port.

Нельзя просто вернуть local path и ожидать, что другой replica его увидит.

---

# 16. PostgreSQL deployment

Local:

- container;
- persistent named volume;
- healthcheck;
- не exposed public.

Production:

- managed PostgreSQL или HA deployment;
- backups/PITR;
- connection limits/pooling;
- TLS/service network policy;
- monitored storage/replication.

Application uses one PostgreSQL contract независимо от placement.

---

# 17. Redis deployment

Local:

- container;
- internal network;
- persistence mode может быть включён для developer convenience/restart tests.

Production:

- HA/managed Redis по required availability;
- memory/maxmemory policy согласована cache/queue/coordination use;
- protected network/auth/TLS при необходимости.

Redis persistence не заменяет PostgreSQL durable Job state/outbox.

---

# 18. Redis memory classes

Cache и queue/coordination могут иметь разные eviction requirements.

Нельзя настроить один global `allkeys-lru`, если это может удалить queue/lease data, необходимую runtime correctness.

При необходимости используются:

- разные Redis logical deployments/instances;
- non-evicting DB для coordination;
- отдельный cache instance.

Точное разделение определяется load/capacity design.

---

# 19. SearXNG deployment

SearXNG — отдельный internal service.

Требования:

- private/internal access от Web Access;
- JSON API configured;
- engine configuration version-controlled/operator-managed;
- own rate/limiter settings;
- outbound internet access;
- health/observability;
- не публиковать admin/search UI наружу без необходимости.

Web Access adapter не управляет SearXNG container lifecycle.

---

# 20. Yandex/provider secrets

Search provider credentials передаются через secret configuration.

Они не записываются в image/repository/.env production.

Local `.env` допустим только как developer mechanism с `.gitignore` и example config без secrets.

---

# 21. ContentStore profiles

Минимальные deployment profiles:

## Local filesystem

- shared/persistent volume;
- простой developer deployment;
- один host или shared volume semantics.

## S3-compatible

- production/horizontal scaling;
- object storage;
- scoped credentials;
- server-side durability policy.

Application chooses adapter via configuration.

---

# 22. Filesystem ContentStore scaling limit

Local filesystem adapter не считается universal production backend для multi-host replicas.

Если API/Job/Browser workers находятся на разных hosts, storage должен быть shared с корректной consistency semantics или заменён S3-compatible adapter.

Docs/config должны явно предупреждать об этом.

---

# 23. Migration workload

Database migrations выполняет отдельный one-shot command/container:

```text
alembic upgrade head
```

Application startup не запускает destructive auto-migrations.

Compose может выражать dependency:

```text
postgres healthy
→ migration success
→ api/workers start
```

---

# 24. Migration concurrency

В production миграцию выполняет один controlled deployment step.

Несколько API replicas не должны одновременно пытаться мигрировать schema на startup.

---

# 25. Rolling schema compatibility

Для deployments с rolling replicas используются expand/contract migrations из `persistence.md`.

New code сначала должен работать с расширенной schema, пока old replicas ещё живы.

Removal/contract выполняется только после завершения migration window.

---

# 26. Configuration

Configuration загружается централизованно через typed settings layer.

Категории:

- runtime/application;
- PostgreSQL;
- Redis;
- ContentStore;
- Search providers;
- browser profile/capacity;
- security/egress;
- retention;
- observability;
- job policies.

Не следует передавать настройки через random module-level environment reads.

---

# 27. Configuration validation

Startup должен fail-fast при некорректной **обязательной** configuration:

- malformed DB URL;
- invalid limits;
- enabled provider без required credential;
- incompatible browser profile;
- невозможная retention/capacity relation.

Optional disabled provider не мешает startup.

---

# 28. Configuration revision

Versionable/operator-managed configuration должна иметь observable revision/hash там, где изменение влияет на:

- provider behavior;
- cache semantics;
- browser profiles;
- security policy;
- parser registry.

Secret values не входят в readable revision output.

---

# 29. Secret sources

Архитектура должна поддерживать как минимум:

- environment variables для local/simple deployments;
- Docker/Kubernetes secrets/files;
- future external secret manager/reference.

Application code получает resolved secret через configuration port и не логирует его.

---

# 30. Image build

Production images строятся reproducibly.

Требования:

- pinned Python dependencies/lock;
- no `pip install latest` at container startup;
- no `npx @latest` runtime download;
- Playwright package/browser binary versions compatible;
- minimal runtime image layers;
- build metadata/version embedded safely.

---

# 31. Browser image

Browser Worker image может базироваться на официальном/version-pinned Playwright-compatible image или собственном image с необходимыми browser dependencies.

Критерии выбора:

- exact Playwright/browser version match;
- sandbox support;
- non-root user;
- reproducible build;
- security patchability;
- image size/startup tradeoff.

Конкретный Dockerfile фиксируется version implementation plan.

---

# 32. API/Worker images

Можно использовать один Python application base image с разными entrypoints или отдельные optimized images.

Выбор не должен смешивать runtime boundaries.

Если Browser dependencies значительно увеличивают image, Browser Worker имеет отдельный image.

---

# 33. Health probes

Используется model `observability.md`.

Containers/orchestrator получают:

- liveness probe;
- readiness probe;
- startup grace для тяжёлых runtimes.

Detailed capability status не используется как aggressive restart signal.

---

# 34. Graceful API shutdown

Deployment должен дать API достаточный termination grace:

1. mark not-ready/draining;
2. stop new requests;
3. finish/cancel bounded request-bound work;
4. close clients/pools;
5. exit.

Shutdown API replica не закрывает BrowserSessions сервиса и не отменяет Jobs.

---

# 35. Graceful Job Worker shutdown

1. worker draining;
2. stop claim new work;
3. bounded finish active attempts;
4. renew/close leases корректно;
5. если process убит — lease expiry/reconciler восстанавливает state.

Orchestrator grace timeout должен согласовываться с job attempt policy.

---

# 36. Graceful Browser Worker shutdown

Rolling shutdown Browser Worker:

1. mark draining;
2. placement перестаёт назначать новые sessions;
3. существующие sessions продолжают обслуживаться в drain window;
4. sessions, закрытые клиентом/TTL, освобождаются;
5. по достижении maximum drain deadline оставшиеся contexts закрываются;
6. affected sessions получают `closed/expired/lost` согласно доказуемой lifecycle semantics.

Прозрачная миграция live BrowserContext на новый worker не предполагается.

---

# 37. Browser rolling deployment

New Browser Worker revision запускается alongside old.

Placement выдаёт новые sessions только compatible new/current workers согласно rollout policy.

Old workers draining до закрытия sessions или bounded deadline.

Это позволяет обновлять Playwright/browser image без мгновенной потери всех sessions.

---

# 38. Contract compatibility Browser workers

Worker registration сообщает protocol/runtime revision.

Control Plane не dispatch action worker-у с incompatible command schema.

Mixed version deployment разрешён только в documented compatibility range.

---

# 39. Job Worker rolling deployment

Job message содержит stable job_id/type/revision.

New/old workers claim только поддерживаемые job revisions.

Queued Job не должен случайно исполняться incompatible worker version.

Version roadmap определяет migration queued jobs при breaking changes.

---

# 40. Outbox publisher HA

Outbox publisher должен поддерживать безопасный restart и, при необходимости, несколько replicas через concurrent DB claim/lock semantics.

Publisher crash не теряет message: pending outbox остаётся в PostgreSQL.

---

# 41. Reconciler HA

Reaper/reconciler loops должны быть:

- idempotent;
- safe при concurrent instances;
- lease/DB-lock protected там, где нужно;
- bounded batch;
- observable.

Нельзя полагаться на «у нас всегда ровно один API process».

---

# 42. Startup order не является correctness guarantee

Compose `depends_on` полезен для UX, но runtime обязан переживать dependency restart после startup.

API/worker reconnect/recovery logic не может полагаться, что PostgreSQL/Redis/SearXNG больше никогда не перезапустится.

---

# 43. Dependency restart

Expected scenarios:

- PostgreSQL restart;
- Redis restart;
- SearXNG restart;
- ContentStore transient outage;
- Browser Worker restart;
- API replica restart;
- Job Worker restart.

Connection pools/clients должны иметь bounded reconnection/recovery semantics без process corruption.

---

# 44. Browser Worker crash

Orchestrator может restart worker, но новая generation **не восстанавливает автоматически старые live BrowserSessions**.

Reconciliation переводит старые sessions в `lost`.

Новый process регистрируется новой generation и принимает новые sessions.

---

# 45. Capacity configuration

Runtime resource limits задаются config/deployment:

- API max concurrency;
- HTTP connection pools;
- Search provider concurrency;
- Job Worker concurrency;
- Browser sessions per worker;
- pages/session;
- browser action queue;
- parser process pool;
- Content bytes;
- batch limits.

Не следует использовать unbounded defaults библиотек.

---

# 46. Autoscaling signals

Возможные будущие autoscaling signals:

## API

- CPU;
- request inflight/latency.

## Job Workers

- queue depth;
- oldest queued age;
- running jobs;
- CPU.

## Browser Workers

- active sessions/capacity;
- memory/CPU;
- session creation rejection.

Autoscaling не является обязательной функцией Web Access itself; сервис предоставляет metrics.

---

# 47. Backpressure before autoscaling

Даже при autoscaling runtime обязан иметь hard capacity/backpressure.

Нельзя рассчитывать, что orchestrator всегда успеет добавить worker до OOM.

---

# 48. Reverse proxy / gateway

Reference Compose может использовать Nginx или другой простой reverse proxy для:

- единого ingress;
- TLS termination в local/reference profile;
- request limits/timeouts;
- routing REST/MCP.

Конкретный proxy не является application dependency.

Production может использовать cloud LB/Ingress controller.

---

# 49. MCP streaming proxy compatibility

Reverse proxy configuration должна корректно поддерживать Streamable HTTP MCP:

- streaming/chunking;
- connection timeout;
- buffering settings;
- headers/auth;
- graceful disconnect.

Proxy buffering не должен ломать MCP response streaming/progress.

---

# 50. REST streaming proxy compatibility

Content download/SSE также требуют корректной proxy streaming configuration.

Request/response buffering ограничивается согласно endpoint type.

---

# 51. TLS

Public/remote ingress использует TLS.

TLS termination может быть gateway/load balancer.

Internal service traffic может использовать private network + service auth; mTLS добавляется согласно threat model/deployment environment.

---

# 52. Service authentication

Builtin MCP endpoint не считается защищённым только потому, что internal.

Требуется scoped service authentication от собственного Agent/service client.

Точный mechanism (bearer token, mTLS, workload identity) остаётся deployment/auth ADR.

Browser Worker internal protocol также требует отдельную service identity.

---

# 53. Firewall / egress

Production network policy должна различать:

```text
API/Search egress
Browser egress
SearXNG egress
internal persistence
```

Browser Worker public internet access не должен автоматически давать доступ к PostgreSQL/internal metadata network.

---

# 54. DNS

Retrieval/Browser SSRF design требует контролируемого resolver/network path.

Deployment не должен незаметно отправлять часть запросов через proxy/resolver, который имеет иной доступ к internal network и обходит application assumptions.

Proxy/DNS architecture документируется как security-sensitive config.

---

# 55. Resource quotas at runtime

Container/system resource limits являются defense-in-depth дополнением application quotas.

Browser Worker особенно получает:

- memory limit;
- CPU quota;
- PID limit;
- temp disk quota;
- shared-memory bound.

Job/parser workers также bounded.

---

# 56. OOM behavior

OOM kill worker не должен разрушать durable correctness:

- Job attempt lease expires → retry/fail;
- Browser Worker sessions → lost;
- API request fails/retries client-side according semantics;
- Content staged orphans reconcile.

System design не рассчитывает на `finally` при OOM.

---

# 57. Backups

Production PostgreSQL:

- regular backups;
- tested restore;
- PITR where required.

ContentStore:

- durability/backup lifecycle согласно retention/product requirements.

Redis backup не является способом восстановить authoritative Job/Content/Browser metadata.

---

# 58. Disaster recovery

DR runbook должен понимать различия:

```text
DB restored
→ durable metadata/jobs recovered

ContentStore потерян
→ metadata может ссылаться на missing payload → reconciliation/error

Redis lost
→ queues/cache/routing rebuild/reconcile from durable state where possible

Browser workers lost
→ live sessions irrecoverably lost
```

Это реальные разные failure domains.

---

# 59. Redis loss recovery

После полного Redis loss:

- Search cache cold;
- outbox republish pending/required Jobs;
- running Job leases reconcile;
- Browser routing registry rebuildляется из live worker registration + durable sessions, при невозможности подтвердить session → lost;
- rate-limit counters reset согласно documented degraded/security policy.

Если reset rate limits создаёт security risk, deployment должен fail closed для соответствующей capability до восстановления enforcement.

---

# 60. ContentStore recovery

Metadata без payload не выдаётся как successful ContentObject data.

Content read возвращает normalized missing/corrupt payload error.

Reconciliation отмечает/обрабатывает broken objects согласно Content lifecycle.

---

# 61. Configuration profiles

Минимальные profiles:

```text
local
ci/test
production
```

### local

- Compose;
- local PostgreSQL/Redis/SearXNG;
- filesystem ContentStore;
- один Browser Worker;
- удобные defaults.

### ci/test

- deterministic fixtures/services;
- isolated volumes;
- reduced limits/timeouts;
- no billable providers by default.

### production

- external/HA persistence where appropriate;
- strong auth/network policy;
- explicit resource limits;
- monitoring/backups.

---

# 62. Development without Docker

Python application components могут запускаться локально вне Docker для development/unit testing.

Но Browser/Redis/PostgreSQL/SearXNG integration profile документируется через Compose как canonical reproducible environment.

Architecture не зависит от Windows-only/local process paths.

---

# 63. Cross-platform developer support

Repository должен оставаться удобным для Windows developer host через Docker Desktop/Compose.

Runtime paths внутри containers POSIX и не должны сохранять host-specific absolute paths в application metadata.

---

# 64. CI images/services

CI использует pinned service images/versions.

Billable Yandex/live external search не запускается обычным CI.

SearXNG/provider adapter integration использует controlled instance/mocks/recorded protocol fixtures там, где возможно.

Real-browser Playwright integration запускается в dedicated job/image.

---

# 65. Build artifacts

CI должен уметь собирать:

- application image;
- Browser Worker image;
- migration image/command;
- version metadata/SBOM по выбранной supply-chain policy.

Обязательный registry publishing определяется release process позднее.

---

# 66. Dependency scanning

Production pipeline должен поддерживать:

- Python dependency vulnerability scan;
- container image scan;
- secret scan;
- optional SBOM/license report.

Security scan warning policy определяется release gates.

---

# 67. Deployment smoke test

После Compose/production deploy выполняются smoke checks:

- liveness/readiness;
- PostgreSQL migration revision;
- Redis connectivity;
- SearXNG provider readiness;
- filesystem/S3 Content roundtrip;
- Browser Worker registration/session create/close;
- Job create/outbox/worker roundtrip на synthetic job;
- REST/MCP discovery.

Никаких billable/external side effects.

---

# 68. Rolling deployment test

CI/staging должен проверять хотя бы одну mixed-version rollout simulation для изменений, затрагивающих:

- DB schema;
- Job message revision;
- Browser Worker protocol;
- MCP tool schema/agent compatibility.

Breaking runtime protocol не выкатывается без coordinated drain/migration.

---

# 69. Version compatibility metadata

Runtime health/registration сообщает:

- application version;
- build/git revision;
- DB schema compatibility range;
- Browser Worker protocol revision;
- Job worker capability revisions;
- MCP integration/schema revision;
- parser registry revision при необходимости.

Secrets не входят metadata.

---

# 70. Release configuration immutability

Критичные production config changes должны быть traceable/revisioned.

Нельзя менять security/provider/browser profile поведение «вручную внутри container» без observable configuration change.

Exact config management platform deployment-specific.

---

# 71. Acceptance criteria Deployment

Deployment считается спроектированным/реализованным, если:

1. `docker compose up` поднимает полный local stack.
2. API/MCP, Job Worker и Browser Worker остаются разными runtimes.
3. PostgreSQL/Redis не exposed public по умолчанию.
4. Browser Worker non-root/sandboxed/least-privilege.
5. Migrations выполняются отдельным step до application rollout.
6. API масштабируется без sticky correctness dependency.
7. BrowserSession routeable через shared ownership metadata.
8. Browser Worker drain не принимает новые sessions.
9. Worker restart не притворяется восстановлением old live sessions.
10. Job Worker rolling versions claim только compatible jobs.
11. Outbox/reconciler переживают restart/duplicate publishers.
12. Filesystem ContentStore clearly local/single-host profile; S3-compatible adapter поддерживает horizontal deployment.
13. Dependency restart не требует restart всей системы.
14. Capability-aware health используется orchestrator/diagnostics.
15. Resource limits/backpressure существуют до autoscaling.
16. Secrets не bake-ятся в images/logs.
17. Proxy поддерживает MCP/Content streaming.
18. Backup/restore/Redis-loss/browser-loss semantics документированы и testable.

---

# 72. Open questions

До production implementation необходимо закрыть:

1. Reverse proxy в reference Compose: Nginx или другой выбранный компонент.
2. Browser Worker internal transport/service auth.
3. Browser Worker direct Redis/DB/ContentStore permissions.
4. Production ContentStore recommendation (конкретный S3-compatible implementation не обязан быть частью приложения).
5. Redis single vs split cache/coordination deployments.
6. Outbox publisher process placement/HA.
7. Exact Docker base images/Python version/browser image.
8. Exact seccomp profile/browser network policy.
9. Auth mechanism Agent ↔ MCP/REST.
10. Deployment platform target после Docker Compose (Kubernetes/VM/systemd/etc.), если нужен официальный production profile.
11. Exact backup/PITR/retention requirements.
12. Autoscaling recommendations после load tests.
13. Build registry/release artifact strategy.
14. Observability collector/reference stack.

Эти вопросы не меняют основную process/network/persistence topology.
