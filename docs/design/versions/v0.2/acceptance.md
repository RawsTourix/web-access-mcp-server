# v0.2 Search Runtime — implementation and acceptance evidence

## Status

`accepted`

The coding-agent handoff evidence below has completed independent review. v0.3 Retrieval & Content Core was not part of this acceptance and had not started at the accepted HEAD.

## Independent acceptance

v0.2 Search Runtime independently accepted.

Acceptance repository HEAD:

```text
a6af55ba5e6b2781af580f335342e356a8fbe747
```

Final production correction:

```text
c91f12925f4c3673ccc93a8b137824c5b913e33b
```

Independent review confirmed the applicable v0.2 architecture, contract, security, migration, Search, retry/cost, race/fault, recovery, and scope gates recorded in this document.

No unresolved v0.2 acceptance blocker remains.

v0.3 Retrieval & Content Core was not part of this acceptance and had not started at the accepted HEAD.

## Candidate identity

- Final factual acceptance correction: `c91f12925f4c3673ccc93a8b137824c5b913e33b`.
- Corrected implementation commit: `07476fb73a90bbf67698bb054d270df587d31ec6`.
- Original implementation candidate: `3c10cde78f8be8b01519d3b577bdee770e893982`.
- S0 characterization base: `7a190d5be4e34b001a5e6e6555c032062f0235c3`.
- Package/service version: `0.2.0`; Python support: `>=3.11,<3.13`; exercised with Python 3.11.
- Alembic head: `0002_search_attempts` over accepted `0001_foundation`.

Logical commit chain:

```text
S1  f0525d2 search contracts
S2  182a4ef language/region
S3  9857836 exact limits
S4  4a3f503 application service
S5  76be995 cache/single-flight
S6  2c2f308 rate/concurrency
S7  52f426b SearXNG adapter
S8  99ebf83 SearXNG deployment
S9  8b1cbb7 billable attempt persistence
S10 642f66b Yandex adapter
S11 38b1db2 observability/readiness
S12 951d40f REST
S13 8ab56b5 MCP
S14 c49e50f response-loss/cost
S15 8278668 E2E/race/fault
S16 3c10cde acceptance closure/version/docs
S17 07476fb acceptance correction: bounded runtime, fail-closed admission, contracts, deterministic E2E
S18 c91f129 final acceptance correction: replica-safe flow control, provider bounds, cache/UTC
```

## Provider and protocol revisions

- SearXNG image: `searxng/searxng:2026.7.28-c01178d03` at digest `sha256:5d6d903ab82afa56ee32792d477f36bc63d3e5ca04fcb6947e28a5cfd987fad3`.
- SearXNG configuration revision: `searxng-2026.7.28-c01178d03-v1`; private Compose service, JSON enabled, no default host port.
- Yandex official API verification: 2026-08-11; synchronous Search API v2 `POST /v2/web/search`, `Api-Key`, REST CamelCase request, base64 XML response. Detailed record: `../../../verification/yandex-search-api-2026-08-11.md`.
- Sanitized deterministic Yandex fixtures: `web_search_request.json`, `web_search_response.json`, `web_search_response.xml`. Default live Yandex calls: **0**.
- Redis cache schema revision: `1`; single-flight release script revision: `1`; token-bucket revision: `3`; concurrency acquire/release revisions: `3`/`1`; shared flow-generation revision: `2`.

## Public contract evidence

OpenAPI exposes exactly the two v0.2 Search routes in addition to operational routes:

```text
POST /api/v1/search
GET  /api/v1/search/providers
```

The actual generated Search request schema has `additionalProperties=false`, `queries` 1..32, query length 1..4096, limit 1..50, provider enum `default|searxng|yandex`, omission-only optional fields, and bearer security. Provider discovery uses the common public operation envelope and contains only public identity, enabled/billable flags, five capability booleans, and readiness.

Actual FastMCP client discovery returns exactly:

```text
["web_search"]
```

Its discovered schema has `additionalProperties=false`, queries 1..8 with item length 1..2048, limit 1..20, exact provider/safe-search/time-range enums and defaults, no credential/context/raw provider fields, and annotations `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=true`. The separate trusted descriptor is `phase_evidence_required`, has possible billable cost, and forbids blind replay after possible dispatch.

REST and MCP construct the same trusted principal and `ExecutionContext`, then call the same `SearchApplicationService`; only the documented transport limits differ.

## S17 correction evidence

- `SearchLanguage` is dependency-free domain data. BCP 47 validation and normalization with pinned `langcodes` occurs at the application boundary, and an AST architecture test rejects every undeclared third-party domain import.
- REST and MCP create an absolute Search deadline; the application adds the same bounded deadline for non-transport callers. Batch-slot waits, provider calls, retry sleeps, cache/single-flight work, concurrency waits, and billable accounting share that budget.
- Owned provider tasks are cancelled and awaited before concurrency release on direct task cancellation. Cooperative cancellation or deadline expiry after possible paid dispatch returns `unknown_outcome`, records durable unknown evidence, and performs no hidden retry.
- Retry timing applies exponential backoff, bounded jitter, and provider `Retry-After` under the remaining absolute deadline. No new attempt starts when its delay cannot fit.
- Redis token and concurrency admission use provider-scoped generation markers in the same Lua operation as reservation/acquisition. Missing state after FLUSHDB quarantines all replicas for the conservative refill/lease horizon.
- Redis unavailability maps to `infrastructure/search_admission_unavailable`; genuine token denial maps to `rate_limited`. Fully unsuccessful REST Search returns category-derived 4xx/5xx status, while partial/success remains HTTP 200.
- Provider discovery uses `PublicOperationResult`; authenticated MCP principals without `search:read` receive a structured `permission/insufficient_scope` rejection.
- SearXNG and Yandex adapters expose Russian agent-facing messages, reject unsafe provider-region values, bound URLs and response bodies, and isolate malformed result items while preserving valid siblings.

## Final acceptance correction evidence

- Rate and concurrency now use one provider-scoped Redis generation marker. Missing marker or a changed Redis `run_id` starts the configured maximum refill/lease horizon inside the same Lua transaction as admission. There is no process-local bootstrap exemption and no generation/admission TOCTOU window.
- A read-only flow-control readiness probe reads that same marker and quarantine. Provider discovery reports `unavailable` while Search admission is fail-closed, then returns to `ready` after the horizon without API restart and without consuming a token, creating a lease, or calling a provider.
- Fresh limiter replicas after FLUSHDB and after Redis restart cannot reopen token or concurrency capacity. Ten repeated old/new-replica bootstrap races admitted zero contenders during quarantine.
- Yandex HTTP `400`, `401`, and `403` are server-owned upstream rejections (`provider_request_rejected` / `provider_auth_rejected`) and therefore REST returns `502`, never client authentication `401` or validation `422` after dispatch.
- Official deterministic Yandex constraints are enforced before rate/concurrency/accounting/provider dispatch: query length 400, query word count 40, flat result window 250, folder ID length 50, region length 100 and configured positive decimal region IDs. Invalid requests produce zero rate admissions, concurrency acquisitions, attempt rows, and upstream calls.
- Cache finalization is best-effort after terminal provider success and completed mandatory billable accounting. False returns, Redis exceptions, cache deadline expiry, and cooperative cancellation add `cache_write_failed` without changing the successful Search outcome or starting a second provider call.
- Public Search result timestamps reject naive values and normalize aware values to UTC. SearXNG `2026-08-11T15:00:00+03:00` projects as `2026-08-11T12:00:00Z`.

## Test and operational evidence

Final local gate:

```text
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q
```

Result after the final correction: `300 passed in 59.81s`; skips `0`; xfail `0`; xpass `0`; flaky-marked tests `0`.

