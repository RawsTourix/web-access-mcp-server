# v0.2 — Search Runtime implementation sequence

## Статус

`ready for implementation`

Все архитектурные blockers v0.2 закрыты ADR-0003/0004/0005 и этим документом.

---

# 1. Exact contract choices

## 1.1 Language

Добавить dependency:

```text
langcodes
```

и использовать её только как BCP-47 language tag parser/normalizer.

Application `language`:

- `None` → provider default;
- нормализуется `langcodes.standardize_tag`/эквивалентным API locked version;
- invalid tag rejected до provider;
- provider adapter может поддерживать только subset/base language и обязан это отразить capability/validation.

Не выполнять language detection текста query.

## 1.2 SearchRegionId

Canonical pattern:

```regex
^[a-z0-9][a-z0-9-]{0,63}$
```

Registry загружается из typed Search settings.

Initial example config должен показать как минимум структуру для:

```text
ru-moscow
```

но production не обязан включать этот mapping, если operator не настроил Yandex region ID.

## 1.3 MCP hard limits

`web_search` schema:

```text
queries: 1..8 items
query string: 1..2048 chars после trim validation
page: 1..100, default 1
limit: 1..20, default 10
provider: default | searxng | yandex, default default
```

`language`, `region`, `safe_search`, `time_range` optional.

Почему limit ≤20:

- MCP result должен оставаться bounded для LLM;
- 8×20 уже даёт максимум 160 result items;
- более широкие программные выгрузки доступны REST;
- агент может запросить следующую page отдельным вызовом.

Это hard public MCP contract, не dynamic provider limit.

## 1.4 REST/application limits

Application policy configurable, но имеет hard safety ceiling в Settings.

Initial defaults:

```text
max_batch_queries = 32
max_query_chars = 4096
max_results_per_query = 50
max_page = 100
```

REST Pydantic schema использует stable upper safety ceiling; operator quotas могут быть строже runtime policy.

Provider-specific limits дополнительно применяются adapter-ом.

## 1.5 SearXNG mapping

Use async HTTPX GET/POST to configured:

```text
{base_url}/search
```

Baseline params:

```text
q=<query>
format=json
categories=general
language=<tag> when provided
pageno=<application page>
safesearch=0|1|2
time_range=day|month|year when provided
```

Mapping:

```text
off      → 0
moderate → 1
strict   → 2
```

`region` unsupported baseline SearXNG capability unless future configured adapter extension proves exact semantics.

Validate JSON response with provider-specific Pydantic model; do not trust arbitrary dict shape.

## 1.6 Yandex API v2 mapping

Baseline official endpoint:

```text
https://searchapi.api.cloud.yandex.net/v2/web/search
```

Endpoint configurable for test, but production default above.

Use HTTPX POST JSON + official API-key authentication required by current Yandex Search API v2.

Provider configuration contains:

```text
folder_id
api_key SecretStr
endpoint
```

Baseline request uses provider v2 concepts:

- query text;
- search type/localization required by official API;
- page mapping from application 1-based to provider numbering;
- grouping/docs-per-page sufficient to obtain requested `limit`;
- family/safe-search mapping where official API provides equivalent semantics;
- Yandex region ID from ADR-0003 registry.

Current API response `rawData`/official response representation must be decoded/parsing exactly according to locked official contract. Reuse parsing logic from the user's previous Yandex Search service where compatible, but integration tests must verify current official response fixture.

Do not expose Yandex request enums/raw XML fields publicly.

## 1.7 Cache serialization

Use versioned UTF-8 JSON via Pydantic `model_dump_json`/standard JSON semantics.

No pickle.

Redis key namespace:

```text
wa:search:cache:v1:<sha256 canonical request>
```

Canonical request serialization sorted/deterministic.

Principal-scoped mode includes stable `principal_id` in **hashed canonical input**, not plaintext key suffix.

## 1.8 Cache TTL initial defaults

Config defaults:

```text
SearXNG: 300 seconds
Yandex:  300 seconds
```

These are operational defaults, not semantic freshness guarantees.

Response always includes original upstream `retrieved_at`.

Operator can change TTL.

## 1.9 Single-flight

