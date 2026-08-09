# ADR-0004 — Yandex Search adapter: direct official REST API over HTTPX

**Статус:** accepted

## 1. Контекст

У проекта уже есть рабочий опыт использования Yandex Search API как отдельного MCP-сервера.

В Web Access Yandex должен стать дополнительным billable `SearchProvider`, сохраняя:

- отдельный billing/accounting;
- отдельные credentials;
- provider-specific constraints;
- возможность отключения;
- отсутствие зависимости бесплатного SearXNG от Yandex.

Нельзя прятать Yandex только как один underlying engine SearXNG, иначе Web Access потеряет прямой контроль над usage/cost/errors/provider semantics.

---

## 2. Рассмотренные варианты

### A. Использовать только Yandex через SearXNG

Просто для Search core, но теряются точный billing/provenance/direct provider health и возможность использовать официальный API независимо от SearXNG engine configuration.

### B. Использовать Yandex SDK/Cloud SDK как обязательную dependency

Может упростить auth/types, но добавляет более тяжёлую provider-specific dependency и сильнее связывает adapter с SDK release cycle.

### C. Прямой официальный Yandex Search REST API через HTTPX

Минимальная dependency surface; Web Access сам контролирует request/response mapping, timeouts, retries, telemetry и credentials.

---

## 3. Решение

Принимается вариант **C**.

`YandexSearchProvider` использует официальный поддерживаемый Yandex Search API REST interface через shared/bounded async HTTPX client/provider transport.

Adapter не использует scraping публичной HTML-страницы yandex.ru.

---

## 4. API version

Baseline adapter ориентируется на текущую официальную **Yandex Search API v2** contract line, используемую в документации Yandex Cloud на момент реализации.

Exact endpoint path/request/response shape фиксируется integration contract tests после выбора locked implementation date/version.

Если Yandex изменит API, обновляется только provider adapter и его tests, а common Search contract остаётся стабильным.

---

## 5. Configuration

Provider config conceptually содержит:

```text
provider_id = yandex
enabled
endpoint/base URL
folder_id / project-scope identifier, требуемый официальным API
API credential/secret reference
request timeout profile
provider limits
configuration revision
```

Secret не возвращается в REST/MCP/health/logs.

Endpoint operator-configurable только для test/staging/official-compatible deployment; LLM/client его не передаёт.

---

## 6. Authentication

Используется официальный supported Yandex API authentication mechanism для выбранного Search API contract.

Credential находится в provider configuration/secret store.

Search request не содержит API key в agent-facing schema.

Adapter обязан redacted auth headers/fields в errors/logs.

---

## 7. HTTP client

Yandex adapter использует отдельный provider-scoped HTTPX client/pool или shared provider transport с отдельными limits.

Он **не использует Retrieval SafeHttpFetcher** как public-web fetcher, потому что Yandex endpoint является заранее доверенным configured upstream provider, а не arbitrary user URL.

При этом:

- TLS verify обязателен;
- endpoint allowlisted/configured;
- bounded response size;
- timeout/deadline;
- retry policy;
- tracing/metrics.

---

## 8. Common mapping

Adapter маппит только common Search concepts:

```text
query
page
limit
language, если supported mapping существует
region через SearchRegionRegistry
safe_search
time_range, только если official API имеет эквивалентную semantics
```

Unsupported common option rejected через provider capability layer.

Не следует симулировать отсутствующую capability query rewriting-ом.

---

## 9. Pagination

Application page = 1-based.

Adapter переводит её в provider-specific page numbering/fields.

Provider raw numbering не протекает наружу.

Integration tests обязаны проверять first/second page mapping.

---

## 10. Result normalization

Provider response преобразуется в common `SearchResultItem`:

```text
rank
title
url
snippet
published_at, если надёжно доступно
provider provenance
```

Provider-specific XML/JSON/raw response structure не возвращается обычному REST/MCP caller.

Raw protocol fragment может сохраняться только в bounded/redacted diagnostic fixture/log profile, если это реально требуется debugging.

---

## 11. Provider score

Yandex-specific relevance/weight не становится canonical cross-provider `score`.

Порядок выдачи сохраняется как `rank`.

---

## 12. Billable accounting

Каждый фактический upstream request должен иметь observable accounting event/record.

Минимально различаются:

```text
request not sent
request sent
response received
provider rejected/rate-limited
cache hit (upstream request absent)
```

Если Yandex billing считается на запрос независимо от успешности ответа, accounting implementation должна отражать provider semantics после проверки официальных условий.

Цена в рублях/валюте **не хардкодится** в provider adapter.

---

## 13. Retry и стоимость

Yandex provider относится к read-only Search, но automatic retries могут увеличить расходы.

Поэтому:

- retry только на ограниченный набор доказуемо transient ошибок;
- finite small retry count;
- backoff/jitter;
- deadline-aware;
- retry count observable;
- rate-limit `Retry-After`/provider signal respected, если присутствует;
- не retry validation/auth/quota/permanent 4xx.

Exact policy конфигурируется v0.2 implementation.

---

## 14. Cache

Search cache расположен над provider adapter.

Следовательно cache hit:

```text
→ Yandex upstream call = 0
→ billable request = 0 для этого serving operation
```

если provider pricing не имеет другого externally incurred cost.

Cache key включает provider/config/region mapping revision.

---

## 15. Provider health

Health status учитывает:

- config validity;
- credential presence;
- recent actual call results;
- rate/quota state, если достоверно известно;
- operator enable/disable.

Health check не выполняет billable search query только ради readiness.

---

## 16. Testing

Default CI:

- request serialization fixtures;
- response parsing fixtures;
- mocked/controlled provider HTTP server;
- auth redaction;
- pagination;
- region mapping;
- safe search;
- provider error mapping;
- retry/accounting.

Optional manually triggered live smoke:

- requires secret;
- hard request budget;
- no fork/untrusted execution;
- records call count;
- never required for ordinary PR acceptance.

---

## 17. Why no official SDK baseline

Direct HTTPX is chosen because Search API contract is narrow and HTTP-oriented.

Если в будущем официальный SDK даст существенные преимущества (auth rotation, generated stable types, protocol migration), adapter может перейти на него через отдельное ADR без изменения `SearchProvider`/REST/MCP contracts.

---

## 18. Compatibility with previous Yandex service

При реализации adapter следует сравнить request/response semantics с уже рабочим Yandex Search MCP-кодом пользователя и переиспользовать проверенные parsing/configuration решения, если они соответствуют актуальному официальному API.

Нельзя blindly копировать старый код без актуальной protocol verification.

---

## 19. Acceptance

1. Yandex отдельный SearchProvider, а не hidden SearXNG fallback.
2. Adapter использует официальный API, не HTML scraping.
3. HTTPX используется через bounded provider client.
4. Credentials скрыты от LLM/public API/logs.
5. Application page mapping tested.
6. Region использует ADR-0003 registry, не raw provider ID.
7. Unsupported options rejected.
8. Results нормализованы в common schema.
9. Provider rank сохранён без reranking.
10. Cache hit не вызывает Yandex upstream.
11. Billable request/retry observability существует.
12. Default CI делает 0 live billable calls.
13. Provider outage не отключает SearXNG Search capability.

---

## 20. Не определяется

- exact Yandex endpoint constant текущей release;
- exact request XML/JSON serialization classes;
- initial retry count;
- live-smoke frequency;
- pricing table;
- initial region mappings.

Эти details фиксируются v0.2 implementation sequence после verification against official docs and existing working implementation.
