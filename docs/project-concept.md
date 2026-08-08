# Концепция проекта Web Access MCP

## Статус документа

Этот документ фиксирует общее направление проекта `web-access-mcp-server` и архитектурные принципы, которых следует придерживаться при дальнейшей разработке.

Это **не полноценный design document и не окончательная спецификация**. Здесь намеренно не фиксируются точные REST endpoints, MCP tool schemas, таблицы PostgreSQL, Redis-протоколы, лимиты, timeout-значения, полный roadmap и другие детали, которые должны проектироваться отдельно.

Главная задача документа — удерживать правильную предметную границу проекта и не дать ему превратиться в набор разрозненных MCP-инструментов, монолитный web-scraper или универсальный document-processing комбайн.

---

## 1. Назначение проекта

`Web Access MCP` — самостоятельный production-oriented микросервис, предоставляющий программируемый доступ к вебу для ИИ-агентов и других клиентов.

Сервис должен объединять несколько классов возможностей:

- поиск информации в интернете;
- безопасное получение известных HTTP(S)-ресурсов;
- дешёвую идентификацию и непосредственное чтение поддерживаемого содержимого;
- хранение исходных и производных представлений контента;
- полноценную stateful-работу с браузером;
- длительные и фоновые веб-операции, когда они действительно нужны;
- инфраструктурные механизмы масштабирования, наблюдаемости, ограничения нагрузки и восстановления после сбоев.

Сервис создаётся не как одноразовый MVP, локальный скрипт или обёртка вокруг одного поискового API. Он должен быть пригоден для постоянного использования в собственном ИИ-агенте и для подключения других клиентов в будущем.

Архитектура изначально должна учитывать многопользовательскую эксплуатацию, горизонтальное масштабирование и независимый жизненный цикл сервиса.

---

## 2. Backend-first подход

Основной принцип проектирования:

```text
предметные задачи сервиса
        ↓
domain/application backend
        ↓
infrastructure adapters
        ↓
единые application operations
        ↓
        ├── REST facade
        └── MCP facade
```

MCP-инструменты не должны определять внутреннюю архитектуру backend-а.

Сначала необходимо спроектировать прикладные операции, модели, жизненные циклы, persistence, concurrency, cancellation, failure model и security boundaries. Только после этого поверх готового application layer проектируются два независимых фасада:

- REST API — полный программный интерфейс к возможностям сервиса;
- MCP — компактный и понятный ИИ-агенту facade над теми же application capabilities.

REST и MCP не обязаны иметь одинаковые request/response schemas.

---

## 3. Единый backend для REST и MCP

REST и MCP должны использовать один и тот же application layer и одну и ту же бизнес-логику.

Недопустима архитектура, в которой:

- MCP имеет отдельную реализацию поиска;
- REST отдельно реализует retrieval;
- browser lifecycle частично живёт в transport layer;
- одинаковые security rules дублируются в нескольких фасадах.

Transport layer отвечает только за представление входных данных, transport-specific mapping/validation, transport context и преобразование application result во внешний response contract.

Фактическое выполнение операции принадлежит application/backend слою.

---

## 4. Роль REST API

REST API является полным прямым интерфейсом к backend-функционалу.

Он предназначен потенциально для:

- других микросервисов;
- web UI;
- административного интерфейса;
- debugging и diagnostics;
- просмотра job history;
- работы с большими content objects;
- provider controls;
- эксплуатационных и интеграционных задач.

REST может быть существенно подробнее MCP и раскрывать низкоуровневые, но стабильные application capabilities, если это полезно программным клиентам.

При этом REST не должен без необходимости протекать во внутреннюю реализацию конкретной библиотеки или provider-а.

---

## 5. Роль MCP

MCP — agent-facing facade над общим backend-ом.

Он должен быть:

- компактным;
- семантически понятным LLM;
- практически эффективным настолько же, насколько REST для основных задач;
- свободным от ненужных инфраструктурных параметров;
- построенным вокруг агентных намерений, а не внутренних backend-команд.

MCP не является копией REST API.

Имена tools, docstrings, descriptions полей, пояснения ошибок и другая информация, предназначенная для агента, должны быть преимущественно **на русском языке**, поскольку русский является основным языком проекта и это упрощает сопровождение. Технические идентификаторы, имена функций, классов, полей и error codes могут оставаться английскими.

JSON Schema MCP-инструмента следует считать частью agent UX, а не побочным продуктом Python-типизации.

Runtime обязан самостоятельно валидировать arguments. Нельзя полагаться на то, что LLM прочитала JSON Schema и обязательно сформирует корректный вызов.

---

## 6. Web Access не принимает решения за агента

