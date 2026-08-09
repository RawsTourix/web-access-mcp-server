# Архитектурные принципы Web Access MCP

## Статус документа

Этот документ является каноническим владельцем **сквозных архитектурных принципов и инвариантов** проекта `web-access-mcp-server`.

Он не описывает конкретные REST endpoints, MCP tools, таблицы PostgreSQL или Redis-протоколы. Компонентные и version-документы обязаны соответствовать этим принципам и не должны заново определять их независимо.

---

## 1. Backend-first

Архитектура проектируется от предметных задач и application contracts к transport facades, а не наоборот.

```text
предметная capability
→ domain/application contract
→ ports
→ infrastructure adapters
→ REST projection
→ MCP projection
```

Нельзя проектировать backend как реализацию заранее придуманного MCP-tool или REST endpoint.

---

## 2. Единый application layer для REST и MCP

REST и MCP являются разными представлениями одних и тех же application capabilities.

Они могут иметь разные:

- входные schemas;
- имена полей;
- уровень детализации;
- формы ошибок;
- формы выдачи результата.

Но они не должны дублировать бизнес-логику.

Фактическое выполнение операции принадлежит application layer.

---

## 3. Web Access не выполняет reasoning за клиента

Сервис предоставляет наблюдаемые веб-возможности и не должен скрыто принимать смысловые решения за ИИ-агента или другого клиента.

Запрещены неявные reasoning-эвристики вида:

```text
мало результатов поиска → автоматически сменить provider
пустой HTML → автоматически запустить Browser
сканированный PDF → автоматически запустить OCR
неподдерживаемый DOC → автоматически запустить LibreOffice
```

Допустимы инфраструктурные policy-решения:

- rate limit;
- quota;
- timeout/deadline;
- backpressure;
- resource limits;
- access policy;
- configured default provider;
- security restrictions.

---

## 4. Сервис должен быть быстрым и ленивым

По умолчанию Web Access выполняет наиболее прямую и дешёвую операцию, которую явно запросил клиент.

Он не должен автоматически повышать computational class операции.

```text
Search            → только поиск
Retrieval         → только получение ресурса
Content L0/L1     → inspection и native parsing
Browser           → только по явному вызову browser capability
Advanced L2       → за границей Web Access
```

Тяжёлая обработка запускается только через отдельную capability или внешний сервис.

---

## 5. Основные bounded responsibilities

На верхнем уровне Web Access разделяется на:

```text
Search
Retrieval
Content
Browser
Jobs
```

Сквозными concerns являются:

- Security / Policy;
- Persistence;
- Observability;
- Configuration;
- Transport.

`Content Extraction` не является отдельным верхнеуровневым bounded context. Дешёвое детерминированное извлечение является частью Content.

---

## 6. Content имеет три уровня обработки

### L0 — Inspection

Дешёвое определение того, что уже получено:

- media type / format;
- размер;
- hash;
- dimensions;
- page count;
- container properties;
- доступные metadata;
- другие свойства, которые можно определить без тяжёлой обработки.

### L1 — Native Parsing

Прямое детерминированное чтение структуры существующего формата без OCR, VLM, browser rendering или тяжёлой конвертации.

Примеры:

```text
HTML → текст / ссылки / metadata
PDF с text layer → текст
DOCX → paragraphs / tables
XLSX → sheets / cells
JSON / XML / CSV → структура
EPUB / FB2 → главы / текст
```

### L2 — Advanced Processing

Не является ответственностью Web Access:

- OCR;
- VLM;
- сложное layout recognition;
- LibreOffice-based conversion;
- speech-to-text;
- multimedia understanding;
- специализированная тяжёлая обработка документов.

Если L1 недоступен, сервис возвращает raw content, diagnostics и при необходимости structured hint, но не запускает L2 автоматически.

---

## 7. Structured hints информируют, но не оркестрируют

Application result может содержать структурированные подсказки о следующем возможном действии.

Hint должен:

- объяснять наблюдаемую причину;
- по возможности ссылаться на capability самого Web Access;
- быть машиночитаемым;
- не менять outcome выполненной операции;
- не запускать действие автоматически.

Пример:

```json
{
  "code": "browser_may_be_required",
  "reason": "Полученный HTML содержит минимальное статическое содержимое.",
  "related_capability": "browser"
}
```

Для внешних систем рекомендации формулируются нейтрально. Web Access не должен жёстко предписывать конкретный внешний продукт, если тот не является частью его контракта.

---

## 8. Один intent — одна canonical operation

