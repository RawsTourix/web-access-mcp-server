# Концепция проекта Web Access MCP

## Статус документа

Этот документ фиксирует **общее направление и предметную границу** проекта `web-access-mcp-server`.

Он намеренно не является технической спецификацией. Точные runtime-протоколы, библиотеки, схемы БД, REST endpoints, MCP tools, limits и version implementation plans принадлежат `docs/design/`.

Если формулировка этого concept-документа расходится с более поздним accepted Design/ADR/contract, приоритет имеет каноническая design-документация.

---

# 1. Что такое Web Access MCP

`Web Access MCP` — самостоятельный production-oriented сервис программируемого доступа к вебу.

Он предназначен прежде всего для собственного ИИ-агента, но не должен зависеть от его внутренней реализации и остаётся пригодным для других MCP/REST клиентов.

Основные классы возможностей:

```text
Search
Retrieval
Content
Browser
Jobs
```

Сервис должен оставаться удобным локально, но архитектурно быть готовым к:

- множеству одновременных клиентов;
- нескольким API/MCP replicas;
- нескольким Browser/Job workers;
- PostgreSQL/Redis;
- отдельному Content storage;
- production observability/security/recovery.

Это не одноразовый MVP и не wrapper вокруг одного API.

---

# 2. Backend-first

Ключевой порядок:

```text
предметная задача
→ domain/application backend
→ ports/adapters/runtime
→ REST facade
→ MCP facade
```

REST и MCP используют общий backend.

Нельзя строить application logic вокруг заранее придуманного tool/endpoint.

REST и MCP могут иметь разные DTO/granularity, но не дублируют business logic.

---

# 3. Роль REST

REST — богатый программный facade.

Он предназначен для:

- других микросервисов;
- web/admin UI;
- automation;
- diagnostics/operator tasks;
- полного typed доступа к stable backend capabilities.

REST может быть существенно подробнее MCP, но не превращается в raw proxy SQL/Redis/HTTPX/Playwright/provider API.

---

# 4. Роль MCP

MCP — компактный agent-facing facade для LLM.

Требования:

- один понятный intent на tool;
- detailed Russian descriptions/docstrings;
- строгая JSON Schema;
- machine-readable bounds/invariants;
- structured repairable errors;
- bounded results;
- opaque resource handles;
- корректные retry/side-effect annotations;
- отсутствие infrastructure/provider internals.

Agent-facing тексты по умолчанию пишутся на русском. Technical identifiers остаются английскими.

---

# 5. Web Access не является reasoning engine

Сервис выполняет явно заказанные операции и сообщает наблюдаемый результат.

Он не должен скрыто решать за агента:

```text
мало search results → сменить provider
пустой HTML → автоматически Browser
scan PDF → автоматически OCR
legacy DOC → автоматически LibreOffice
```

Вместо скрытого fallback сервис может вернуть **structured hint**, если рекомендация следует из объективного результата.

Пример:

```text
HTML получен, native content отсутствует,
структура похожа на JS-rendered shell
→ hint: browser capability may be useful
```

Hint — рекомендация, а не автоматическая orchestration.

---

# 6. Search

Search отвечает только за поисковую выдачу через explicit/configured providers.

Базовое направление:

```text
SearchProvider
├── SearXNG
├── Yandex Search
└── future providers
```

Search:

- нормализует provider output;
- сохраняет ranking/provenance;
- учитывает cache/rate/cost policy;
- не читает найденные страницы;
- не комбинирует providers hidden heuristic-ой;
- не считает snippet содержимым target page.

---

# 7. Retrieval

Retrieval отвечает за безопасное получение уже известного HTTP(S)-ресурса.

Граница:

```text
URL
→ validate/security
→ HTTP acquisition
→ raw ContentObject
```

Retrieval не запускает Browser и не выполняет L2 processing.

Security — часть базовой ответственности: SSRF, DNS/IP/redirect/size/decompression/egress constraints не являются optional hardening «на потом».

---

# 8. Content

Content владеет уже полученными материалами:

```text
Storage
Identification
L0 Inspection
L1 Native Parsing
Representations
Provenance
```

## L0 — Inspection

Дешёвая детерминированная информация:

- формат/MIME;
- размер/hash;
- страницы/dimensions;
- container/basic metadata;
- наличие непосредственно доступного text layer и другие format properties.

## L1 — Native Parsing

Прямое чтение структуры файла без тяжёлого semantic/visual processing.

Примеры:

```text
HTML → text/metadata/links
PDF text layer → text
JSON/XML/CSV → structure
DOCX/XLSX/PPTX → directly readable OOXML data
ODF/EPUB/FB2/SVG → directly readable container/XML content
```

Поддержка нового формата добавляется через parser/capability registry и не требует нового MCP tool на каждый extension.

---

# 9. L2 за границей Web Access

Advanced document/media processing — отдельная ответственность.

К L2 относятся:

- OCR;
- layout recognition;
- VLM/vision understanding;
- LibreOffice conversion;
- speech transcription;
- semantic video/image processing;
- другие тяжёлые CPU/GPU workflows.

Web Access может сохранить результат внешнего processor как derived Content с provenance, но не обязан сам выполнять L2.

Если L1 невозможен, нормальный результат:

```text
raw ContentObject
+ inspection/diagnostics
+ optional generic processing hint
```

---

# 10. Browser

Browser — отдельный stateful runtime для настоящего browsing/JS rendering/interaction.

BrowserSession:

- имеет opaque handle;
- переживает MCP reconnect;
- не принадлежит одному HTTP/MCP transport connection;
- имеет server-side TTL/reaper;
- владеет Pages/snapshots/actions;
- работает через отдельный Browser runtime boundary.

Browser используется **явно**, а не как hidden fallback Retrieval.

---

# 11. Jobs

Не каждая операция является Job.

Request-bound операции выполняются непосредственно, пока их semantics подходит синхронному request/response.

Durable Job используется для явно выбранной long-running/background capability, которая должна переживать disconnect/restart и иметь persistent progress/result lifecycle.

Queue не является заменой application architecture.

---

# 12. PostgreSQL, Redis и ContentStore

Эти компоненты имеют разные роли:

```text
PostgreSQL
→ durable structured source of truth

Redis
→ cache / rate / coordination / queue wake-up / short-lived routing

ContentStore
→ большие immutable text/binary payloads
```

Ни Redis keys, ни SQLAlchemy models, ни storage paths не должны определять public application contract.

---

# 13. Масштабируемость

Архитектура должна позволять независимо масштабировать:

- Control Plane;
- Job Workers;
- Browser Workers;
- SearXNG;
- PostgreSQL/Redis;
- Content storage.

Stateful resources имеют явных owners/lifecycle и не зависят от конкретной API replica.

---

# 14. Security и recovery

Web Access работает с недоверенным вебом, поэтому с самого начала учитывает:

- authentication/principal ownership;
- SSRF/egress;
- browser isolation;
- parser isolation/resource limits;
- quotas/backpressure;
- retry/idempotency/unknown outcome;
- cleanup/retention;
- crash/restart reconciliation;
- observability/audit.

«Работает в happy path» недостаточно для завершённого решения.

---

# 15. Текущий источник истины

После concept layer архитектура подробно спроектирована в:

```text
docs/design/
```

Начинать coding work следует с:

```text
docs/AGENTS.md
→ docs/design/current.md
→ target design/ADR/contracts
→ target version implementation sequence
```

Concept-документ не заменяет эти спецификации.
