# v0.2 — Search Runtime

## Статус

`ready for implementation`

Версия добавляет первый полноценный web capability — Search — через общий backend, REST и MCP.

Подробный порядок: `implementation-sequence.md`.

---

# 1. Цель

После v0.2 Web Access должен:

- выполнять batch-first web search;
- поддерживать собственный SearXNG как бесплатный default provider;
- поддерживать отдельный optional Yandex Search provider;
- нормализовать provider-specific results в общий application model;
- иметь explicit/default provider selection без hidden fallback;
- иметь cache/freshness/rate/capacity policies;
- иметь provider health/degraded state;
- предоставлять REST Search API;
- предоставлять русскоязычный MCP `web_search` с точной schema.

Search **не читает содержимое найденных страниц**.

---

# 2. Canonical design / ADR

- `../../search.md`;
- `../../application-contracts.md`;
- `../../security.md`;
- `../../observability.md`;
- `../../rest-api.md`;
- `../../mcp.md`;
- ADR-0003 language/region model;
- ADR-0004 Yandex adapter;
- ADR-0005 Search cache/rate/capacity.

---

# 3. Non-goals

- page Retrieval;
- Browser;
- automatic provider fallback;
- provider quality heuristics;
- image/video search;
- scraping search engines directly;
- live billable provider tests in default CI;
- geocoding/fuzzy region inference inside Search.

---

# 4. Application structure

Conceptually:

```text
SearchApplicationService
→ SearchProviderRegistry
   ├── SearXNGProvider
   └── YandexSearchProvider
→ SearchCache
→ SearchRateLimiter
→ ProviderConcurrencyLimiter
→ usage/budget port foundation
```

Transport calls application service only.

Provider adapters do not own cache/rate policy.

---

# 5. Batch-first Search

Одна operation принимает несколько независимых queries с общими options.

No:

```text
search
search_many
```

Input order preserved.

Partial per-query failure does not automatically fail successful queries.

---

# 6. MCP limits

Freeze baseline:

```text
queries: 1..8
results per query: 1..20
```

REST/application may support wider configured bounds under hard server ceiling.

These MCP limits protect LLM context and are contract limits, not heuristics about result quality.

---

# 7. Query model

Stable agent/application concepts:

```text
query
page
limit
language | null
region | null
time_range | null
safe_search
type/category only when common semantic capability is proven
provider = default | provider_id
```

Provider-specific raw parameters do not leak into MCP/common application model.

---

# 8. Language

ADR-0003:

- common normalized language tag (BCP-47-like canonical input semantics);
- provider adapter maps to supported upstream values;
- unsupported provider mapping rejected/normalized explicitly;
- no language guessing from query text as hidden policy.

---

# 9. Region

`SearchRegionId` is canonical configured Web Access region identifier.

Registry maps stable region to provider-specific value.

No:

- automatic geocoding;
- fuzzy city inference;
- provider numeric region exposed directly to LLM.

Unknown region gives repairable validation error and optional supported-values guidance bounded appropriately.

---

# 10. Provider selection

```text
provider omitted/default
→ configured default provider

provider explicit
→ exact provider
```

No:

```text
few results → switch provider
provider error → silently use paid provider
```

Client/Agent chooses next semantic action.

---

# 11. SearXNG provider

Own SearXNG instance is default free provider baseline.

Adapter uses its HTTP JSON Search API.

Provider-specific mapping may include:

- query;
- pageno;
- language;
- time range;
- SafeSearch;
- categories where exposed as stable Web Access concept.

SearXNG runtime is private infrastructure service, not directly exposed public API.

Reference Compose adds version-pinned SearXNG and health/readiness.

---

# 12. Yandex Search provider

ADR-0004:

- direct adapter to official Yandex Search API;
- HTTPX async suitable because destination/configured provider endpoint is trusted/configured;
- credentials/folder/account config server-side;
- no API key in MCP/REST request;
- separate provider health/error mapping;
- billable usage metadata/accounting foundation;
- no hiding Yandex solely as SearXNG engine.

This lets operator disable/account paid provider independently.

