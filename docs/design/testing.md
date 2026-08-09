# Testing strategy Web Access MCP

## Статус документа

Этот документ является каноническим владельцем **уровней тестирования, test environments, determinism, race/fault/security/load testing и CI strategy** Web Access MCP.

Acceptance отдельных версий ссылается на эту стратегию и `release-gates.md`.

---

# 1. Главный принцип

Тесты должны проверять не только happy-path функции, но и **архитектурные invariants**:

- dependency boundaries;
- application contracts;
- persistence consistency;
- remote resource lifecycle;
- restart/recovery;
- concurrency/races;
- security;
- actual REST/MCP schemas;
- production-like process topology.

Высокий unit coverage без этих проверок не считается достаточным.

---

# 2. Уровни тестирования

Canonical test classes:

```text
Static / architecture checks
Unit
Contract/schema
Component integration
Infrastructure integration
End-to-end
Concurrency/race
Fault-injection/recovery
Security/adversarial
Load
Soak/leak
Live external smoke (optional controlled profile)
```

Каждый уровень имеет собственную цель и не заменяет соседний.

---

# 3. Repository test layout

Предварительно:

```text
tests/
├── unit/
├── contract/
├── integration/
├── e2e/
├── race/
├── fault/
├── security/
├── load/
├── fixtures/
└── helpers/
```

Структура может группироваться по component, но смысл test class должен быть очевиден.

---

# 4. Static checks

PR baseline должен включать:

- formatting;
- linting;
- type checking;
- import/dependency rules;
- dead/broken imports;
- config/schema validation;
- docs links/consistency при наличии tooling;
- migration heads consistency.

Точные tools (`ruff`, `mypy`/`pyright` и т.п.) выбираются version implementation plan.

---

# 5. Architecture dependency tests

Автоматически проверяются правила `dependency-rules.md`.

Минимум:

- `domain` не импортирует application/transport/infrastructure/workers;
- `application` не импортирует FastAPI/FastMCP/SQLAlchemy/Redis/Playwright concrete modules;
- REST/MCP не импортируют concrete providers/repositories;
- MCP не вызывает REST;
- REST не вызывает MCP;
- workers не содержат duplicate application business logic.

Можно использовать AST/import graph tooling или custom tests.

---

# 6. Unit tests

Unit tests:

- быстрые;
- deterministic;
- не требуют Docker/network;
- используют fake ports;
- проверяют application/domain semantics.

Unit suite не должен случайно обращаться к интернету/Redis/PostgreSQL.

Network должен быть запрещён/перехвачен там, где это practically реализуемо.

---

# 7. Property-based tests

Для сложных input/state spaces рекомендуется property-based testing.

Кандидаты:

- URL normalization/SSRF inputs;
- batch aggregate outcome;
- resource state transitions;
- cursor encoding/decoding;
- retry/backoff bounds;
- parser limits;
- Job lifecycle transitions.

Hypothesis или эквивалентный Python инструмент может быть выбран implementation plan.

---

# 8. State-machine tests

BrowserSession/Job/Content lifecycle полезно проверять model/state-machine tests.

Запрещённые transitions должны гарантированно rejected.

Пример:

```text
closed BrowserSession → click
```

никогда не должен случайно вернуться в `ready`.

---

# 9. Contract tests application

Общие contracts тестируются отдельно:

- OperationOutcome invariants;
- error/warning/hint separation;
- batch order/partial success;
- deadline/cancellation propagation;
- `unknown` semantics;
- opaque resource refs;
- ownership checks.

Component tests не должны независимо изобретать эти assertions.

---

# 10. Actual MCP schema tests

FastMCP server поднимается в test context, после чего schema получается **реальным MCP client-ом** через tool discovery.

Проверяется actual client-visible contract:

- tool catalog;
- descriptions;
- nested field descriptions;
- required/default/enums/limits;
- oneOf/discriminators;
- annotations;
- hidden Context absence;
- no provider/internal fields.

Нельзя считать `Model.model_json_schema()` достаточной проверкой MCP output.

---

# 11. MCP catalog snapshot

Expected tool names/categories хранятся как contract snapshot/explicit assertion.

Unexpected add/remove/rename ломает test и требует design/version review.

