# Концепция проекта Web Access MCP

## Статус документа

Этот документ фиксирует общее направление проекта `web-access-mcp-server` и архитектурные принципы, которых следует придерживаться при дальнейшей разработке.

Это **не полноценный design document и не окончательная спецификация**. Здесь намеренно не фиксируются точные REST endpoints, MCP tool schemas, таблицы PostgreSQL, Redis-протоколы, лимиты, timeout-значения и другие детали, которые должны быть спроектированы отдельно после формирования полного backend-контракта.

Главная задача документа — не дать проекту преждевременно превратиться в набор разрозненных MCP-инструментов или в реализацию, построенную вокруг одного конкретного клиента.

---

## 1. Назначение проекта

`Web Access MCP` — самостоятельный production-oriented микросервис, предоставляющий программируемый доступ к вебу для ИИ-агентов и других клиентов.

Сервис должен объединить несколько классов возможностей:

- поиск информации в интернете;
- безопасное получение известных HTTP(S)-ресурсов;
- извлечение содержимого и метаданных из веб-страниц и документов;
- хранение и выдачу больших полученных материалов;
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

Сначала необходимо спроектировать полноценные прикладные операции, модели, жизненные циклы, persistence, concurrency, cancellation, failure model и security boundaries. Только после этого поверх готового application layer проектируются два независимых фасада:

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
- одинаковые правила безопасности дублируются в нескольких фасадах.

Transport layer должен отвечать только за:

- представление входных данных;
- transport-specific validation и mapping;
- авторизацию/transport context;
- преобразование application result в удобный response contract.

Фактическое выполнение операции принадлежит application/backend слою.

---

## 4. Роль REST API

REST API является полным прямым интерфейсом к backend-функционалу.

Он предназначен не только для ИИ-агентов, но и потенциально для:

- других микросервисов;
- web UI;
- административного интерфейса;
- debugging и diagnostics;
- просмотра job history;
- работы с большими content objects;
- provider controls;
- эксплуатационных и интеграционных задач.

REST может быть существенно подробнее MCP и раскрывать низкоуровневые, но стабильные application capabilities, если это полезно программным клиентам.

При этом REST не должен протекать напрямую во внутреннюю реализацию конкретного provider-а или библиотеки без архитектурной необходимости.

---

## 5. Роль MCP

MCP — agent-facing facade над общим backend-ом.

Он должен быть:

- компактным;
- семантически понятным LLM;
- практически эффективным настолько же, насколько REST для основных задач;
- свободным от ненужных инфраструктурных параметров;
- построенным вокруг пользовательских/агентных намерений, а не внутренних backend-команд.

MCP не является копией REST API.

Имена tools, docstrings, descriptions полей, пояснения ошибок и другая информация, предназначенная для агента, должны быть преимущественно **на русском языке**, поскольку русский является основным языком проекта и это упрощает сопровождение. Технические идентификаторы, имена функций, классов, полей и error codes могут оставаться английскими.

JSON Schema MCP-инструмента следует считать частью agent UX, а не побочным продуктом Python-типизации.

Полная MCP-схема должна позволять LLM понять:

- что именно делает операция;
- когда её следует использовать;
- когда её использовать не следует;
- что означает каждый аргумент;
- какие существуют machine-readable ограничения;
- какие комбинации полей допустимы;
- что означает результат;
- какие ограничения есть у результата.

При этом runtime обязан самостоятельно валидировать полученные arguments. Нельзя полагаться на то, что LLM прочитала JSON Schema и обязательно сформирует корректный вызов.

---

## 6. Web Access не принимает решения за агента

Сервис является инфраструктурным и прикладным мостом между агентом и веб-средой.

Он не должен скрыто подменять reasoning агента эвристиками.

Сервис не должен сам решать, например:

- что результатов поиска «слишком мало»;
- что результат «недостаточно качественный»;
- что необходимо автоматически переключиться на другой search provider;
- что HTTP-страницу следует автоматически открыть в браузере;
- по какой ссылке агенту нужно перейти дальше;
- какую страницу нужно перечитать;
- какую стратегию исследования следует выбрать.

Backend должен сообщать наблюдаемые факты:

- что было запрошено;
- что фактически выполнено;
- что получено;
- какой provider использован;
- какие ограничения, ошибки или предупреждения возникли.

Решение о следующем смысловом шаге остаётся за вызывающим агентом или другим клиентом.

Конфигурационные инфраструктурные политики — лимиты, backpressure, разрешённые providers, timeout, quota и security rules — являются нормальной ответственностью сервиса и не считаются reasoning-эвристиками.

---

## 7. Основные предметные подсистемы