Suite breakdown/evidence:

```text
unit + contract + architecture + security   238 passed
integration + migration + Redis races        61 passed
package smoke                                 1 passed
full pytest                                 300 passed
shutdown timing repetition                   10/10 passed
```

Infrastructure and race evidence:

- PostgreSQL and Redis integration run against real containers.
- Token-bucket last-token race: 10 deterministic repetitions, 30 contenders, exactly 5 admissions each.
- Multi-replica provider cap: five seeds, two application instances, 20 clients per seed; observed active calls never exceeded global limit 3; excess work received structured capacity failures.
- Identical requests across two application instances produced one upstream call, one cache fill, one cached waiter result, preserved retrieval timestamp, and input order.
- Redis FLUSHDB tests prove that old and newly constructed replicas fail closed for the conservative maximum token/refill or lease horizon and recover without an API restart.
- The Redis flow-control subset completed `12 passed in 3.07s`; the full integration/migration suite completed `61 passed in 10.81s`.
- The pinned SearXNG container is checked only for health and static JSON configuration. Search behavior is exercised against a deterministic local SearXNG-compatible service; public Search calls are zero.

Compose fault/restart evidence:

```text
REST mixed Search + cache smoke        passed
MCP default Search                     passed
controlled Yandex v2 protocol          passed
PostgreSQL outage/recovery              passed
Redis restart/recovery, twice           passed
Redis FLUSHDB fail-closed/recovery       passed
Redis restart + new API replica          passed
provider readiness during quarantine     passed
SearXNG outage/no-fallback/recovery      passed
graceful API shutdown/restart            passed
non-root runtime UID 10001                passed
migration upgrade repeatability (twice)  passed
```

The final isolated controlled fault run completed in 125 seconds. PostgreSQL outage left free Search usable and rejected Yandex before the controlled provider counter changed. Redis transport failures are reported as infrastructure unavailability rather than rate exhaustion. A fresh API process started immediately after a real Redis restart remained fail-closed until the shared horizon elapsed. Provider discovery reported `unavailable` during restart/FLUSH quarantine and automatically returned to `ready`. The controlled Yandex and SearXNG-compatible services exist only in the E2E Compose override; ordinary CI requires no Yandex secret, performs zero live Yandex calls, and makes no public Search requests.

Billable response-loss call counts:

```text
possible dispatch + lost response       upstream calls 1, evidence rows 1, automatic retries 0
concurrent identical paid single-flight upstream calls 1, evidence rows 1, hidden retries 0
explicit second caller operation        upstream calls 2, operation IDs 2, attempt rows 2
cache hit                               upstream calls 0, new billable rows 0, rate units 0
live Yandex                             0
controlled local Yandex                 1
public external Search                  0
```

## Gate mapping

- G0/G28/G29/G31: this status and evidence handoff, with independent acceptance retained.
- G1/G2/G24/G25/G30: architecture tests, Ruff, formatting, Pyright, deterministic non-skipped tests.
- G3/G4/G14/G15: actual OpenAPI/FastMCP contracts, operation-enveloped provider discovery, structured MCP scope rejection, and common `search:read` identity.
- G5: repeatable empty/previous-head migration and durable attempt transition/constraint tests.
- G6/G23: secret/privacy tests, hashed keys, content-free accounting, pinned SearXNG image/config.
- G7/G27: deterministic provider selection, no fallback, paid response-loss evidence and conservative retry descriptor.
- G13: bounded telemetry and independent provider readiness.
- G17/G18/G20: Redis races, multi-instance caps/backpressure, FLUSHDB generation horizons, and dependency restart/outage recovery.
- G26: deterministic local SearXNG-compatible Search, pinned SearXNG health/static verification, and sanitized Yandex fixture profile; public Search and live paid profile counts are zero.

G8–G12 and v0.3+ subsystems are intentionally outside this implementation candidate.