Не следует создавать параллельные операции с одинаковым смыслом:

```text
web_read
read_page
fetch_url
web_fetch
web_fetch_many
```

Если две операции существуют отдельно, между ними должна быть реальная семантическая разница.

---

## 9. Batch-first для независимых операций

Stateless операции, элементы которых независимы друг от друга, проектируются batch-first там, где это естественно.

Один элемент передаётся как список из одного элемента.

Не создаются отдельные `*_many` операции без отдельной семантической причины.

Batch должен иметь определённую семантику:

- порядок результатов относительно входных элементов;
- per-item outcome/error;
- partial success;
- общую aggregate metadata.

Точная форма фиксируется в `application-contracts.md`.

---

## 10. Stateful transitions не batch-ятся механически

Операции, изменяющие состояние `BrowserSession`, рассматриваются как последовательные transitions.

```text
click
→ состояние изменилось
→ snapshot
→ новое решение
```

Нельзя объединять зависимые действия в произвольный batch только ради уменьшения количества вызовов.

Внутри одной browser session mutating actions должны иметь определённый ordering.

---

## 11. Transport lifecycle не владеет application resource

Жизненный цикл MCP/HTTP connection не является жизненным циклом `BrowserSession`, `Job`, `ContentObject` или другого stateful/durable ресурса.

```text
transport reconnect/disconnect
≠ resource create/close
```

Stateful resources используют opaque handles и собственный lifecycle.

---

## 12. Сервер остаётся окончательным владельцем cleanup

Клиент может отправлять best-effort cleanup request, но Web Access обязан самостоятельно обеспечивать окончательную очистку принадлежащих ему ресурсов.

Для временных ресурсов должны существовать server-side механизмы:

- TTL;
- expiration;
- reaper/reconciliation;
- bounded shutdown cleanup.

Потеря клиента не должна означать бесконечную жизнь ресурса.

---

## 13. Ownership проектируется заранее

Даже до появления полноценной пользовательской авторизации архитектура должна быть `principal-ready`.

Ресурсы не проектируются как бесхозные глобальные объекты.

Как минимум должны быть возможны:

- owner/principal context;
- проверка доступа к opaque handle;
- дальнейшее расширение до multi-user режима без смены базовой модели ресурсов.

Scope/ownership не заменяют authorization policy.

---

## 14. Opaque handles не раскрывают внутреннюю топологию

Публичный handle не должен кодировать в читаемом виде:

- worker address;
- database primary key, если это создаёт лишнюю связанность;
- internal filesystem path;
- secret/token;
- инфраструктурную топологию.

Клиент не должен строить логику на внутренней структуре handle.

---

## 15. Operation identity существует независимо от Job

Короткая request-bound операция не обязана становиться durable job, но всё равно может иметь стабильный `operation_id`/correlation identity для:

- tracing;
- structured logs;
- provenance;
- diagnostics;
- связывания downstream calls.

`Operation` и `Job` — разные понятия.

---

## 16. Deadline и cancellation являются сквозными контрактами

Deadline должен протекать вниз по стеку настолько, насколько это поддерживает конкретная операция:

```text
transport
→ application
→ provider / retrieval / worker
```

Отмена request-bound операции и отмена durable job имеют разную семантику и не должны смешиваться.

Игнорирование клиентского disconnect не должно автоматически означать отмену durable ресурса.

---

## 17. Retry определяется семантикой операции

Операции должны классифицироваться как минимум по возможности безопасного повторения.

Принципиальные категории:

- безопасно повторяемая;
- идемпотентная при определённых условиях;
- не допускающая автоматический retry после неопределённого исхода.

Если side effect мог произойти, а ответ потерян, допустим outcome `unknown`.

Нельзя считать transport failure доказательством того, что операция не выполнилась.

---

## 18. Failure model является частью application contract

Ошибки не должны сводиться к случайным exceptions конкретной библиотеки.

Application layer обязан нормализовать значимые классы ошибок и outcomes так, чтобы:

- REST мог вернуть программно обрабатываемую ошибку;
- MCP мог вернуть агенту repairable structured response;
- observability могла отличать validation, policy, upstream, timeout, lost resource и unknown outcome.

---

## 19. Provenance сохраняется для полученного и производного контента

Raw и derived representations должны иметь происхождение.

Для производного результата должно быть возможно определить:

- исходный ContentObject;
- producer/parser;
- producer version/revision, если это важно для воспроизводимости;
- время создания;
- параметры преобразования, если они влияют на результат.