Snapshot не должен использоваться для giant brittle serialization всего schema, если точечные semantic tests дают более устойчивую проверку.

---

# 12. Actual OpenAPI tests

Тест получает schema от реального FastAPI app.

Проверяется:

- endpoint tree;
- operationId uniqueness/stability;
- request/response schemas;
- descriptions;
- security schemes;
- common errors;
- binary media types;
- no infrastructure leakage;
- deprecation/version markers.

---

# 13. REST/MCP parity tests

Для capabilities, доступных через оба facade, проверяется semantic parity:

```text
одинаковый application input meaning
→ одинаковый canonical outcome/data semantics
```

REST и MCP serialization могут различаться, но не должны получать разные business result из-за duplicate logic.

---

# 14. PostgreSQL integration tests

Persistence tests используют **реальный PostgreSQL**, а не SQLite substitute для critical semantics.

Проверяются:

- migrations;
- constraints;
- transactions;
- optimistic revision;
- `FOR UPDATE`/locking;
- outbox;
- concurrent claim;
- retention/reconciliation queries.

Каждый test получает isolated schema/database/transaction strategy.

---

# 15. Redis integration tests

Реальный Redis используется для:

- queue adapter;
- cache;
- rate limit;
- leases/locks;
- worker registry/routing, когда design выбран;
- outbox publisher integration.

Проверяются restart/flush/duplicate delivery scenarios.

---

# 16. ContentStore integration tests

Минимум два adapter profiles:

- filesystem;
- S3-compatible test backend, когда adapter реализован.

Одинаковый contract suite запускается против обоих adapters.

Проверяются:

- streaming write/read;
- finalize;
- hash/integrity;
- missing object;
- range, если поддерживается;
- concurrent refs;
- cleanup/orphans.

---

# 17. Controlled HTTP test server

Retrieval tests используют локальный controlled server, способный программно воспроизводить:

- redirects;
- redirect loops;
- arbitrary status;
- chunked streaming;
- slow response;
- reset connection;
- gzip/compression expansion;
- wrong Content-Type;
- malformed headers;
- large payload;
- empty payload;
- downloadable content.

Это лучше случайных публичных сайтов.

---

# 18. Controlled web application для Browser

Нужен собственный deterministic test site/app с routes/scenarios:

- static page;
- SPA dynamic DOM;
- delayed element;
- popup/new tab;
- form controls;
- checkbox/radio/select;
- keyboard submit;
- hover menu;
- drag/drop;
- iframe;
- shadow DOM;
- dialog;
- download;
- upload;
- console logs;
- XHR/fetch/WebSocket;
- page crash/error simulation;
- attempt private-network subresource.

Browser tests не зависят от layout Google/другого внешнего сайта.

---

# 19. Real Playwright integration

Browser integration suite запускает реальный Chromium/Playwright worker.

Fake worker нужен для application unit tests, но не заменяет:

- actionability;
- BrowserContext isolation;
- popup/download behavior;
- crash/restart;
- actual snapshot/element-ref resolution.

---

# 20. SearXNG integration

Search adapter тестируется против controlled/private SearXNG test instance/profile или stable protocol fixture.

Не следует утверждать exact ranking публичной выдачи как CI invariant.

Проверяется protocol mapping/normalization, а не «первый результат всегда example.com».

---

# 21. Yandex integration profiles

Обычный PR CI не выполняет billable Yandex calls.

Уровни:

```text
unit/provider protocol fixtures
optional manually-triggered live smoke with secret/budget
```

Live smoke имеет hard request budget и не запускается fork/untrusted CI.

---

# 22. Format/parser fixtures

Каждый Native Parser получает versioned fixture corpus.

Минимум:

- valid minimal;
- representative;
- empty/no-native-content;
- malformed;
- truncated;
- oversized/limit;
- spoofed extension/MIME;
- security/adversarial case;
- deterministic expected schema/output properties.

Fixtures не должны нарушать licensing/privacy.

---

# 23. Golden outputs

Golden files полезны для stable structured parsers/snapshots, но применяются осторожно.

Не следует snapshot-ить огромный binary/text output целиком, если достаточно проверить:

- schema;
- key fields;
- normalized text fragments/hash;
- deterministic ordering.

Golden update требует review, а не blind regeneration.

---

# 24. Migration tests

Обязательно:

- empty DB → head;
- current previous supported schema → head;
- downgrade только если project policy его обещает;
- expand/contract compatibility test для rolling migration;
- migration data backfill fixtures;
- multiple-head detection.

Migration smoke запускается до application e2e.

---

# 25. End-to-end tests

E2E использует full Compose-like topology:

```text
REST/MCP client
→ API
→ PostgreSQL/Redis/SearXNG/ContentStore
→ Job/Browser Worker
```

Representative flows:

1. Search → fetch → native content.
2. Fetch JS shell → hint → Browser create/navigate/snapshot/content → close.
3. Browser click → popup/download → ContentRef.
4. Content parse existing raw object.
5. Durable Job create → outbox → worker → result → read.
6. Partial batch failure.
7. MCP discovery/schema/call.
8. REST owner isolation.

---

# 26. No hidden L2 E2E

Scanned PDF E2E должен подтверждать:

```text
raw PDF saved
native text unavailable
hint advanced_processing_may_be_required
```

и **нулевые OCR/VLM/LibreOffice calls** внутри Web Access.

---

# 27. Concurrency/race suite

Race tests должны многократно повторять critical interleavings.

Основные классы:

### Resources

- close vs access;
- expiration vs operation;
- cleanup vs retry;
- cross-owner concurrent access.

### Browser

- two actions same session;
- action vs close;
- action vs reaper;
- duplicate action delivery;
- stale worker/fencing;
- download vs close;
- popup vs close.

### Jobs

- duplicate queue delivery;
- two claims;
- cancel vs completion;
- retry vs cancel;
- stale attempt late result;
- reconciler concurrency.

### Content

- duplicate ingest;
- finalize vs cleanup;
- derived reuse race;
- orphan cleanup vs late finalize.

---

# 28. Randomized race tests

Critical state machines должны иметь randomized/repeated stress tests с controlled seeds.

Failed seed сохраняется в test report для воспроизведения.

Race suite не считается успешным после одного прохода.

---

# 29. Fault injection

Нужно искусственно создавать failure **между steps**, а не только возвращать exception в начале.

Примеры:

- DB commit succeeded, process dies before next step;
- Redis publish succeeded, acknowledgement lost;
- Browser action executed, response lost;
- Content bytes written, metadata finalize dies;
- Job Worker dies after claim;
- Redis routing record disappears;
- PostgreSQL restarts mid-operation.

---

# 30. Fault injection hooks

Implementation должна позволять deterministic test failpoints в critical paths без production behavior change.

Например test-only dependency/hook между:

```text
outbox publish
→ mark delivered
```

или:

```text
browser execute
→ send response
```

Это позволяет проверять именно crash windows.

---

# 31. Restart/recovery tests

Отдельно проверяются рестарты:

- API;
- Job Worker;
- Browser Worker;
- PostgreSQL;
- Redis;
- SearXNG;
- ContentStore emulator.

Expected recovery соответствует `deployment.md`/`persistence.md`.

---

# 32. Browser Worker restart

Test invariant:

```text
old BrowserSession
→ worker killed/restarted new generation
→ session becomes lost
→ не получает новый unrelated BrowserContext
```

Новая session после restart работает нормально.

---

# 33. Redis loss test

Полный Redis flush/restart должен проверить:

- cache cold recovery;
- Job outbox republish;
- duplicate-safe claims;
- Browser routing reconciliation/lost handling;
- capability readiness/degraded status.

Durable DB records не исчезают.

---

# 34. Security tests

Security suite строится по `security.md`.

Обязательные matrices:

- SSRF IPv4/IPv6/redirect/DNS;
- content spoof/decompression/archive/XML;
- cross-owner handles;
- Browser internal network;
- Browser isolation;
- upload/download path;
- auth/error redaction;
- active content serving;
- resource quota abuse;
- arbitrary-code capability denial.

---

# 35. URL fuzzing

URL parser/security policy должен получать adversarial corpus:

- alternative IP notations, если parser их принимает;
- IPv6 brackets/zones;
- IDN/punycode;
- encoded separators;
- userinfo;
- strange ports;
- redirect chains;
- mixed-case schemes/hosts;
- null/control characters;
- parser differential cases.

При fuzz failure сохраняется minimal reproducer.

---

