# v0.2 — Search Runtime implementation sequence

## Статус

`ready for implementation`

Mandatory patch order for Search after accepted v0.1.

Current relevant decisions:

```text
ADR-0003 language/region
ADR-0004 direct Yandex provider
ADR-0005 cache/rate/capacity split
ADR-0024 cost/resource-aware retry
```

Exact facade targets:

- Search section `../../contracts/rest-api-v1.md`;
- `web_search` in `../../contracts/mcp-tools.md`.

---

# S0 — Preconditions

- v0.1 accepted;
- Postgres/Redis/FastAPI/FastMCP/auth/operation contracts green;
- no Search code already hidden in transport;
- controlled SearXNG fixture/profile prepared;
- Yandex default CI live calls = 0;
- provider secrets test-redacted.

**Gate:** baseline green before Search dependencies/migrations.

---

# S1 — Search domain/application contracts

Create `domain/search` + `application/search`.

Models:

```text
SearchProviderId
SearchLanguage
SearchRegionId
SearchSafeMode
SearchTimeRange
SearchQuery
SearchBatchRequest/Result
SearchResultItem
ProviderCapabilities/Descriptor
cache/pagination/usage metadata
```

Ports:

```text
SearchProvider
SearchCache / single-flight abstraction
ProviderRateLimiter
ProviderConcurrencyLimiter
SearchUsageRepository
```

No provider library types in application.

Tests batch/order/default/explicit provider/no fallback/empty success.

---

# S2 — Language/region configuration

Use pinned `langcodes` or verified equivalent only for tag parse/normalization.

No query language detection.

Canonical region ID pattern:

```regex
^[a-z0-9][a-z0-9-]{0,63}$
```

Typed configured provider mappings.

Tests invalid/duplicate/missing provider mapping and deterministic config revision without secrets.

---

# S3 — Search exact limits

MCP target:

```text
queries 1..8
query 1..2048
page 1..100 default1
limit 1..20 default10
provider default|searxng|yandex
optional language/region/safe_search/time_range
```

REST/application bounded wider baseline:

```text
queries <=32
query <=4096
results/query <=50
page <=100
```

Operator policy may be stricter, never silently wider than hard schema/software ceiling.

---

# S4 — SearchApplicationService with fakes

Pipeline:

```text
validate/resolve provider
→ cache lookup
→ single-flight coordination
→ rate/capacity admission
→ provider call
→ normalize
→ usage evidence hook
→ cache
→ per-item result
```

No Redis/HTTPX directly in application service.

Tests:

- unsupported option;
- provider disabled;
- batch partial;
- cancellation/deadline;
- cache hit skips provider;
- no hidden fallback;
- provider timeout isolation.

---

# S5 — Redis Search cache/single-flight

Use deterministic versioned JSON, no pickle.

Principal-scoped default cache key hash.

Initial operational TTL direction 300s/provider, configurable.

Single-flight uses holder token + TTL + owner-only release; wait bounded by operation deadline.

Tests:

- cache roundtrip/freshness;
- principal isolation/shared mode;
- corrupted payload;
- concurrent identical miss;
- holder death;
- Redis restart.

---

# S6 — Redis rate/concurrency

Implement independent mechanisms:

## Token bucket

Provider-global + principal/provider where configured.

Atomic Redis script with bounded retry-after.

## Concurrency lease

Provider sorted-set/token lease + local semaphore.

Tests multi-replica:

- boundary refill/burst;
- wrong-owner release;
- crashed holder TTL;
- Redis failure behavior;
- cancellation;
- concurrent cap enforcement.

Do not build generic distributed-lock framework unless required by another accepted design.

---

# S7 — SearXNG adapter

Configured private/self-hosted SearXNG.

HTTP mapping baseline:

```text
/search
q
format=json
categories=general
language
pageno
safesearch 0|1|2
time_range
```

Validate provider response model and normalize rank/title/url/snippet/date where reliable.

No raw engine/provider exception trusted as hint.

Controlled integration tests; no public-instance dependency.

---

# S8 — SearXNG deployment profile

Add pinned/reproducible SearXNG Compose/config:

- JSON enabled;
- general category;
- private network;
- no host exposure default;
- explicit health/readiness;
- version/config recorded.

---

# S9 — Billable provider attempt persistence

Before Yandex live adapter, add migration/repository for safe attempt evidence such as:

```text
operation_id
principal_id
provider_id
query_item_index
attempt_number
started/completed
execution/send evidence
outcome/status class
retry reason
provider request ID if safe
```

Do not store raw query/snippet in accounting table.

This is v0.2 evidence foundation; v0.7 adds full budgets/reservations.

---

# S10 — Yandex provider adapter

Before implementation:

1. verify current official API against locked date/version;
2. compare user's previous working Yandex Search code where useful;
3. commit exact request/response non-secret fixtures.

Use direct official configured adapter, not hidden SearXNG engine.

Tests:

- auth/config redaction;
- page/region/safe mapping;
- response parse;
- 4xx/429/5xx;
- timeout;
- send-stage evidence;
- no raw provider DTO in public model.

### Retry rule

Provider internal retry allowed only when execution-stage evidence proves no ambiguous billable send/effect according ADR-0024.

Do **not** implement generic `timeout → retry paid call`.

After possible send/unknown response, return normalized conservative failure/evidence; Agent-level descriptor must not blind replay.

---

# S11 — Search observability/readiness

Add bounded metrics/traces/logging:

- provider call latency/outcome;
- cache hit/miss;
- rate/concurrency rejection;
- results count aggregate;
- provider readiness;
- billable attempt/send/result evidence;
- internal safe retry counts/reasons.

No raw query metric labels/log by default.

---

# S12 — REST Search

Implement exact:

```text
POST /api/v1/search
GET  /api/v1/search/providers
```

from `contracts/rest-api-v1.md`.

REST supports per-query typed options.

OpenAPI tests exact security/limits/descriptions/no credentials/raw Yandex region data leakage.

---

# S13 — MCP `web_search`

Register exactly one Search tool from `contracts/mcp-tools.md`.

Requirements:

- Russian description;
- provider description warns `yandex` may be billable;
- actual schema exact limits/defaults;
- no `search_many`;
- no page fetching;
- MCP annotations according exact contract;
- own-agent trusted retry class **conservative after possible provider dispatch**, even if readOnlyHint/idempotentHint are true.

Actual MCP client schema tests.

---

# S14 — Response-loss/cost tests

Synthetic billable provider must prove:

```text
pre-dispatch failure
→ may retry if policy allows

possible dispatch + response loss
→ no second automatic provider/Agent call
→ one conservative usage attempt evidence
```

Test cache hit consumes zero provider attempt.

Test explicit caller second call remains a new operation and may consume new unit.

---

# S15 — E2E/race/fault

Topology:

```text
API/MCP
PostgreSQL
Redis
SearXNG
mocked/controlled Yandex adapter
```

Scenarios:

- MCP default SearXNG;
- REST mixed per-item provider/options;
- SearXNG outage;
- Yandex disabled;
- Redis cache/limiter restart/failure;
- duplicate identical query/single-flight;
- concurrent replicas provider cap;
- provider timeout;
- cache freshness;
- billable response-loss no duplicate;
- no hidden fallback.

Default real Yandex calls = 0.

---

# S16 — Acceptance closure

Record:

- SearXNG version/config;
- Yandex API contract date/fixtures;
- Redis scripts/version;
- migration head;
- test counts;
- actual OpenAPI/FastMCP schemas;
- billable response-loss evidence;
- live paid calls count = 0 unless explicit separately approved test;
- race/fault results.

v0.2 accepted only when README DoD + applicable gates green.

---

# Forbidden shortcuts

Do not:

- use public random SearXNG as production dependency;
- hide Yandex inside SearXNG only;
- auto-switch provider on result count;
- store provider secret/query in accounting/log labels;
- merge rate and concurrency into one mechanism;
- assume readOnly Search is blind-retry-safe when billable;
- treat response loss after possible Yandex send as pre-dispatch failure;
- add page-fetching to Search;
- expose raw provider DTO/options to MCP.