Это позволяет повторно парсить сохранённый контент без нового Retrieval и сравнивать версии обработки.

---

## 20. ContentStore отделён от PostgreSQL metadata

Крупные bytes и бинарные материалы не должны безусловно храниться в JSON/строковых колонках PostgreSQL.

Базовая модель:

```text
PostgreSQL → durable metadata / ownership / lifecycle / references
ContentStore → raw и derived bytes
```

Storage backend должен быть заменяемым через port.

Локальный filesystem и S3-compatible storage не должны менять application contracts.

---

## 21. Redis не является общим source of truth

Redis используется для тех задач, где он подходит:

- cache;
- rate limits;
- queues;
- locks;
- leases/fencing;
- routing metadata;
- coordination/events.

Durable состояние не должно становиться неявно зависимым только от наличия volatile Redis key, если по контракту оно должно переживать restart.

---

## 22. Live browser state принадлежит Browser Worker

Объекты Playwright (`Browser`, `BrowserContext`, `Page`, `Locator`) существуют только внутри browser runtime, который ими владеет.

Они не сериализуются в PostgreSQL и не передаются через REST/MCP.

Control plane хранит только необходимые metadata/handles/routing state.

---

## 23. Horizontal scaling не должен требовать смены application contracts

Архитектура изначально должна позволять независимо масштабировать:

- API/MCP control plane;
- job workers;
- browser workers;
- search infrastructure;
- ContentStore;
- PostgreSQL/Redis deployment.

Локальный однопроцессный режим не должен становиться скрытым архитектурным предположением.

---

## 24. Ports принадлежат потребляющему application-модулю

Application layer объявляет интерфейсы, которые ему нужны.

Например:

```text
Search → SearchProvider
Retrieval → HttpFetcher / URL policy ports
Content → ContentStore / NativeParser registry
Browser → BrowserWorkerClient / BrowserSessionRepository
Jobs → JobQueue / JobRepository
```

Infrastructure реализует эти ports.

Не следует создавать глобальную папку-свалку с несвязанными interfaces без владельца.

---

## 25. Provider-specific детали не протекают в общий contract без причины

Внутренние параметры SearXNG, Yandex, HTTPX, Playwright, Redis или конкретного storage backend не должны автоматически становиться domain/application/MCP contract.

Если параметр нужен клиенту, он должен быть переосмыслен как стабильное agent/application-facing понятие.

---

## 26. Security является частью архитектуры

SSRF, DNS rebinding, redirects, egress, download handling, content limits, browser isolation, secrets, quotas и safe logging проектируются до production-интеграции, а не добавляются постфактум.

BrowserContext считается изоляцией browser state, но не общей security sandbox.

---

## 27. Observability проектируется без превращения всего в Job

Structured logs, metrics, tracing и operation correlation должны быть доступны и для request-bound операций.

Нельзя превращать каждое действие в durable job только ради истории или диагностики.

Durable audit и telemetry являются разными понятиями.

---

## 28. MCP schema является частью agent UX

MCP facade проектируется для LLM, а не как автоматическая копия backend signature.

Для каждого tool важны:

- однозначное русскоязычное description;
- подробные descriptions аргументов;
- machine-readable constraints;
- корректные defaults;
- ясная `null`/omission semantics;
- cross-field invariants в JSON Schema, когда это возможно;
- structured validation errors;
- корректные MCP annotations.

Runtime всё равно обязан самостоятельно валидировать arguments.

---

## 29. Agent-facing тексты проекта — преимущественно на русском

Docstrings MCP-tools, descriptions параметров, agent-facing hints и пояснения ошибок должны быть на русском языке, если нет веской причины использовать другой язык.

Технические identifiers, field names, class/function names и error codes могут оставаться английскими.

---

## 30. REST является мощным facade, MCP — удобным facade

REST должен предоставлять полный и пригодный для программных клиентов доступ к стабильным application capabilities.

MCP должен предоставлять практически ту же полезную мощность через меньшее количество ясных agent-facing операций.

Упрощение MCP не должно превращать его в игрушечный или искусственно ограниченный интерфейс.

---

## 31. Документация проектируется для реализации

Design-документ считается полезным только если по нему coding agent может однозначно понять:

- ответственность компонента;
- non-goals;
- contracts;
- invariants;
- ports;
- lifecycle;
- persistence;
- concurrency;
- failure semantics;
- tests;
- acceptance criteria.

Version docs не должны заново изобретать архитектуру. Они реализуют уже утверждённый design по безопасной последовательности патчей.