На текущем уровне проект следует рассматривать как совокупность нескольких независимых, но связанных областей:

```text
Web Access
├── Search
├── Retrieval
├── Extraction
├── Content
├── Browser
├── Jobs
└── Diagnostics / Observability
```

Точные границы модулей будут уточняться в design documents.

---

## 8. Search

Подсистема Search отвечает за выполнение поисковых запросов и нормализацию результатов внешних search providers.

Предварительная модель:

```text
SearchApplicationService
        ↓
SearchProvider
        ├── SearXNGProvider
        ├── YandexSearchProvider
        └── future providers
```

### Базовое направление

Основным бесплатным search backend предполагается собственный экземпляр SearXNG.

Дополнительные search providers, включая существующий Yandex Search API, должны подключаться через отдельные adapters.

Provider-specific значения и детали не должны автоматически становиться частью общего domain/application contract.

### Выбор provider

Выбор search provider должен быть явным application/configuration решением.

Не следует хардкодить скрытые эвристики вроде:

```python
if len(results) < 5:
    use_other_provider()
```

Можно иметь понятие configured default provider, а вызывающий клиент при необходимости сможет явно запросить другой provider.

### Batch-first

Независимые stateless операции следует проектировать batch-first там, где это естественно.

Например, backend search operation должна уметь обработать один или несколько независимых поисковых запросов одним вызовом, вместо создания отдельных `search` и `search_many` операций.

Один элемент передаётся как список из одного элемента.

---

## 9. Retrieval

Retrieval отвечает за получение известных HTTP(S)-ресурсов без браузерного взаимодействия.

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
→ MIME/type detection
→ RetrievedResource
```

Для сетевого клиента предполагается async HTTPX.

### Обязательные свойства

Retrieval layer должен учитывать:

- только разрешённые URL schemes;
- SSRF и private-network protection;
- redirects как отдельные проверяемые переходы;
- DNS/IP validation;
- streaming;
- ограничение compressed/decompressed размера;
- connect/read/total deadlines;
- корректную работу с encoding;
- проверку declared и фактического content type;
- контролируемую обработку частичных и ошибочных ответов.

Безопасность retrieval должна быть централизована и переиспользоваться всеми transport facades.

---

## 10. Extraction

Получение bytes и извлечение полезного содержимого являются разными задачами.

Предварительная архитектура:

```text
ContentExtractionService
        ↓
ExtractorRegistry
        ├── HtmlExtractor
        ├── PdfExtractor
        ├── JsonExtractor
        ├── XmlExtractor
        └── TextExtractor