Сервис является инфраструктурным и прикладным мостом между агентом и веб-средой.

Он не должен скрыто подменять reasoning агента эвристиками.

Сервис не должен сам решать, например:

- что результатов поиска «слишком мало»;
- что необходимо автоматически переключиться на другой search provider;
- что HTTP-страницу следует автоматически открыть в браузере;
- что сканированный PDF следует автоматически отправить в OCR;
- что legacy Office-документ следует автоматически конвертировать через LibreOffice;
- по какой ссылке агенту нужно перейти дальше;
- какую стратегию исследования следует выбрать.

Backend должен сообщать наблюдаемые факты: что было запрошено, что фактически выполнено, что получено и какие ограничения, ошибки или предупреждения возникли.

Решение о следующем смысловом шаге остаётся за вызывающим агентом или другим клиентом.

Конфигурационные инфраструктурные политики — лимиты, backpressure, разрешённые providers, timeout, quota и security rules — являются нормальной ответственностью сервиса и не считаются reasoning-эвристиками.

### Structured hints вместо скрытого fallback

Web Access может помогать LLM или другому клиенту **структурированными рекомендациями**, если они непосредственно следуют из наблюдаемого результата операции.

Подсказка:

- не выполняет следующую операцию автоматически;
- не изменяет фактический результат текущей операции;
- должна быть объяснима конкретными diagnostics;
- предпочтительно указывает на capability самого Web Access;
- не должна выдавать внешний инструмент за гарантированно доступный;
- для внешних инструментов формулируется как осторожная рекомендация класса решения.

Примеры допустимой семантики:

```text
HTML получен, но непосредственно доступного содержимого почти нет
→ можно рекомендовать browser capability самого Web Access

PDF не содержит доступного text layer
→ сообщить, что native parsing не дал текста и дальнейшее чтение может потребовать OCR/document-processing tool

legacy Office format не имеет встроенного native parser
→ можно рекомендовать отдельный document-conversion/document-processing workflow

изображение содержит только доступные metadata
→ сообщить, что OCR/semantic visual reading находится за пределами native parsing
```

Подсказки должны быть особенно точными, когда они относятся к инструментарию самого сервиса. Рекомендации по использованию внешних систем должны быть более осторожными и не должны становиться скрытой зависимостью Web Access.

---

## 7. Основные предметные подсистемы

На текущем уровне проект следует рассматривать как совокупность нескольких независимых, но связанных областей:

```text
Web Access
├── Search
├── Retrieval
├── Content
├── Browser
├── Jobs
└── Diagnostics / Observability
```

Сложное document/media processing намеренно не является отдельной подсистемой Web Access.

---

## 8. Search

Search отвечает за выполнение поисковых запросов и нормализацию результатов внешних search providers.

Предварительная модель:

```text
SearchApplicationService
        ↓
SearchProvider
        ├── SearXNGProvider
        ├── YandexSearchProvider
        └── future providers
```

Основным бесплатным search backend предполагается собственный экземпляр SearXNG.

Дополнительные providers, включая существующий Yandex Search API, должны подключаться через adapters.

Выбор provider должен быть явным application/configuration решением. Не следует хардкодить скрытые эвристики вроде автоматического переключения provider-а по количеству результатов.

Независимые stateless операции следует проектировать batch-first там, где это естественно: один и несколько поисковых запросов используют один и тот же application contract.

Search не читает найденные страницы и не выполняет сложную обработку их содержимого.

---

## 9. Retrieval

Retrieval отвечает за безопасное получение известных HTTP(S)-ресурсов без браузерного взаимодействия.

Основной принцип:

```text
HTTP retrieval ≠ browser runtime
```

Retrieval не должен автоматически превращаться в browser operation на основании скрытой оценки содержимого.

Типовой pipeline:

```text
URL validation
→ security / SSRF checks
→ DNS/IP validation
→ HTTP request
→ redirect validation
→ streaming read
→ size/decompression limits
→ response metadata
→ preliminary content identification
→ raw ContentObject
```

Для сетевого клиента предполагается async HTTPX.

Retrieval отвечает за сеть, bytes и transport-level metadata, но не за OCR, semantic parsing или визуальное понимание файла.

---

## 10. Content

`Content` отвечает за уже полученное содержимое: его идентификацию, дешёвую инспекцию, непосредственный разбор поддерживаемых форматов, управление производными представлениями и хранение.

Content не должен превращаться в универсальный document/media-processing engine.

### Три уровня обработки

Для архитектуры вводится концептуальное разделение:

```text
L0 — Inspection
L1 — Native Parsing
L2 — Advanced Processing
```

