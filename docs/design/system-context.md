# System Context Web Access MCP

## Статус документа

Этот документ является каноническим владельцем **границы системы Web Access, внешних акторов, соседних систем и распределения ответственности**.

Он отвечает на вопрос:

> Что входит в Web Access, что находится за его границей и какие обязательства существуют на каждой интеграционной границе?

Точные внутренние contracts компонентов определяются последующими design-документами.

---

# 1. Система в одном предложении

`Web Access MCP` — самостоятельный production-oriented сервис, предоставляющий программным клиентам и ИИ-агентам безопасный, наблюдаемый и масштабируемый доступ к веб-поиску, HTTP(S)-ресурсам, базовому Content processing и stateful browser runtime через общий application backend с REST и MCP facade.

---

# 2. Главная внешняя схема

```text
                    ┌────────────────────┐
                    │   ИИ-агент / LLM   │
                    └─────────┬──────────┘
                              │ MCP
                              ▼
┌─────────────────┐      ┌───────────────────────────┐
│ Другой сервис / │ REST │                           │
│ Web UI / client ├─────►│      Web Access MCP       │
└─────────────────┘      │                           │
                         │ Search / Retrieval        │
                         │ Content / Browser / Jobs  │
                         └──────┬─────────┬───────────┘
                                │         │
                   ┌────────────┘         └───────────────┐
                   ▼                                      ▼
          Search providers /                       Websites / web
             SearXNG etc.                           applications

                         Web Access
                              │
                              │ raw content / diagnostics
                              ▼
                   ┌──────────────────────┐
                   │ Внешний Advanced L2 │
                   │ processing (optional)│
                   └──────────────────────┘
```

Последняя связь является возможностью клиента построить более широкий workflow. Web Access не обязан сам вызывать L2 processing service.

---

# 3. Внешние акторы

## 3.1. ИИ-агент

Основной предполагаемый consumer MCP facade.

ИИ-агент отвечает за:

- reasoning;
- выбор следующего инструмента;
- orchestration нескольких capabilities;
- интерпретацию search/retrieval/content/browser результата;
- решение о необходимости Browser после Retrieval;
- решение о необходимости внешнего L2 processing;
- пользовательский UX и progress presentation со своей стороны.

Web Access предоставляет агенту факты, results, diagnostics и structured hints, но не заменяет agent reasoning.

---

## 3.2. REST client

Программный клиент, использующий более полный REST facade.

Это может быть:

- другой микросервис;
- отдельный Web UI;
- административный интерфейс;
- integration/testing client;
- automation system.

REST client не обязан знать о MCP и не должен зависеть от MCP-specific abstractions.

---

## 3.3. Operator / administrator

Субъект, управляющий deployment/configuration сервиса.

Его ответственность может включать:

- configuration;
- provider credentials;
- quotas/limits;
- deployment topology;
- storage backend;
- observability;
- security policy;
- lifecycle maintenance.

Operator controls не должны смешиваться с обычным agent-facing MCP surface.

---

## 3.4. Search Provider

Внешняя система, возвращающая поисковую выдачу.

Предполагаемые реализации:

- собственный SearXNG;
- Yandex Search;
- будущие providers.

Provider не является частью domain/application model; он находится за `SearchProvider` boundary.

---

## 3.5. Target Website / Web Application

Недоверенная внешняя веб-система, к которой обращается Retrieval или Browser runtime.

Web Access должен считать внешние URL, HTTP responses, HTML, scripts, downloads и browser content недоверенными.

---

## 3.6. Advanced Processing Service

Опциональная внешняя система/инструментарий уровня L2.

Примеры capabilities:

- OCR;
- VLM;
- сложный document layout analysis;
- LibreOffice-based conversion;
- audio transcription;
- multimedia understanding.

Такая система не входит в базовую ответственность Web Access.

---

# 4. Что входит в Web Access

## 4.1. Search

Web Access:

- принимает явный поисковый запрос/application request;
- вызывает выбранный/configured SearchProvider;
- нормализует provider output;
- возвращает search results и provenance/diagnostics;
- поддерживает инфраструктурные cache/rate policies.

Search не обязан читать найденные страницы.

---

## 4.2. Retrieval

Web Access:

- безопасно получает известные HTTP(S)-ресурсы;
- контролирует redirects, DNS/IP/SSRF policy, limits и deadlines;
- фиксирует наблюдаемые response metadata;
- передаёт bytes в Content boundary/storage.

Retrieval не запускает Browser автоматически.

---

## 4.3. Content

Web Access:

- сохраняет raw/derived representations;
- идентифицирует содержимое;
- выполняет L0 Inspection;
- выполняет L1 Native Parsing через поддерживаемые parsers;
- хранит provenance;
- выдаёт representations через стабильные handles/contracts;
- возвращает diagnostics и structured hints, если native parsing недоступен.

---

## 4.4. Browser

Web Access:

- создаёт и закрывает managed BrowserSession;
- маршрутизирует действия owning Browser Worker;
- выполняет navigation/observation/interaction capabilities;
- управляет session lifecycle/TTL/cleanup;
- нормализует результаты и ошибки;
- может создавать ContentObjects из browser output/download/export.

Browser lifecycle не принадлежит MCP/HTTP connection.

---

## 4.5. Jobs

Web Access предоставляет durable execution model только тем операциям, которым это требуется по семантике.

Jobs должны переживать transport disconnect и иметь собственный lifecycle/persistence/cancellation model.

---

# 5. Что не входит в Web Access

Web Access не является:

- универсальным ИИ-агентом;
- research planner;
- reasoning engine;
- OCR-платформой;
- универсальным office/document converter;
- мультимодальной VLM-платформой;
- speech-to-text сервисом;
- бесконечным crawler по умолчанию;
- CAPTCHA bypass/anti-bot evasion системой;
- сервисом скрытой авторизации на сторонних сайтах;
- пользовательским браузером общего назначения без policy/lifecycle ограничений.

Такие capabilities могут появляться как отдельные проекты/инструменты и комбинироваться агентом.

---

# 6. Search и Content — разные ответственности

Search result является поисковой выдачей, а не содержимым найденной страницы.

```text
Search
→ candidate URLs + snippets + metadata

Retrieval/Browser
→ фактическое содержимое URL
```

Нельзя считать search snippet доказательством того, что Web Access прочитал целевую страницу.

---

# 7. Retrieval и Browser — разные ответственности

Retrieval выполняет ordinary HTTP(S) access.

Browser выполняет stateful browser runtime с JavaScript execution и interaction.

```text
Retrieval result: минимальный JS shell
→ вернуть наблюдаемый результат + возможный hint
→ клиент решает, запускать ли Browser
```

Не существует обязательного hidden fallback Retrieval → Browser.

---

# 8. Content и Advanced Processing — разные ответственности

Если Content может получить данные через L0/L1, он делает это непосредственно.

Если требуется OCR/VLM/conversion другого класса:

```text
Content
→ raw object + diagnostics + neutral hint
→ client/agent решает следующий шаг
```

Web Access не обязан знать, какой конкретный внешний processor будет использован.

---

# 9. Structured hints на системной границе

Hints являются advisory частью результата.

Примеры внутренних capabilities Web Access:

```text
browser_may_be_required
native_parser_available
content_representation_available
```

Для внешних capabilities предпочтительны нейтральные hints:

```text
advanced_processing_may_be_required
native_text_unavailable
unsupported_native_format
```

Нежелательно жёстко писать:

```text
use_liteparse
use_libreoffice
```

если конкретный внешний продукт не входит в deployment contract.

---

# 10. Trust boundaries

## 10.1. Client → Web Access

Недоверенными считаются:

- arguments;
- URLs;
- uploaded/referenced content;
- opaque handles до проверки ownership/policy.

Transport validation не заменяет application validation.

## 10.2. Web Access → Internet

Интернет является недоверенной сетью.

Необходимо контролировать:

- SSRF;
- DNS rebinding;
- redirects;
- response sizes;
- decompression;
- timeouts;
- downloads;
- content types;
- browser egress.

## 10.3. Web Content → Agent

Полученное содержимое является данными, а не инструкцией Web Access.

Сервис должен сохранять границу между:

- web content;
- application diagnostics;
- trusted MCP descriptions/hints.

Agent-facing protocol не должен смешивать недоверенный текст страницы с canonical server instruction.

---

# 11. Ownership boundary

ContentObject, BrowserSession, Job и другие addressable resources должны иметь owner/principal context.

Client не получает доступ к resource только потому, что знает opaque handle.

Web Access проверяет handle + ownership/policy на своей стороне.

---

# 12. Lifecycle boundary

Клиент может запросить cleanup, но Web Access остаётся окончательным владельцем server-side lifecycle.

```text
client cleanup request
→ best effort ускорение cleanup

server TTL/reaper/reconciliation
→ окончательная гарантия освобождения временного ресурса
```

Transport disconnect не является lifecycle event ресурса сам по себе.

---

# 13. Data boundaries

Предварительное разделение:

```text
PostgreSQL
→ structured durable metadata / lifecycle / source of truth

Redis
→ cache / queues / locks / routing / coordination

ContentStore
→ крупные raw/derived bytes

Browser Worker memory
→ live Playwright state
```

Ни одна из этих систем не должна неявно подменять роль другой.

---

# 14. Deployment boundary

Web Access является одним продуктом/репозиторием, но не обязательно одним process/container.

Внутри system boundary могут существовать:

- API/MCP control plane;
- Job Workers;
- Browser Workers;
- internal persistence/coordination adapters.

SearXNG, PostgreSQL, Redis и external object storage могут быть отдельными deployment components и не обязаны жить в одном container/process.

---

# 15. Integration с собственным ИИ-агентом

Основной собственный агент подключает Web Access как builtin MCP service через стабильный MCP contract.

Web Access не импортирует внутренние классы Agent Runtime.

Агент не импортирует внутренние классы Web Access.

Общие обязательства задаются protocol/integration contracts, а не shared implementation code.

---

# 16. Совместимость с другими агентами и клиентами

Web Access не должен быть технически привязан только к одному агенту.

Собственный агент является главным consumer и может использовать расширенные trusted presentation/lifecycle integration со своей стороны, но базовый MCP facade должен оставаться корректным MCP interface для других совместимых clients.

REST facade обеспечивает ещё более нейтральный программный доступ.

---

# 17. Критерий правильной system boundary

Новая capability находится внутри Web Access, если она преимущественно отвечает за **доступ к вебу, управление веб-ресурсом или дешёвое непосредственное представление уже полученного web content** и логично разделяет lifecycle с существующими подсистемами.

Capability должна рассматриваться как отдельная система, если она:

- требует самостоятельного тяжёлого compute/runtime класса;
- имеет существенно другой предметный lifecycle;
- не является необходимой частью безопасного web access;
- может развиваться независимо и использоваться вне Web Access.

При сомнении решение фиксируется ADR до включения новой ответственности в system boundary.