Redis short lease lock:

```text
wa:search:singleflight:v1:<same request hash>
```

Use random holder token + atomic SET NX PX.

Wait bounded to remaining deadline / configured `singleflight_wait_max`.

Release via Lua compare-and-delete holder token.

If lock holder dies, TTL releases lock.

Do not wait indefinitely.

## 1.10 Token bucket

Use Redis Lua script with one hash/key per bucket storing token balance + last refill timestamp.

Namespace concept:

```text
wa:search:rate:v1:<provider>:<scope-hash>
```

Script atomically:

1. computes elapsed refill;
2. clamps to capacity;
3. checks requested cost=1 per upstream query attempt;
4. deducts;
5. returns allowed + retry_after_ms/current tokens;
6. sets key expiry long enough to remove inactive buckets.

Two buckets applied atomically when configured:

- provider global;
- principal/provider.

Use Redis server time inside Lua where practical to reduce replica clock skew.

## 1.11 Distributed concurrency semaphore

Use Redis sorted set per provider:

```text
wa:search:concurrency:v1:<provider>
```

Member = random lease token.
Score = lease expiry timestamp.

Atomic acquire Lua:

1. remove expired members;
2. count active;
3. if below limit, add holder token with expiry;
4. return allowed/current count.

Release Lua removes only exact token.

Provider call deadline must be shorter than lease or lease renewed.

Local `asyncio.Semaphore` additionally limits per-replica concurrency.

## 1.12 Yandex durable usage record

Add table/model concept:

```text
search_provider_calls
├── id
├── operation_id
├── principal_id / owner reference
├── provider_id
├── query_item_index
├── attempt_number
├── started_at
├── completed_at
├── outcome/status_class
├── retry_reason | null
├── billable_assumed/confirmed state
└── provider_request_id | null (safe value only)
```

Do **not** persist query text/snippet in this accounting table.

Records are primarily required for billable Yandex calls; free provider durable call logging may remain telemetry-only unless operator enables it.

Exact billing confirmation semantics follow actual Yandex provider contract and should be named conservatively (`attempted`, `response_received`, etc.), not claim a charge if API does not expose charge confirmation.

---

# 2. Patch S0 — Search contracts/models

Create:

```text
src/web_access/domain/search/
src/web_access/application/search/
```

Models:

- SearchProviderId;
- SearchLanguage;
- SearchRegionId;
- SearchSafeMode;
- SearchTimeRange;
- SearchQuery;
- SearchBatchRequest/Result;
- SearchResultItem;
- pagination/cache/provider usage metadata;
- provider capabilities/descriptor.

Ports:

- SearchProvider;
- SearchCache;
- ProviderRateLimiter;
- ProviderConcurrencyLimiter;
- SearchUsageRepository (billable accounting).

Tests pure models/batch/provider selection.

---

# 3. Patch S1 — configuration/region registry

Extend Settings:

```text
SearchSettings
SearchProviderSettings
SearXNGSettings
YandexSearchSettings
SearchCacheSettings
SearchRateLimitSettings
SearchConcurrencySettings
SearchRegionSettings
```

Implement SearchRegionRegistry exact mapping.

Tests:

- duplicate/malformed region IDs;
- mapping unknown provider;
- exact resolution;
- missing mapping rejection;
- config revision/hash deterministic without secrets.

---

# 4. Patch S2 — SearchApplicationService with fakes

Implement execution pipeline against fake ports:

```text
validate query/provider/options
→ cache lookup
→ single-flight abstraction
→ limiter/capacity
→ provider call
→ normalize provider result
→ usage hook
→ cache
→ per-item result
```

The service should delegate single-flight/rate/capacity mechanics through ports/services rather than embed Redis calls.

Tests:

- default/explicit provider;
- no fallback;
- unsupported option;
- empty result success;
- provider ordering;
- batch order/partial failures;
- cache hit skips provider;
- provider timeout isolation;
- cancellation.

---

# 5. Patch S3 — Redis cache/single-flight

Implement JSON SearchCache + single-flight lease.

Tests real Redis:

- cache roundtrip;
- principal isolation;
- shared mode;
- TTL/freshness;
- corrupted payload;
- revision invalidation;
- concurrent identical miss synthetic test;
- lease owner-only release;
- Redis restart.