### L0 — Inspection

Дешёвая, детерминированная идентификация и инспекция уже полученного содержимого.

Примеры:

- фактический формат и MIME;
- размер и hash;
- container type;
- page count;
- dimensions;
- basic document/image/media metadata;
- наличие или отсутствие непосредственно доступного text layer;
- encryption/protection flags, если они доступны без сложной обработки.

Inspection не пытается понять смысл документа, изображения, аудио или видео.

### L1 — Native Parsing

Непосредственное чтение уже доступной структуры формата без OCR, visual understanding, browser rendering, speech recognition и тяжёлой конвертации.

Примеры:

```text
HTML → текст, metadata, links, JSON-LD
PDF с text layer → текст по страницам
JSON → structured object
XML/FB2/SVG → доступная XML-структура и текстовые элементы
CSV → строки/колонки
DOCX → непосредственно доступный текст/таблицы
XLSX → sheets/cells
PPTX → slides/text
EPUB → главы и текст
TXT → текст
```

Поддержка конкретного формата добавляется только при наличии достаточно надёжного и ограничиваемого native parser.

Native Parsing не должен автоматически переходить к L2, если результат отсутствует или недостаточен.

### L2 — Advanced Processing

К этому классу относятся операции вроде:

- OCR сканированных PDF и изображений;
- layout recognition;
- VLM/vision understanding;
- LibreOffice-конвертация legacy/сложных офисных форматов;
- speech-to-text;
- semantic video/image analysis;
- сложное восстановление таблиц и визуальной структуры;
- другие CPU/GPU-heavy document/media workflows.

**L2 не является ответственностью Web Access.**

Для него может существовать отдельный document/media-processing сервис, Python/sandbox или другой специализированный инструмент.

Если Web Access не может получить пригодное представление через L0/L1, он возвращает raw content, diagnostics и при необходимости structured hint, но не запускает L2 автоматически.

### Определение формата

Нельзя полагаться только на расширение URL или filename.

Определение должно учитывать:

```text
URL/filename hint
+
declared Content-Type
+
magic bytes / container inspection
+
security policy
```

URL без расширения может вернуть XLSX или PDF; `*.plx.pdf` остаётся PDF, если фактическое содержимое действительно является PDF; HTTP `Content-Type` может быть ошибочным.

### Representations и provenance

Content должен позволять хранить исходное содержимое и производные representations с явным происхождением.

Концептуально:

```text
raw PDF
├── native text
├── native metadata
└── внешнее OCR-представление, если его позднее создал другой processor

raw HTML
├── native text/Markdown
├── metadata
└── links/structured data
```

Производное представление не заменяет оригинал.

В дальнейшем необходимо предусмотреть provenance: из какого `ContentObject` получено представление, каким parser/processor и какой версией.

### ContentStore

Большие материалы нельзя безусловно передавать через MCP result или хранить как огромный JSON в PostgreSQL.

Проект должен с самого начала иметь абстракцию `ContentStore`.

Предварительные реализации:

```text
FilesystemContentStore
S3CompatibleContentStore
```

Локальная установка не должна требовать внешнего S3.

PostgreSQL хранит metadata, references, provenance и lifecycle-информацию, но не обязан быть blob storage для всего полученного веб-контента.

---

## 11. Browser runtime

Browser является отдельной stateful подсистемой и не должен быть скрытой частью Retrieval.

Предварительные понятия:

```text
BrowserService
BrowserSession
BrowserPage
BrowserAction
BrowserSnapshot
```

Базовым browser automation engine предполагается Playwright с Chromium.

Предпочтительным первоначальным вариантом является официальный Python Playwright, чтобы основной стек проекта оставался единым.

Browser runtime должен иметь отдельную границу выполнения:

```text
API/MCP process
       ↓
BrowserCoordinator
       ↓
BrowserWorker
       ↓
Playwright / Chromium
```

Жизненный цикл BrowserSession не зависит от жизненного цикла MCP connection:

```text
MCP reconnect/disconnect
≠ BrowserSession close
```

Stateful browser operations используют собственные opaque handles.

Фактические объекты Playwright (`Browser`, `BrowserContext`, `Page`, `Locator`) живут только в browser worker process. PostgreSQL/Redis могут хранить coordination metadata, но не сериализованный Playwright state.

Сервер остаётся окончательным владельцем cleanup и обязан иметь собственные TTL/reaper механизмы независимо от best-effort cleanup со стороны клиента.

---

## 12. Stateful browser actions и ordering

Внутри одной BrowserSession действия могут зависеть от результата предыдущих действий, поэтому batch-first принцип не должен механически применяться к stateful transitions.