# 36. File/parser fuzzing

Parser boundaries подходят для fuzz/property tests:

- malformed container;
- truncated magic bytes;
- hostile XML;
- deep nesting;
- huge counts declared in headers;
- malformed ZIP paths.

Fuzzing не обязан запускать все third-party native parsers в PR на миллионах inputs, но targeted corpus обязателен.

---

# 37. Load tests

Load testing разделяется по capability:

- Search throughput/provider limits;
- Retrieval concurrent hosts/bytes;
- Content parser CPU/memory;
- API mixed workload;
- Job queue/backlog;
- Browser session/action capacity;
- ContentStore throughput.

Один общий RPS number не характеризует систему.

---

# 38. Performance baselines

До установления hard SLO сначала собирается reproducible baseline на reference hardware/profile.

Для regression tests фиксируются допустимые relative/absolute budgets после измерений.

Нельзя придумать latency target без benchmark и затем оптимизировать несуществующую проблему.

---

# 39. Browser load tests

Измеряются:

- session create latency;
- RAM/context;
- contexts/worker;
- pages/session;
- action latency;
- crash rate;
- cleanup latency;
- worker drain time.

На основании этого выбираются default capacity limits.

---

# 40. Soak tests

Длительный soak нужен особенно для:

- Browser Worker;
- Content temp storage;
- connection pools;
- Redis queue/leases;
- Job reconciler.

Проверяются:

- memory growth;
- zombie Chromium processes;
- leaked BrowserContexts/pages;
- leaked temp files;
- DB connections;
- orphan Content;
- stale Redis keys/leases.

---

# 41. Leak invariants

После synthetic workload + cleanup:

```text
active browser contexts → baseline
open pages → baseline
pending temp downloads → 0/baseline
outbox backlog → 0
unclaimed stale jobs → 0
orphan staged content → 0 after reconciliation
```

Допуски для caches отдельно документируются.

---

# 42. Test isolation

Каждый integration/E2E test должен иметь isolated:

- owner/principal;
- DB rows/schema namespace;
- ContentStore prefix/temp dir;
- BrowserSession;
- queue/job IDs.

Tests не полагаются на порядок выполнения.

---

# 43. Parallel CI

Suite должен позволять parallel execution без shared fixed ports/filenames/resource IDs.

Controlled services используют dynamic ports/network aliases.

---

# 44. Time tests

TTL/retention/backoff tests не должны ждать реальные минуты/часы.

Application time abstractions/fake clock используются там, где возможно.

Интеграционные tests реального lease timeout используют сокращённый test profile.

---

# 45. Flaky tests

Flaky test считается defect, а не «нормой browser integration».

Запрещено лечить race простым `sleep(5)` без condition.

Используются:

- event/condition wait;
- deterministic controlled server;
- bounded retry только если сам тест проверяет eventual consistency;
- failure diagnostics/artifacts.

---

# 46. Test retries в CI

Автоматический retry failed test не должен скрывать flaky behavior.

Если CI platform rerun используется для диагностики, original failure остаётся visible и release gate учитывает flaky count.

---

# 47. Test artifacts

При failure сохраняются безопасные artifacts:

- logs;
- trace/correlation IDs;
- Playwright screenshot/trace только для test site;
- relevant container logs;
- DB/job state dump с redaction;
- failed seed;
- OpenAPI/MCP schema diff.

Production secrets не попадают в artifacts.

---

# 48. Browser trace/video в tests

Playwright tracing/video может включаться `retain-on-failure` в integration suite.

Не следует всегда записывать видео каждого CI action, если это создаёт огромные artifacts.

---

# 49. CI tiers

Предлагаемые tiers:

## PR fast gate

- static/type;
- unit;
- contract schemas;
- lightweight PostgreSQL/Redis integration;
- selected real Browser tests;
- security baseline.

## Full integration gate

- full component integrations;
- Compose E2E;
- migrations;
- browser matrix;
- fault/race subset.

## Nightly/adversarial

- randomized race loops;
- fuzzing;
- restart chaos;
- load/soak;
- larger parser corpus.

## Release gate

- all required suites;
- security scans;
- deployment/upgrade test;
- agent MCP integration;
- controlled optional live provider smoke.

---

# 50. No billable calls by default

PR/nightly tests по умолчанию выполняют:

```text
Yandex billable calls = 0
```

Live provider profile запускается только explicit workflow/manual secret context с budget.

---

# 51. No uncontrolled internet dependency

Core acceptance suite не должна падать из-за:

- Google UI change;
- external website downtime;
- internet unavailable;
- public SearXNG rate limit.

Internet/live tests являются отдельным non-deterministic profile.

---

# 52. Coverage

Line/branch coverage используется как diagnostic, но не является главным критерием качества.

Critical state transitions/failure branches должны иметь explicit tests даже при формально высоком coverage.

Coverage threshold может быть установлен после появления codebase и baseline.

---

# 53. Mutation testing

Для critical pure logic полезно рассмотреть mutation testing:

- outcome aggregation;
- URL policy;
- state machines;
- retry policy;
- ownership checks.

Не обязательно первой version, но release-hardening может использовать targeted mutation suite.

---

# 54. Documentation examples tests

JSON/schema/code snippets design docs, ставшие canonical contract examples, желательно проверять хотя бы через schema validation/embedded fixtures, чтобы документация не расходилась с implementation.

Version implementation plans должны обновлять examples при schema change.

---

# 55. Compatibility tests

При evolution REST/MCP:

- previous supported client request fixtures продолжают валидироваться;
- additive fields не ломают parser;
- old/new Browser Worker protocol compatibility проверяется rolling test;
- queued Job revision совместим с worker version;
- DB migration mixed-version scenario проверяется.

---

# 56. Own-agent integration tests

`internet-search-bot` compatibility проверяется отдельным integration profile:

- Streamable HTTP connect;
- list tools;
- get schema;
- call search/fetch;
- BrowserSession create/cleanup;
- agent trusted presentation metadata mapping;
- unknown outcome behavior;
- server restart/reconnect;
- content handles;
- optional Job lifecycle.

Этот suite может жить частично в одном/обоих repositories, но contract fixtures должны быть versioned.

---

# 57. Generic MCP client tests

Server должен проходить integration с standard MCP/FastMCP client независимо от custom Agent Runtime.

Нельзя тестировать только через `internet-search-bot` и случайно создать private protocol dependency.

---

# 58. Test data privacy

Fixtures не содержат:

- реальные personal credentials;
- production cookies;
- private documents;
- production API keys.

Synthetic data предпочтительна.

---

# 59. Test naming/reporting

Critical scenario test name должен описывать invariant/condition, например:

```text
test_browser_action_response_loss_returns_unknown_without_retry
```

а не:

```text
test_case_17
```

CI report группирует failures по component/gate.

---

# 60. Acceptance criteria Testing strategy

Testing foundation считается реализованным, если:

1. PR CI имеет static/unit/contract/integration baseline.
2. Architecture import rules автоматизированы.
3. Actual FastMCP schemas проверяются real client.
4. Actual OpenAPI проверяется real app.
5. Real PostgreSQL/Redis используются для critical persistence tests.
6. Controlled HTTP/web app исключают зависимость от random internet.
7. Real Chromium suite проверяет Browser lifecycle/actions.
8. Security SSRF/content/browser matrices автоматизированы.
9. Race/fault suites проверяют crash windows, а не только function exceptions.
10. Browser/Job/Content leak/soak tests существуют до production release.
11. Billable external calls отсутствуют default CI.
12. Failed randomized seed/artifacts воспроизводимы.
13. Flaky test считается failure quality gate.
14. Own-agent и generic MCP integration оба покрыты.
15. Migration/rolling compatibility тестируется до release.

---

# 61. Open questions

До implementation CI/testing необходимо закрыть:

1. Exact lint/type tools.
2. Test container orchestration: Docker Compose, testcontainers или hybrid.
3. Controlled HTTP/browser test app framework/placement.
4. Hypothesis/property-based scope первой версии.
5. Fault injection hook implementation.
6. Load tool (`k6`, Locust, custom async harness и т.п.).
7. Browser tracing artifact policy.
8. Coverage thresholds после code baseline.
9. Nightly schedule/resource budget.
10. Cross-repository own-agent contract test automation.
11. Live Yandex smoke budget/frequency.
12. Security scanning tools/release policies.

Эти решения уточняют tooling, но не меняют обязательные test classes и invariants.
