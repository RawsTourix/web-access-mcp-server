# Глоссарий Web Access MCP

## Статус документа

Этот документ является каноническим владельцем базовой терминологии design-документации проекта.

Если термин используется в нескольких design-файлах, его основное значение должно определяться здесь. Компонентные документы могут уточнять термин в своём контексте, но не должны вводить несовместимую трактовку.

---

## A

### Adapter

Конкретная реализация внешней зависимости или integration boundary, соответствующая port/application contract.

Примеры:

- `SearXNGProvider` реализует `SearchProvider`;
- `FilesystemContentStore` реализует `ContentStore`;
- HTTP/Redis-based browser transport реализует `BrowserWorkerClient`.

Adapter относится к infrastructure/runtime стороне и не должен определять application semantics.

### Advanced Processing (L2)

Тяжёлая или специализированная обработка контента, выходящая за базовую ответственность Web Access.

Примеры:

- OCR;
- VLM;
- сложное layout recognition;
- LibreOffice-based conversion;
- transcription;
- semantic multimedia processing.

Web Access может сообщить, что такая обработка потенциально нужна, но не обязан и по умолчанию не должен выполнять её сам.

### Application Contract

Стабильное описание прикладной операции или ресурса, независимое от REST/MCP и конкретной infrastructure implementation.

Application contract определяет смысл inputs, outputs, outcomes, invariants и lifecycle.

### Application Operation

Логически завершённое действие application layer.

Примеры:

- выполнить web search;
- получить известный URL;
- прочитать ContentObject;
- создать BrowserSession;
- выполнить browser action;
- закрыть BrowserSession;
- создать/cancel durable Job.

Application Operation не обязана быть REST endpoint, MCP tool или Job.

---

## B

### Batch

Один application/transport вызов, содержащий несколько независимых элементов одной операции.

Batch-first используется только там, где элементы могут исполняться независимо без скрытой зависимости от промежуточного состояния.

### Batch Item

Один независимый элемент внутри batch. Имеет собственный result/outcome/error, даже если aggregate response содержит общую metadata.

### Browser Action

Операция над уже существующей BrowserSession/Page.

Может быть:

- наблюдающей/read-only;
- изменяющей browser state;
- потенциально вызывающей внешний side effect.

Retry semantics Browser Action определяется её фактической семантикой.

### Browser Page

Логическая открытая страница/tab внутри BrowserSession.

Публичный контракт не должен раскрывать внутренний объект Playwright `Page`.

### Browser Runtime

Отдельный stateful runtime, владеющий живыми browser objects и выполняющий browser actions.

### Browser Session

Stateful удалённый ресурс Web Access, представляющий изолированную browser context/session, способную пережить несколько отдельных REST/MCP вызовов.

BrowserSession имеет собственный lifecycle и не привязана к lifetime одного transport connection.

### Browser Snapshot

Структурированное наблюдаемое представление текущего состояния страницы, пригодное для выбора следующего browser action.

Точный формат snapshot определяется design Browser subsystem.

### Browser Worker

Отдельный процесс/runtime, который фактически владеет Playwright browser/context/page objects и исполняет действия BrowserSession.

---

## C

### Cache

Временное повторно используемое представление результата, не являющееся по умолчанию authoritative durable source of truth.

Cached response должен позволять определить freshness/время происхождения настолько, насколько это важно для application contract.

### Canonical Operation

Единственная основная публичная/application операция для конкретного intent.

Не следует поддерживать несколько алиасов с одинаковым смыслом без compatibility-причины.

### Content

Подсистема, отвечающая за inspection, native parsing, representations, provenance и storage уже полученного или созданного содержимого.

### Content Inspection (L0)

Дешёвая детерминированная идентификация и получение базовых свойств ContentObject без тяжёлой обработки.

Примеры:

- media type;
- detected format;
- size;
- hash;
- dimensions;
- page count;
- container metadata.

### Content Object

Логический ресурс, представляющий сохранённое содержимое или одно из его representations.

ContentObject должен иметь opaque identifier, metadata, lifecycle/ownership information и storage reference.

### Content Representation

Конкретное представление содержимого.

Примеры:

- raw bytes;
- HTML;
- plain text;
- Markdown;
- parsed structure;
- screenshot;
- downloaded file.

Representation может быть raw или derived.

### Content Store