```text
click
→ navigation/state change
→ snapshot
→ next decision
```

В пределах одной browser session должна быть обеспечена корректная последовательность mutating actions. Несколько browser sessions могут исполняться параллельно в пределах ресурсов и policy сервиса.

При потере transport response после возможного side effect результат операции может быть неопределённым. Такие операции нельзя слепо автоматически повторять.

---

## 13. PostgreSQL

Базовый persistence stack:

```text
PostgreSQL
SQLAlchemy 2 async
asyncpg
Alembic
```

PostgreSQL рассматривается как authoritative durable storage для структурированной информации: operations/jobs, events, result metadata, upstream diagnostics, content metadata/provenance, browser session metadata, audit и usage/accounting.

Точная схема БД должна проектироваться отдельно.

Важно не превращать каждую короткую synchronous operation в durable queue job только потому, что PostgreSQL присутствует в архитектуре.

---

## 14. Redis

Redis должен поддерживаться архитектурой с самого начала, но его роли необходимо явно разделять.

Предварительно Redis может использоваться для:

- cache;
- rate limiting;
- distributed locks;
- arq job queue;
- browser worker registry;
- short-lived browser routing metadata;
- leases/fencing;
- event delivery/coordination;
- backpressure-related state.

Транспорт команд к owning browser worker требует отдельного технического решения после анализа latency, ordering, cancellation, retries, worker crash semantics, backpressure и horizontal scaling.

---

## 15. Jobs и execution paths

Web Access не должен пропускать каждую операцию через durable queue.

Предполагаются как минимум два execution path.

### Request-bound operations

Короткие операции, результат которых нужен вызывающему клиенту непосредственно в рамках текущего запроса:

- search;
- retrieval;
- content inspection/native parsing;
- чтение content object;
- большинство browser actions.

Они могут вести observability/audit records, но не обязаны становиться durable jobs.

### Durable jobs

Операции, которые по своей природе являются длительными, фоновыми или требуют устойчивости к разрыву клиентского соединения:

- crawl;
- большие batch operations;
- длительные операции, остающиеся в пределах ответственности Web Access;
- фоновые workflows.

Для них предполагается паттерн:

```text
PostgreSQL durable state
→ Redis / arq
→ worker
→ persisted result/events
```

Точный набор durable operations определяется их семантикой, а не скрытой эвристикой размера результата.

---

## 16. Application layer

Не следует заранее строить один огромный `CommandExecutor` для всей системы.

Предварительная декомпозиция:

```text
SearchApplicationService
RetrievalApplicationService
ContentApplicationService
BrowserApplicationService
JobApplicationService
```

Подсистемы должны использовать общие базовые contracts, например `ExecutionContext`, `OperationResult`, `OperationError`, `OperationEvent`.

Application layer не должен зависеть от FastAPI router или FastMCP tool.

---

## 17. Infrastructure adapters

Внешние системы и библиотеки должны находиться за явными ports/adapters.

Примеры:

```text
SearchProvider
HttpFetcher
ContentStore
ContentInspector
NativeContentParser
BrowserWorkerClient
JobQueue
Cache
Repositories
```

Это позволяет тестировать application layer без реального интернета, заменять providers и storage backends, а также изменять worker transport без переписывания MCP и REST facades.

---

## 18. Предварительный технологический стек

| Задача | Технология / направление |
|---|---|
| Язык | Python 3.11+ |
| HTTP application | FastAPI |
| MCP transport | FastMCP 3.x |
| Schemas/config | Pydantic v2 + pydantic-settings |
| HTTP clients | HTTPX async |
| Database | PostgreSQL |
| ORM | SQLAlchemy 2 async |
| PostgreSQL driver | asyncpg |
| Migrations | Alembic |
| Redis | Redis 7+ |
| Durable jobs | arq |
| Бесплатный search backend | собственный SearXNG |
| Дополнительный search | provider adapters, включая Yandex Search |
| Native HTML parsing | Trafilatura как один из кандидатов для main-content parsing |
| Structural HTML parsing | определить отдельным решением (`lxml` / `selectolax` / другой) |
| Native PDF text parsing | pypdf с resource limits для доступного text layer |
| MIME detection | declared type + content sniffing; возможен libmagic/python-magic |
| Browser automation | Playwright Python |
| Browser engine | Chromium |
| Large content | `ContentStore`: filesystem + S3-compatible adapter |
| Tests | pytest + pytest-asyncio + jsonschema и интеграционные тесты |
| Deployment | Docker / Docker Compose с архитектурой, готовой к горизонтальному масштабированию |

Это направление, а не окончательный lock-файл. Конкретные зависимости и версии должны фиксироваться после отдельных технических решений и проверок совместимости.

