# v0.2 — Search Runtime

## Статус

`design in progress`

Версия реализует первый полноценный Web Access capability — Search — через общий application backend, REST и MCP.

---

# 1. Цель

После v0.2 клиент должен уметь:

```text
query/queries
→ Web Access Search
→ SearXNG или explicit Yandex
→ normalized ranked results
```

с:

- batch-first semantics;
- cache/freshness;
- distributed rate/capacity protection;
- provider health;
- billable accounting;
- REST API;
- MCP `web_search`.

---

# 2. Prerequisites

- accepted v0.1 Service Foundation;
- `../../search.md`;
- `../../rest-api.md`;
- `../../mcp.md`;
- `../../security.md`;
- `../../observability.md`;
- `../../testing.md`;
- `../../decisions/ADR-0003-search-language-region-model.md`;
- `../../decisions/ADR-0004-yandex-search-adapter.md`;
- `../../decisions/ADR-0005-search-cache-rate-capacity.md`.

---

# 3. Scope

## Application

- `SearchApplicationService`;
- Search batch/query/result models;
- SearchProvider port/registry;
- provider capabilities;
- SearchRegionRegistry;
- default/explicit provider resolution;
- cache/freshness metadata;
- provider rate/concurrency ports;
- usage accounting hooks.

## Infrastructure

- SearXNGProvider;
- YandexSearchProvider;
- Redis SearchCache;
- Redis token bucket;
- Redis distributed provider concurrency lease;
- provider HTTP clients;
- SearXNG Compose service.

## REST

- `POST /api/v1/search`;
- `GET /api/v1/search/providers`;
- detailed provider status через existing status/admin boundary настолько, насколько входит v0.2.

## MCP

- `web_search`.

---

# 4. Non-goals

- Retrieval/read URL;
- Browser;
- auto provider fallback;
- search reranking;
- semantic deduplication;
- image/video/news search;
- arbitrary SearXNG engine selection LLM-ом;
- dynamic geocoding региона;
- scraping yandex.ru HTML;
- live billable calls в ordinary CI.

---

# 5. SearXNG role

SearXNG — configured default free provider.

Web Access обращается к private SearXNG HTTP API и получает JSON result.

Underlying engines/configuration принадлежат SearXNG deployment.

`web_search` не принимает engine names.

---

# 6. Yandex role

Yandex — explicit optional billable provider.

Используется официальный Yandex Search API v2-compatible adapter через HTTPX согласно ADR-0004.

Yandex не является hidden fallback SearXNG.

---

# 7. Provider config

Configuration должна поддерживать:

```text
search.default_provider
search.providers.searxng.*
search.providers.yandex.*
search.regions.*
search.cache.*
search.rate_limits.*
search.concurrency.*
```

Disabled provider может не иметь credentials.

Enabled provider с invalid mandatory config делает соответствующую capability unavailable/fail-fast согласно profile, но не должен случайно раскрывать secret.

---

# 8. Search Region registry

По ADR-0003:

- canonical region IDs operator-configured;
- no free-form place guessing;
- Yandex raw region ID hidden;
- missing mapping rejected;
- region config revision учитывается cache/provenance.

Initial repository должен содержать example region config, а не претендовать на полный мировой справочник.

---

# 9. Search language

Application принимает normalized language tag.

Implementation sequence фиксирует validation/mapping rules.

`null` = provider/configured default.

---

# 10. Cache

По ADR-0005:

- Redis;
- normalized typed JSON result;
- hashed canonical key;
- principal-scoped default;
- configurable shared-public mode;
- provider/config/region/schema revision;
- freshness observable.

Cache failure не отменяет successful provider result.

---

# 11. Rate/capacity

- distributed Redis token bucket;
- principal + global provider policy;
- distributed provider concurrency lease + local semaphore;
- cache hit не потребляет provider rate/concurrency;
- mandatory limiter Redis outage → fail closed для upstream calls.

---

# 12. Usage accounting

Yandex actual upstream attempts записываются/наблюдаются отдельно от cache hits.

Exact durable accounting schema может быть minimal в v0.2, но должна позволять впоследствии считать confirmed attempts/usage без реконструкции из logs.

Pricing не хардкодится.

---

# 13. REST contract direction

`POST /api/v1/search` поддерживает batch items с богатой per-query application projection.

REST может иметь:

- разные provider/options per query item;
- provider/freshness metadata;
- detailed typed errors.

MCP будет проще.

---

# 14. MCP `web_search`

Baseline schema direction:

```text
queries: list[str]
provider: default | searxng | yandex = default
page: int = 1
limit: int = 10
language: str | null = null
region: str | null = null
safe_search: off | moderate | strict | null = null
time_range: day | month | year | null = null
```

Все options общие для batch.

Если нужны разные параметры — отдельные tool calls.

Hard bounds фиксируются `implementation-sequence.md` после provider/schema review.

---

# 15. MCP description requirement

Description обязан явно сообщать:

- tool ищет ссылки/поисковую metadata;
- snippets не являются содержимым страниц;
- найденный URL читается будущим `web_fetch`;
- Yandex может быть billable;
- отсутствие результатов не запускает другой provider автоматически.

---

# 16. Provider errors

Должны быть различимы:

- provider unavailable;
- provider auth/config failure;
- rate limited;
- capacity unavailable;
- unsupported option/region/language;
- timeout;
- upstream protocol error;
- malformed response.

Один provider outage не выключает другой provider.

---

# 17. Health

Capability status:

```text
Search
├── default provider state
├── SearXNG state
└── Yandex state
```

Service может быть Search-ready при недоступном optional Yandex.

---

# 18. Required gates

- G0–G7;
- G12 Observability;
- G13 REST;
- G14 MCP;
- G15 Deployment для добавления SearXNG;
- G17 relevant Redis/provider races;
- G20 own-agent MCP integration;
- G21 docs consistency.

---

# 19. Acceptance criteria

1. `web_search` реально доступен через MCP.
2. REST Search использует тот же SearchApplicationService.
3. Один/N queries используют batch-first contract.
4. SearXNG default search работает через private service.
5. Yandex explicit search работает через official adapter при configured secret.
6. Нет hidden fallback между providers.
7. Provider ranking сохраняется.
8. Empty result successful.
9. Unsupported options rejected, не ignored.
10. Region mapping exact/configured.
11. Cache hit/freshness visible.
12. Principal-scoped cache isolation работает.
13. Redis token bucket/distributed capacity работают multi-replica.
14. Redis limiter outage не bypass-ит mandatory rate policy.
15. Yandex cache hit не вызывает billable upstream.
16. Default CI Yandex live calls = 0.
17. Actual MCP/OpenAPI schemas contract-tested.
18. `web_search` descriptions русские и достаточны для agent discovery/schema workflow.
19. Search не создаёт ContentObject и не читает URL.

---

# 20. Remaining blockers

Перед `ready for implementation` требуется создать `implementation-sequence.md` и зафиксировать:

1. exact language validation/mapping;
2. exact MCP schema hard limits;
3. exact initial SearXNG HTTP request mapping/profile;
4. exact current Yandex v2 endpoint/request serializer based on official docs + previous working code;
5. exact Redis JSON serialization/key namespace;
6. token-bucket/concurrency Lua/data structures;
7. minimal durable Yandex usage table/model;
8. initial example SearchRegion config.