Port/application abstraction для хранения и чтения крупных текстовых и бинарных representations.

Предполагаемые adapters:

- filesystem;
- S3-compatible storage.

### Control Plane

Stateless или преимущественно stateless API/MCP runtime, принимающий клиентские вызовы, выполняющий application orchestration и маршрутизирующий работу в нужные infrastructure runtimes.

Он не должен владеть живыми Playwright objects.

### Correlation ID

Идентификатор, связывающий несколько логов/вызовов/событий одной цепочки выполнения. Не обязательно равен `operation_id`.

---

## D

### Deadline

Абсолютная или логическая граница времени, после которой продолжение request-bound операции больше не ожидается клиентом или запрещено policy.

Deadline должен протекать вниз по execution stack там, где это возможно.

### Derived Content / Derived Representation

ContentRepresentation, полученное из другого ContentObject через deterministic parser, export или другой processor.

Должно сохранять provenance к исходному объекту.

### Durable Job

Долгоживущая/фонова́я операция, состояние которой должно переживать transport disconnect и обычно должно сохраняться в durable storage.

Не каждая Application Operation является Job.

---

## E

### Execution Context

Общий application context выполнения операции.

Предполагается, что в будущем он сможет включать:

- operation identity;
- principal/owner context;
- deadline;
- cancellation context;
- correlation/trace metadata;
- policy context.

Точная модель определяется `application-contracts.md`.

### Extraction

Не используется как самостоятельный верхнеуровневый bounded context.

В design-документации под прямым извлечением содержимого обычно понимается `Native Parsing` внутри Content.

Тяжёлая обработка относится к `Advanced Processing (L2)`.

---

## F

### Freshness

Информация о времени и актуальности полученного/cached результата.

Freshness не является reasoning-эвристикой качества ответа. Она описывает наблюдаемый факт или policy кэша.

---

## H

### Handle

Opaque identifier удалённого ресурса, используемый клиентом для последующих операций.

Handle не должен требовать от клиента знания внутренней topology/storage implementation.

### Hint / Structured Hint

Машиночитаемая необязательная рекомендация в application result, объясняющая возможный следующий шаг на основании наблюдаемого состояния.

Hint:

- не является командой;
- не запускает операцию автоматически;
- не меняет outcome текущей операции;
- наиболее точен, когда указывает на capability самого Web Access.

---

## I

### Idempotent Operation

Операция, повтор которой при одинаковом idempotency context не создаёт дополнительного эффекта относительно уже выполненного эквивалентного вызова.

Идемпотентность не следует предполагать только из HTTP method или названия tool.

### Infrastructure

Конкретные технологии и adapters, реализующие ports/application needs.

Примеры:

- PostgreSQL/SQLAlchemy;
- Redis;
- HTTPX;
- SearXNG;
- Playwright;
- filesystem/S3;
- arq.

### Inspection

См. `Content Inspection (L0)`.

---

## J

### Job Worker

Worker runtime для durable/background operations, которые подходят под queue-based execution model.

Job Worker не является владельцем произвольной BrowserSession, если эта session живёт в Browser Worker.

---

## L

### Lease

Ограниченное по времени право runtime-а владеть или обслуживать конкретный распределённый ресурс.

Точная необходимость и реализация lease/fencing для browser routing будет определена отдельным design/ADR.

### L0 / L1 / L2

Уровни обработки Content:

- **L0 — Inspection**;
- **L1 — Native Parsing**;
- **L2 — Advanced Processing**, находящийся за границей Web Access.

---

## M

### MCP Facade

Agent-facing transport projection application capabilities через MCP.

MCP facade должен быть компактным, понятным LLM и использовать подробные русскоязычные descriptions/schemas.

Он не является механической копией REST API.

---

## N

### Native Parser

Детерминированный parser, который непосредственно читает уже доступную структуру формата без OCR/VLM/browser rendering/тяжёлой конвертации.

### Native Parsing (L1)

Получение доступного текстового или структурированного представления непосредственно из формата.

Если Native Parsing невозможно или формат не поддерживается, сервис возвращает raw content + diagnostics/hints вместо скрытого перехода к L2.

---

## O

### Operation

См. `Application Operation`.

### Operation Error

Нормализованная application-level ошибка, не привязанная к exception конкретной библиотеки.

### Operation ID

Уникальная identity одного application execution attempt/operation в рамках принятой модели.