---

## 19. Failure model и observability

Ошибки проектируются как часть application contract, а не как случайные exceptions transport layer.

Необходимо предусмотреть устойчивую taxonomy для validation, policy/security rejection, upstream failure, timeout, rate limiting, resource unavailable/expired/lost, cancellation, queue/worker failure и `unknown outcome` для операций с возможным side effect.

Production-ready сервис должен иметь архитектурные точки для structured logging, correlation IDs, operation/job history, upstream diagnostics, timings, provider usage, cache statistics, browser worker health, resource lifecycle, metrics и tracing.

Observability не должна требовать превращения каждой операции в durable job.

---

## 20. Security boundary

Web Access будет обрабатывать недоверенные URL, страницы, документы и browser state, поэтому security является частью архитектуры, а не поздним дополнением.

Необходимо проектировать отдельно SSRF protection, egress policy, DNS rebinding protection, redirect validation, size/decompression limits, browser isolation, process/container boundaries, file/download handling, secret isolation, permissions, safe logging, cleanup и resource quotas.

BrowserContext следует считать изоляцией browser state, но не общей security sandbox.

---

## 21. Принципы будущего MCP surface

Окончательный каталог пока не фиксируется, но уже приняты общие правила:

- один intent — один canonical tool;
- независимые stateless операции проектируются batch-first;
- stateful sequential operations не batch-ятся механически;
- schema является частью интерфейса агента;
- каждое публичное поле должно иметь понятное описание и machine-readable constraints;
- MCP остаётся agent-facing, а не provider-facing;
- validation errors должны помогать агенту исправить вызов;
- tool annotations должны отражать реальные execution semantics;
- structured hints могут рекомендовать следующий шаг, но не выполнять его автоматически.

---

## 22. Совместимость с собственным ИИ-агентом

Web Access MCP является самостоятельным сервисом и не должен зависеть от внутренних классов `internet-search-bot`.

Интеграция осуществляется через стабильный MCP contract. Со стороны агента сервис предполагается использовать как builtin MCP service.

Агент отвечает за reasoning, orchestration, пользовательский progress, trusted presentation metadata, ownership opaque remote handles со своей стороны и best-effort cleanup requests.

Web Access отвечает за фактическое выполнение веб-операций, безопасное взаимодействие с внешним вебом, проверку handles, внутренний resource lifecycle, server-side TTL/reaper и окончательную очистку собственных ресурсов.

MCP transport lifecycle не должен становиться владельцем stateful remote resources.

---

## 23. Масштабирование

Проект должен оставаться удобным локально, но архитектура не должна предполагать единственный process или единственного пользователя.

Нужно сохранять возможность независимо масштабировать API/MCP control plane, durable job workers, browser workers, SearXNG, PostgreSQL, Redis и content storage.

Stateful browser routing необходимо проектировать так, чтобы любой API instance мог принять запрос и направить действие worker-у, который действительно владеет BrowserSession.

---

## 24. Что пока не фиксируется

Этот концептуальный документ намеренно не определяет:

- окончательный список MCP-tools;
- точные MCP input/output schemas;
- REST endpoint tree;
- таблицы PostgreSQL;
- Redis keys/streams/channels;
- точные job types;
- конкретный browser-worker transport;
- точные TTL, timeout и limits;
- окончательную error taxonomy;
- authentication/authorization protocol;
- persistent browser profiles;
- exact crawling semantics;
- version roadmap.

Эти решения должны приниматься последовательно в отдельных design documents и ADR.

---

## 25. Критерий правильности архитектуры

Новая возможность должна добавляться примерно по цепочке:

```text
новая предметная capability
→ application contract
→ infrastructure adapter при необходимости
→ tests
→ REST mapping
→ компактный MCP mapping
```

и при этом не требовать переписывания Agent Runtime, дублирования логики REST/MCP, раскрытия provider-specific деталей агенту, привязки stateful resource к transport connection, превращения короткой операции в durable job без причины или скрытой reasoning-эвристики.

---

## 26. Следующий этап проектирования

Следующий этап после этой концепции — подробное проектирование backend surface по областям:

1. Search.
2. Retrieval.
3. Content: Inspection, Native Parsing, representations и storage.
4. Browser.
5. Jobs.
6. Diagnostics/observability.
7. Security and policy.

Для каждой области нужно определить application operations, domain models, ports, lifecycle, persistence, concurrency, cancellation, failure semantics и acceptance criteria.

После стабилизации backend design можно проектировать:

```text
REST API — полный программный facade
MCP — компактный русскоязычный agent-facing facade
```
