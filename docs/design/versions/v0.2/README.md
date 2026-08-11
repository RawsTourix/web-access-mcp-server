# v0.2 — Search Runtime

## Статус

`accepted`

Independent acceptance completed.

Acceptance repository HEAD:

```text
a6af55ba5e6b2781af580f335342e356a8fbe747
```

Final production correction:

```text
c91f12925f4c3673ccc93a8b137824c5b913e33b
```

v0.2 реализует первую полноценную Web Access capability — Search — через общий application backend, REST и MCP.

Implementation order: `implementation-sequence.md`.

Implementation and independent acceptance evidence: `acceptance.md`.

---

# 1. Цель

После v0.2 сервис умеет:

```text
1..N independent search queries
→ deterministic provider selection
→ SearXNG or optional Yandex Search
→ normalized result batches
→ cache/rate/concurrency/accounting
→ REST Search
→ MCP web_search
```

Search не читает target pages и не выполняет hidden provider fallback.

---

# 2. Canonical design/contracts

- `../../search.md`;
- `../../application-contracts.md`;
- `../../observability.md`;
- `../../security.md`;
- `../../rest-api.md`;
- `../../mcp.md`;
- Search section `../../contracts/rest-api-v1.md`;
- `../../contracts/mcp-tools.md` (`web_search`);
- `../../contracts/common-models.md`;
- ADR-0003 language/region;
- ADR-0004 direct Yandex adapter;
- ADR-0005 cache/rate/capacity split;
- **ADR-0024 cost/resource-aware retry semantics**.

ADR-0024 is cross-version and must be implemented even though it was accepted after the initial v0.2 draft.

---

# 3. Non-goals

- reading/fetching result pages;
- Browser;
- automatic provider fallback based on result count/quality;
- provider-specific raw public API;
- search reasoning/synthesis;
- durable Search Job;
- user accounts;
- arbitrary provider installation by client.

---

# 4. Provider model

Application uses common provider abstraction.

Baseline IDs:

```text
default
searxng
yandex
```

`default` resolves configured deterministic default provider.

No hidden flow:

```text
SearXNG result seems weak
→ silently paid Yandex
```

Explicit caller/provider policy decides.

---

# 5. SearXNG

Self-hosted configured SearXNG is default free provider direction.

Adapter maps common fields:

```text
query
page
limit
language
safe_search
time_range
```

Region is unsupported unless exact adapter mapping is explicitly designed/configured.

JSON API only; provider payload validated and normalized.

No dependency on random public SearXNG instance.

---

# 6. Yandex Search

Separate optional billable provider through official configured API.

Provider credentials/folder IDs/endpoints stay infrastructure config.

Public contract exposes only stable provider ID/options.

Region uses ADR-0003 configured mapping; no geocoding/guessing inside Search.

Billable attempts produce durable usage/accounting evidence foundation.

---

# 7. Language/region

Language is normalized common language tag, not provider enum.

Region is canonical configured `SearchRegionId`.

Provider adapter validates capability/mapping and returns repairable rejection when unsupported.

No automatic language detection/query geolocation.

---

# 8. Batch semantics

MCP exact target:

```text
queries 1..8
query chars 1..2048
page 1..100 default1
limit 1..20 default10
```

REST/application may use wider bounded limits from exact REST/settings.

Input order preserved; per-query failures do not erase siblings.

No `search_many` tool.

---

# 9. Cache

Cache is separate infrastructure responsibility.

Baseline:

- versioned deterministic request serialization;
- principal-scoped default to avoid cross-principal side-channel;
- optional explicitly configured shared/disabled mode;
- provider-specific operational TTL;
- result includes cache/freshness facts;
- cache hit avoids upstream provider call/billable unit.

Redis loss does not silently fabricate cached success.

---

# 10. Rate vs concurrency

Separate concerns:

```text
rate limiter
→ attempts over time

concurrency limiter
→ simultaneous upstream calls
```

Distributed Redis-backed implementation + local per-replica bound.

Provider/principal policy can be stricter than hard software ceiling.

---

# 11. Billable accounting foundation

For Yandex-like provider record conservative attempt facts without storing raw query text in accounting table.

Need evidence fields enough to distinguish:

```text
pre-dispatch rejection
send attempted
response received
provider request ID where safe
outcome/retry reason
```

Full durable multi-principal budgets arrive v0.7, but v0.2 must not create semantics that make later correct accounting impossible.

---

# 12. Retry/cost semantics

Critical ADR-0024 invariant:

```text
Search is read-oriented toward the web
≠ blind replay is always safe
```

If explicit/default provider may be billable and request may have been dispatched:

```text
lost result
→ Agent/client must not automatically issue a second paid search solely because tool looked read-only
```

Provider implementation may retry **within the same Operation** only when execution-stage/send/billing evidence proves retry safe under provider policy.

Examples:

- failure before dispatch/auth/validation → may be retryable after correction/transient recovery;
- definite connection failure before bytes/request dispatch → provider-specific safe retry may be allowed;
- response lost after possible send/billing → no blind replay; preserve conservative evidence.

MCP annotation may remain semantically read-only/idempotent, but own-agent trusted retry class is stricter.

---

# 13. Failure model

Normalize at least:

```text
invalid_query
unsupported_language
unsupported_region
provider_disabled
provider_unavailable
provider_rate_limited
provider_timeout
provider_rejected
capacity_limited
billable_budget/policy rejection where introduced
```

Provider stack traces/raw errors do not leak.

Empty result is valid success, not automatic provider switch.

---

# 14. Hints

Allowed:

- selected URLs can be read with `web_fetch` once available;
- explicit provider unavailable/disabled can report capability facts;
- cautious query-refinement hint only from objective structured condition.

Not allowed:

```text
few results → hidden second provider
```

---

# 15. REST/MCP

REST implements exact Search facade from `contracts/rest-api-v1.md`.

MCP implements exact `web_search` from `contracts/mcp-tools.md`, including:

- Russian discovery/field descriptions;
- bounded batch;
- explicit provider enum/default;
- billable provider warning in description;
- actual FastMCP schema tests.

Both call same SearchApplicationService.

---

# 16. Observability/security

Measure bounded:

- provider latency/outcomes;
- cache hit/miss;
- rate/concurrency rejection;
- result count aggregate;
- billable attempt states;
- provider readiness.

No query text as metric label.

Credentials redacted.

No provider raw exception trusted as agent hint.

---

# 17. Required tests

- provider fake/contract normalization;
- SearXNG controlled integration;
- Yandex exact mocked/recorded non-secret fixtures;
- no live paid request default CI;
- batch order/partial;
- language/region mapping;
- cache isolation/freshness/single-flight;
- Redis rate/concurrency races/restart;
- provider outage;
- no hidden fallback;
- billable accounting phases;
- **response-loss after possible paid dispatch does not trigger blind second call**;
- REST OpenAPI exact Search schema;
- actual FastMCP `web_search` schema + own-agent retry descriptor.

---

# 18. Definition of Done

Independent review may accept v0.2 only if:

1. SearXNG free provider works through clean adapter.
2. Yandex is separate optional billable adapter.
3. Provider selection deterministic/explicit; no quality fallback.
4. Common language/region model works.
5. Cache/rate/concurrency independent and race-tested.
6. Search result preserves provider/provenance/freshness.
7. Billable attempt evidence exists and paid response-loss is not blind replayed.
8. REST/MCP reuse same application backend and match exact contracts.
9. Search does not claim target page contents were read.
10. Applicable Search/security/contract gates green.