Operation ID может существовать и для request-bound операций, не являющихся durable jobs.

### Operation Outcome

Канонический итог операции.

Предполагаемые общие категории будут определены в `application-contracts.md`; принципиально поддерживается возможность `unknown`, когда невозможно доказать, был ли side effect выполнен.

### Operation Result

Нормализованный application result, который может содержать:

- data;
- outcome;
- warnings;
- structured hints;
- provenance;
- execution metadata.

Точная schema определяется `application-contracts.md`.

### Owner

Субъект или логический контекст, которому принадлежит ресурс.

Owner model должна быть совместима с будущей multi-user системой.

---

## P

### Partial Success

Batch outcome, при котором часть независимых items выполнена успешно, а часть завершилась ошибкой/отказом.

Partial success не должен автоматически уничтожать успешные результаты других items.

### Port

Интерфейс, объявленный application/domain стороной и описывающий требуемую внешнюю capability без привязки к конкретной технологии.

### Principal

Авторизованный или логически идентифицируемый субъект, от имени которого выполняется операция.

На ранних версиях principal model может быть минимальной, но architecture должна оставаться principal-ready.

### Provider

Внешняя или сменная реализация некоторой application capability.

Например Search Provider предоставляет поисковую выдачу, но его provider-specific API не должен определять общий Search contract.

### Provenance

Информация о происхождении результата/representation.

Может включать:

- source URL/provider;
- исходный ContentObject;
- parser/producer;
- producer version;
- время получения/создания;
- параметры преобразования.

---

## R

### Raw Content / Raw Representation

Содержимое, максимально близкое к фактически полученному или созданному исходному материалу до Native Parsing.

### Reaper

Server-side механизм поиска и очистки просроченных/забытых временных ресурсов.

### Request-bound Operation

Операция, результат которой ожидается в рамках текущего client request и которая не требует durable job lifecycle по своей семантике.

### Resource

Логически адресуемая сущность с identity/lifecycle/ownership.

Примеры:

- ContentObject;
- BrowserSession;
- Job.

### REST Facade

Программный HTTP API, предоставляющий богатый доступ к стабильным application capabilities.

REST facade может быть подробнее MCP, но не должен дублировать application logic.

### Retrieval

Подсистема безопасного получения известного HTTP(S)-ресурса.

Retrieval отвечает за сетевое получение и фиксацию наблюдаемого response/content, но не за Browser fallback или Advanced Processing.

### Retry Policy

Правило, определяющее, допустим ли автоматический повтор операции после конкретного failure/outcome.

Retry policy определяется семантикой операции, а не только типом transport error.

---

## S

### Search

Подсистема получения и нормализации поисковой выдачи через SearchProvider adapters.

Search не читает автоматически содержимое найденных страниц и не выполняет скрытый provider fallback на основании reasoning-эвристик.

### Search Provider

Port/adapter boundary для внешнего поискового backend.

Примеры реализаций: SearXNG, Yandex Search.

### Side Effect

Наблюдаемое изменение внешнего или stateful состояния, вызванное операцией.

Например browser click может инициировать сетевой запрос, отправку формы или изменение server-side состояния сайта.

### Source of Truth

Authoritative storage/состояние, относительно которого определяется durable факт системы.

Redis не считается универсальным source of truth по умолчанию.

### Structured Hint

См. `Hint / Structured Hint`.

---

## T

### Transport

Внешняя форма вызова application capabilities.

Основные transports проекта:

- REST;
- MCP.

Transport не владеет application resource lifecycle.

### Transport Facade

REST/MCP слой, который преобразует transport-specific request в application contract и application result обратно в transport representation.

---

## U

### Unknown Outcome

Состояние, при котором система не может достоверно определить, был ли потенциальный side effect выполнен до transport/infrastructure failure.

`unknown` нельзя автоматически преобразовывать в `failed` и нельзя использовать как основание для blind retry mutating operation.

---

## W

### Warning

Нестопорящая диагностическая информация о выполненной операции или результате.

Warning отличается от Hint:

- Warning сообщает значимое ограничение/аномалию текущего результата;
- Hint предлагает возможное последующее действие.

### Worker

Отдельный runtime/process, исполняющий определённый класс работы.

В проекте как минимум различаются:

- Job Worker;
- Browser Worker.

Их lifecycle и ownership semantics различаются.