---

# 6. Patch S4 — Redis token bucket/concurrency

Implement tested Lua scripts as packaged resources/source constants with explicit version.

Tests real Redis and concurrent async clients representing multiple API replicas.

Required adversarial cases:

- boundary refill;
- burst cap;
- global + principal buckets;
- Redis failure fail-closed;
- semaphore acquire/release;
- crashed holder TTL;
- wrong-holder release;
- cancellation;
- lease expiry safety.

Do not add generic distributed-lock framework beyond what Search needs.

---

# 7. Patch S5 — SearXNG provider

Add HTTPX provider client.

Use controlled test SearXNG/HTTP fixture.

Parser must tolerate documented optional fields but reject malformed required structure.

Normalize:

- title;
- URL;
- content/snippet;
- published date only if parseable/reliable;
- rank from provider order;
- provider provenance.

Capture provider warnings/errors if API exposes them, but do not leak arbitrary engine exception text as trusted hint.

---

# 8. Patch S6 — SearXNG Compose

Add version-pinned SearXNG service/config.

Requirements:

- JSON output enabled;
- `general` category configured;
- private network only;
- no host port by default;
- limiter/settings explicit;
- version/config files committed or generated reproducibly;
- health readiness.

Do not depend on public SearXNG instances.

---

# 9. Patch S7 — Yandex provider + accounting migration

Implement direct official v2 adapter.

Before coding provider serializer:

1. inspect current official Yandex Search API v2 docs;
2. inspect previous working Yandex Search service/code if accessible;
3. encode exact locked request/response fixtures in tests.

Add Alembic migration for `search_provider_calls`.

Tests:

- request serialization fixture;
- authentication header/config redaction;
- page mapping;
- region mapping;
- safe search/search type mapping;
- current response decode/parser;
- 4xx/429/5xx;
- timeout/retry;
- accounting states;
- no query text stored.

No live network in default CI.

---

# 10. Patch S8 — Search observability/health

Add component metrics/spans/logs:

- query/provider calls;
- cache hit/miss;
- rate/capacity rejects;
- provider latency;
- retry;
- result count;
- Yandex attempts;
- provider readiness/degraded state.

No raw query metric labels/log by default.

Extend `/health/status` with Search/provider status.

---

# 11. Patch S9 — REST Search

Implement:

```text
POST /api/v1/search
GET  /api/v1/search/providers
```

REST Search request may use list of per-item objects so each query can have its own options.

Unknown fields forbidden.

Actual OpenAPI tests.

Provider list returns common capabilities + configured canonical regions, not credentials/raw Yandex IDs.

---

# 12. Patch S10 — MCP `web_search`

Register exactly one Search MCP tool.

Input schema exactly uses §1.3 hard limits.

Descriptions Russian and recursively complete.

Provider enum:

```text
default
searxng
yandex
```

Result bounded structured JSON.

Tool description explicitly distinguishes Search from future `web_fetch`.

Actual FastMCP client schema tests:

- catalog contains `web_search`;
- no `search_many`;
- constraints/defaults/descriptions;
- annotation read-only/idempotent/open-world as appropriate;
- hidden Context absent.

---

# 13. Patch S11 — E2E/fault/race

Full local topology:

```text
API/MCP
PostgreSQL
Redis
SearXNG
```

Scenarios:

- MCP search default SearXNG;
- REST batch different providers/options;
- SearXNG outage;
- Yandex disabled;
- Redis cache failure;
- Redis limiter failure fail-closed;
- duplicate identical queries/single-flight;
- concurrent replicas against provider cap;
- provider timeout;
- cache freshness;
- billable call accounting synthetic provider.

Default live Yandex calls = 0.

---

# 14. Final acceptance

Run required gates from v0.2 README.

Record release evidence including:

- SearXNG version/config revision;
- Yandex adapter API contract date/revision/fixtures;
- Redis script revisions;
- test counts;
- actual OpenAPI/MCP schema checks;
- billable live calls = 0;
- provider/cache/rate race suite results.

After acceptance v0.3 Retrieval & Content Core may start.