---

# 13. SearchResult normalization

Common result contains only stable useful concepts, such as:

```text
rank
title
url
snippet
provider_id
provider-specific engine/source metadata only if normalized and justified
published/observed metadata where provider reliably gives it
query/page provenance
```

Search snippet is explicitly **not** target page content verification.

Raw upstream payload may be retained only bounded diagnosticly, not normal MCP response.

---

# 14. Deduplication

Provider adapter/application may deduplicate obvious duplicate entries **within one provider response/batch** using deterministic normalized URL/result identity rules.

No semantic relevance re-ranking by hidden LLM/heuristic baseline.

Original rank/provenance remains observable where useful.

---

# 15. Cache

ADR-0005:

- Redis-backed;
- key from normalized Search request + provider/revision;
- principal-scoped by default to avoid cross-principal side channels;
- bounded TTL;
- response indicates cached/fetched timestamp/freshness metadata;
- cache outage behavior explicit;
- cache hit never masquerades as fresh upstream call.

No hidden stale-while-forever.

---

# 16. Rate vs concurrency

Separate controls:

```text
rate limiter → operations/units over time
concurrency limiter → active upstream calls
```

Both Redis/distributed where needed.

Provider hard limits and principal policy may be lower.

Failure/retry metadata explicit.

---

# 17. Billable provider foundation

v0.2 records billable usage facts/units but full durable multi-principal budget hardening arrives v0.7.

Cache hit does not count as upstream billable attempt.

Provider cost/accounting is not expressed by hardcoded ruble price in SearchResult.

---

# 18. Failure model

Normalize:

```text
provider_unavailable
provider_rate_limited
provider_timeout
provider_rejected
unsupported_language
unsupported_region
invalid_query
capacity_limited
cache_unavailable (if relevant/degraded)
```

One query item failure in batch preserves successful item results.

No provider exception/stack trace leaks.

---

# 19. Hints

Allowed examples:

- refine/alternative query may help only when based on explicit structured upstream/result state and phrased cautiously;
- provider disabled/unavailable may expose that another configured provider exists, but service does not automatically call it;
- Search result can hint `web_fetch` to read chosen URLs — same-service exact capability recommendation.

No “results look bad” hidden quality score baseline.

---

# 20. REST

At minimum:

```text
POST /api/v1/search
```

plus authorized provider/status discovery where useful for programmatic/operator clients.

REST may expose more stable search options than MCP while still using the same application model.

---

# 21. MCP `web_search`

Description in Russian must clearly say:

- searches public web;
- returns candidate result metadata/snippets;
- does not read target pages;
- use `web_fetch` for selected known URLs.

Actual FastMCP schema tests verify descriptions/bounds/enums/defaults.

---

# 22. Observability

Measure:

- provider calls/cache hits;
- latency;
- outcome/error class;
- rate/concurrency rejects;
- result count bounded aggregate;
- billable usage units;
- provider readiness.

No query text as metric label.

Sensitive query logging follows privacy policy and is not required by default.

---

# 23. Testing

Required:

- provider contract adapters against controlled fixtures;
- SearXNG integration;
- Yandex mocked/recorded non-secret fixture tests;
- no live paid call in default CI;
- batch partial semantics/order;
- region/language mapping;
- cache principal isolation/freshness;
- rate/concurrency races;
- provider outage/recovery;
- REST OpenAPI;
- actual FastMCP `web_search` schema;
- no automatic provider fallback.

---

# 24. Definition of Done

v0.2 complete only if:

1. Search is a clean provider-backed application capability.
2. SearXNG works as default free provider.
3. Yandex is separate optional billable adapter.
4. Provider selection is explicit/default deterministic.
5. Language/region mapping is common, not provider-shaped.
6. Cache/rate/concurrency are separate tested concerns.
7. Search results preserve provenance and do not claim page contents were read.
8. REST/MCP use same backend logic.
9. MCP schema/descriptions are LLM-readable and bounded.
10. No hidden provider fallback/quality heuristic exists.
11. Applicable Search release gates are green.