```

Extractor выбирается по фактическому типу содержимого и policy, а не по transport endpoint.

### HTML

Предполагается сочетание:

- инструмента для main-content extraction, ориентировочно Trafilatura;
- отдельного структурного HTML parser для links, metadata, JSON-LD, headings, forms и других элементов страницы.

Конкретный structural parser (`lxml`, `selectolax` или другой вариант) должен быть выбран отдельным техническим решением после сравнения.

### PDF

Для обычного text extraction рассматривается `pypdf`, но обработка PDF должна иметь строгие ресурсные лимиты.

OCR не следует смешивать с обычным PDF extraction. При необходимости он должен стать отдельной optional capability/processor.

### Deterministic processing

Нормализация HTML, извлечение title, canonical URL, JSON-LD, metadata, links и преобразование текста в удобный формат являются обычной deterministic обработкой данных и не противоречат принципу отсутствия reasoning-эвристик.

---

## 11. Content storage

Большие материалы нельзя безусловно передавать через MCP result или хранить как огромный JSON в PostgreSQL.

Проект должен с самого начала иметь абстракцию `ContentStore`.

Предварительная domain-сущность:

```text
ContentObject
```

Она должна позволять хранить или ссылаться на:

- raw HTTP responses;
- HTML;
- extracted text;
- Markdown;
- PDF;
- screenshots;
- browser downloads;
- rendered page content;
- crawl results;
- другие крупные бинарные или текстовые материалы.

Предварительные реализации:

```text
FilesystemContentStore
S3CompatibleContentStore
```

Локальная установка не должна требовать внешнего S3.

Переключение storage backend не должно менять application contracts.

PostgreSQL должен хранить metadata, references, ownership/lifecycle информацию и другие структурированные данные, но не обязан быть blob storage для всего полученного веб-контента.

---

## 12. Browser runtime

Browser является отдельной stateful подсистемой.

Он не должен быть скрытой частью `RetrievalService`.

Предварительные domain/application понятия:

```text
BrowserService
BrowserSession
BrowserPage
BrowserAction
BrowserSnapshot
```

### Playwright

Базовым browser automation engine предполагается Playwright с Chromium.

Предпочтительным первоначальным вариантом является официальный Python Playwright, чтобы основной стек проекта оставался единым. Это решение может быть пересмотрено только при наличии конкретных технических причин.

### Process boundary

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

Нельзя полагаться на запуск Chromium внутри каждого Uvicorn/API worker.

### BrowserSession и MCP transport

Жизненный цикл BrowserSession не должен зависеть от жизненного цикла MCP connection.

```text
MCP reconnect/disconnect
≠ BrowserSession close
```

Stateful browser operations должны использовать собственные opaque handles.

Фактические объекты Playwright (`Browser`, `BrowserContext`, `Page`, `Locator`) живут только в browser worker process.

PostgreSQL/Redis могут хранить coordination metadata, но не сериализованный Playwright state.

### Browser session ownership

Backend должен уметь отслеживать как минимум:

- opaque browser session identifier;
- owning worker;
- lifecycle state;
- revision/generation при необходимости;
- creation/last-activity timestamps;
- expiration metadata;
- безопасную ownership информацию.

Сервер остаётся окончательным владельцем cleanup и обязан иметь собственные TTL/reaper механизмы независимо от best-effort cleanup со стороны клиента.

---

## 13. Stateful browser actions и ordering

Внутри одной BrowserSession действия могут зависеть от результата предыдущих действий.

Поэтому batch-first принцип не должен механически применяться к stateful transitions.

Например:

```text
click
→ navigation/state change
→ snapshot
→ next decision
```

не является независимым batch.

В пределах одной browser session должна быть обеспечена корректная последовательность mutating actions.

Несколько browser sessions могут исполняться параллельно в пределах ресурсов и policy сервиса.

Особое внимание необходимо уделить неопределённому результату операции при потере transport response после фактического side effect. Такие операции нельзя слепо автоматически повторять.

---

## 14. PostgreSQL

Базовый persistence stack:

```text
PostgreSQL
SQLAlchemy 2 async
asyncpg
Alembic
```

PostgreSQL рассматривается как authoritative durable storage для структурированной информации.

Предварительные категории данных:

- operations/jobs;
- operation/job events;
- result metadata;
- upstream-call diagnostics;
- search requests/results metadata;
- retrieval metadata;
- content metadata/references;
- browser session metadata;
- browser action audit;
- provider usage;
- quota/cost accounting;
- другие durable lifecycle records.

Точная схема БД должна проектироваться отдельно.

Важно не превращать каждую короткую synchronous operation в durable queue job только потому, что PostgreSQL присутствует в архитектуре.

---

## 15. Redis

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

Нельзя автоматически выбирать одну Redis-механику для всех задач.

Например, транспорт команд к owning browser worker требует отдельного сравнения как минимум между direct internal HTTP/RPC и Redis-based mailbox/streams подходом.

Такое решение должно быть оформлено отдельным ADR после анализа latency, ordering, cancellation, retries, worker crash semantics, backpressure и horizontal scaling.

---

## 16. Jobs и execution paths

Архитектура KudaGo-сервера является полезным ориентиром для PostgreSQL + Redis + arq lifecycle, но Web Access не должен пропускать каждую операцию через durable queue.

В проекте предполагаются как минимум два execution path.

### Request-bound operations

Короткие операции, результат которых нужен вызывающему клиенту непосредственно в рамках текущего запроса:

- search;
- retrieval;
- extraction;
- чтение content object;
- большинство browser actions.

Они могут вести observability/audit records, но не обязаны становиться durable jobs.

### Durable jobs

Операции, которые по своей природе являются длительными, фоновыми или требуют устойчивости к разрыву клиентского соединения:

- crawl;
- большие batch operations;
- длительная обработка больших документов;
- фоновые workflows;
- другие long-running задачи.

Для них предполагается паттерн:

```text
PostgreSQL durable state
→ Redis / arq
→ worker
→ persisted result/events
```

Точный набор операций, которые считаются durable, должен определяться их семантикой, а не общей эвристикой размера.

---

## 17. Application layer

В отличие от системы, где практически всё естественно моделируется одной командой, Web Access содержит разные классы сущностей и lifecycle.

Поэтому не следует заранее строить один огромный `CommandExecutor` для всей системы.

Предварительная декомпозиция:

```text
SearchApplicationService
RetrievalApplicationService
ContentApplicationService
BrowserApplicationService
JobApplicationService
```

При этом подсистемы должны использовать общие базовые contracts, например:

```text
ExecutionContext
OperationResult
OperationError
OperationEvent
```

Конкретные имена и структуры будут определены в design phase.

Application layer не должен зависеть от FastAPI router или FastMCP tool.

---

## 18. Infrastructure adapters

Внешние системы и библиотеки должны находиться за явными ports/adapters.

Примеры:

```text
SearchProvider
ContentStore
HttpFetcher
ContentExtractor
BrowserWorkerClient
JobQueue
Cache
Repositories
Clock / ID generation при необходимости
```

Это позволит:

- тестировать application layer без реального интернета;
- заменять provider;
- масштабировать компоненты независимо;
- вводить новые storage backends;
- изменять worker transport без переписывания MCP и REST facades.

---

## 19. Предварительный технологический стек

На текущем этапе базовым направлением считается следующий стек:

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
| Main HTML extraction | Trafilatura |
| Structural HTML parsing | определить отдельным решением (`lxml` / `selectolax` / другой) |
| PDF text extraction | pypdf с resource limits |
| MIME detection | declared type + content sniffing; возможен libmagic/python-magic |
| Browser automation | Playwright Python |
| Browser engine | Chromium |
| Large content | `ContentStore`: filesystem + S3-compatible adapter |
| Tests | pytest + pytest-asyncio + jsonschema и интеграционные тесты |
| Deployment | Docker / Docker Compose с архитектурой, готовой к горизонтальному масштабированию |

Этот список является направлением, а не навсегда замороженным lock-файлом. Конкретные зависимости и версии должны быть зафиксированы после отдельных технических решений и проверок совместимости.

---

## 20. MIME и тип содержимого

Сервис не должен безусловно доверять только HTTP `Content-Type`.

Необходимо учитывать:

```text
declared Content-Type
+
фактическое содержимое / magic bytes
+
security policy
```

Это особенно важно для downloads, PDF, архивов и некорректно размеченных HTTP-ответов.

Конкретный механизм content sniffing будет выбран отдельно.

---

## 21. Failure model

Ошибки необходимо проектировать как часть application contract, а не как случайные exceptions transport layer.

На следующих этапах потребуется определить устойчивую taxonomy как минимум для классов проблем:

- validation;
- policy/security rejection;
- provider/upstream failure;
- timeout;
- rate limiting;
- resource unavailable;
- resource expired;
- resource lost;
- cancellation;
- queue/worker infrastructure failure;
- unknown outcome для операций с возможным side effect.

MCP должен преобразовывать эти ошибки в structured agent-repairable responses.

REST должен предоставлять полноценное программное представление ошибки.

Оба фасада должны опираться на одну application error model.

---

## 22. Observability

Production-ready сервис должен с самого начала иметь архитектурные точки для:

- structured logging;
- request/operation correlation IDs;
- job/event history;
- upstream-call diagnostics;
- timing;
- retry data;
- provider usage;
- cache statistics;
- browser worker health;
- resource/session lifecycle;
- metrics;
- tracing.

При этом observability не должна диктовать domain contract и не должна требовать превращения каждой операции в durable job.

---

## 23. Security boundary

Web Access будет обрабатывать недоверенные URL, страницы, документы и browser state, поэтому security является частью архитектуры, а не поздним дополнением.

Необходимо проектировать отдельно:

- SSRF protection;
- egress policy;
- DNS rebinding protection;
- redirect validation;
- content-size/decompression limits;
- browser isolation;
- process/container boundaries;
- file/download handling;
- secret isolation;
- user/service permissions;
- safe logging;
- cleanup;
- resource quotas;
- prompt-injection-safe представление веб-контента для ИИ-агента.

BrowserContext следует считать изоляцией browser state, но не общей security sandbox.

---

## 24. Tool/API surface проектируется после backend-а

На текущем этапе не следует фиксировать окончательный MCP tool catalog.

Сначала для каждой backend capability необходимо определить:

```text
назначение
input contract
output contract
side effects
request-bound / durable execution
persistence
Redis usage
concurrency
ordering
idempotency
retry semantics
cancellation
timeouts
failure model
security boundaries
observability
```

Только после этого проектируется MCP facade.

Аналогично, REST API проектируется после стабилизации application operations, а не наоборот.

---

## 25. Принципы будущего MCP surface

Хотя окончательный каталог пока не фиксируется, уже приняты общие правила.

### Один intent — один canonical tool

Не должно быть набора эквивалентных aliases вроде:

```text
web_read
read_page
fetch_url
web_fetch
web_fetch_many
```

Если две операции существуют отдельно, между ними должна быть реальная семантическая разница.

### Batch-first для независимых операций

Stateless независимые операции естественно принимают список элементов.

Один элемент передаётся как список из одного элемента.

Не создаются отдельные `*_many` tools без необходимости.

### Stateful sequential operations не batch-ятся механически

Browser transitions должны сохранять ordering и промежуточное наблюдаемое состояние.

### Schema — часть интерфейса агента

Каждое публичное поле должно иметь подробное описание, machine-readable constraints, корректные defaults и понятную `null`/omission semantics.

Cross-field invariants должны быть отражены не только runtime validator-ом, но по возможности и реальной JSON Schema (`oneOf`, `anyOf`, etc.).

### Agent-facing, а не provider-facing

MCP не должен раскрывать внутренние параметры SearXNG, HTTPX, Playwright или другого provider-а только потому, что они существуют внутри реализации.

### Structured validation errors

Ошибочный MCP-вызов должен возвращать данные, позволяющие агенту исправить arguments без догадок.

### Tool annotations

Read-only, idempotent, destructive/open-world и другие execution semantics должны корректно отражаться в MCP metadata и согласовываться с интеграционным контрактом собственного ИИ-агента.

---

## 26. Совместимость с собственным ИИ-агентом

Web Access MCP является самостоятельным сервисом и не должен зависеть от внутренних классов `internet-search-bot`.

Интеграция осуществляется через стабильный MCP contract.

Со стороны агента сервис предполагается использовать как builtin MCP service согласно контракту агента для встроенных MCP-сервисов.

Граница ответственности:

### Агент

Отвечает за:

- выбор и вызов MCP-tools;
- reasoning и orchestration;
- пользовательское представление progress;
- trusted presentation metadata;
- ownership opaque remote handles со своей стороны;
- best-effort lifecycle cleanup requests;
- интерпретацию результата.

### Web Access

Отвечает за:

- фактическое выполнение веб-операции;
- внутреннее состояние сервиса;
- безопасное взаимодействие с внешним вебом;
- проверку opaque handles;
- browser/resource lifecycle;
- server-side TTL/reaper;
- окончательную очистку принадлежащих сервису ресурсов;
- consistency и observability backend-а.

MCP transport lifecycle не должен становиться владельцем stateful remote resources.

---

## 27. Масштабирование

Проект должен оставаться удобным локально, но архитектура не должна предполагать единственный process или единственного пользователя.

Нужно заранее сохранять возможность независимо масштабировать:

- API/MCP control plane;
- search/retrieval workers при необходимости;
- durable job workers;
- browser workers;
- SearXNG;
- PostgreSQL;
- Redis;
- content storage.

Stateful browser routing необходимо проектировать так, чтобы любой API instance мог принять запрос и корректно направить действие worker-у, который действительно владеет BrowserSession.

---

## 28. Что пока не фиксируется

Этот концептуальный документ намеренно не определяет:

- окончательный список MCP-tools;
- точные MCP input/output schemas;
- REST endpoint tree;
- таблицы PostgreSQL;
- Redis keys/streams/channels;
- точные job types;
- конкретный browser-worker transport;
- точные TTL и timeout;
- конкретные limits;
- окончательную error taxonomy;
- authentication/authorization protocol;
- persistent browser profiles;
- exact crawling semantics;
- version roadmap.

Эти решения должны приниматься последовательно в отдельных design documents и ADR после анализа конкретной подсистемы.

---

## 29. Критерий правильности архитектуры

Проектирование считается движущимся в правильном направлении, если новая возможность может быть добавлена примерно по следующей цепочке:

```text
новая предметная capability
→ application contract
→ infrastructure adapter при необходимости
→ tests
→ REST mapping
→ компактный MCP mapping
```

и при этом не требуется:

- переписывать Agent Runtime;
- дублировать бизнес-логику между REST и MCP;
- раскрывать provider-specific детали агенту;
- привязывать stateful resource к одному HTTP/MCP connection;
- превращать короткую операцию в durable job без семантической причины;
- хардкодить reasoning-эвристику вместо явного контракта.

---

## 30. Следующий этап проектирования

Следующий этап после этой концепции — не реализация MCP facade.

Сначала необходимо подробно спроектировать backend surface по областям:

1. Search.
2. Retrieval.
3. Extraction.
4. Content.
5. Browser.
6. Jobs.
7. Diagnostics/observability.
8. Security and policy.

Для каждой области нужно определить application operations, domain models, ports, lifecycle, persistence, concurrency, cancellation, failure semantics и acceptance criteria.

После стабилизации backend design можно проектировать:

```text
REST API — полный программный facade
MCP — компактный русскоязычный agent-facing facade
```

Именно эта последовательность является базовой концепцией разработки `Web Access MCP`.
