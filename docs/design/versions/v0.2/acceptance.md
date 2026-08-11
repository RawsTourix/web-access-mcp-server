# v0.2 Search Runtime — implementation candidate evidence

## Status

`implemented, pending acceptance`

This is coding-agent handoff evidence, not self-acceptance. An independent reviewer decides whether the version becomes `accepted`. v0.3 Retrieval & Content Core has not started and is allowed only after factual acceptance of v0.2.

## Candidate identity

- Implementation HEAD: `<S16-candidate-commit>`.
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
S16 <S16-candidate-commit> acceptance closure/version/docs
```

## Provider and protocol revisions

- SearXNG image: `searxng/searxng:2026.7.28-c01178d03` at digest `sha256:5d6d903ab82afa56ee32792d477f36bc63d3e5ca04fcb6947e28a5cfd987fad3`.
- SearXNG configuration revision: `searxng-2026.7.28-c01178d03-v1`; private Compose service, JSON enabled, no default host port.
- Yandex official API verification: 2026-08-11; synchronous Search API v2 `POST /v2/web/search`, `Api-Key`, REST CamelCase request, base64 XML response. Detailed record: `../../../verification/yandex-search-api-2026-08-11.md`.
- Sanitized deterministic Yandex fixtures: `web_search_request.json`, `web_search_response.json`, `web_search_response.xml`. Default live Yandex calls: **0**.
- Redis cache schema revision: `1`; single-flight release script revision: `1`; token-bucket revision: `1`; concurrency acquire/release revisions: `1`.

## Public contract evidence

OpenAPI exposes exactly the two v0.2 Search routes in addition to operational routes:

```text
POST /api/v1/search
GET  /api/v1/search/providers
```

The actual generated Search request schema has `additionalProperties=false`, `queries` 1..32, query length 1..4096, limit 1..50, provider enum `default|searxng|yandex`, omission-only optional fields, and bearer security. Provider discovery contains only public identity, enabled/billable flags, five capability booleans, and readiness.

Actual FastMCP client discovery returns exactly:

```text
["web_search"]
```

Its discovered schema has `additionalProperties=false`, queries 1..8 with item length 1..2048, limit 1..20, exact provider/safe-search/time-range enums and defaults, no credential/context/raw provider fields, and annotations `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=true`. The separate trusted descriptor is `phase_evidence_required`, has possible billable cost, and forbids blind replay after possible dispatch.

REST and MCP construct the same trusted principal and `ExecutionContext`, then call the same `SearchApplicationService`; only the documented transport limits differ.

## Test and operational evidence

Final local gate:

```text
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q
```

Result: `270 passed`; skips `0`; xfail `0`; xpass `0`; flaky-marked tests `0`.

Infrastructure and race evidence:

- PostgreSQL and Redis integration run against real containers.
- Token-bucket last-token race: 10 deterministic repetitions, 30 contenders, exactly 5 admissions each.
- Multi-replica provider cap: five seeds, two application instances, 20 clients per seed; observed active calls never exceeded global limit 3; excess work received structured capacity failures.
- Identical requests across two application instances produced one upstream call, one cache fill, one cached waiter result, preserved retrieval timestamp, and input order.
- SearXNG pinned JSON probe succeeded with 30 results in the final S15 topology run.

Compose fault/restart evidence:

```text
REST mixed Search + cache smoke        passed
MCP default Search                     passed
controlled Yandex v2 protocol          passed
PostgreSQL outage/recovery              passed
Redis restart/recovery, twice           passed
SearXNG outage/no-fallback/recovery      passed
graceful API shutdown/restart            passed
```

The full controlled fault run completed in 112.9 seconds without an API restart during dependency recovery. PostgreSQL outage left free SearXNG usable and rejected Yandex before the controlled provider counter changed. The controlled Yandex service exists only in the E2E Compose override; ordinary CI requires no Yandex secret and performs zero live Yandex calls.

Billable response-loss call counts:

```text
possible dispatch + lost response       upstream calls 1, evidence rows 1, automatic retries 0
concurrent identical paid single-flight upstream calls 1, evidence rows 1, hidden retries 0
explicit second caller operation        upstream calls 2, operation IDs 2, attempt rows 2
cache hit                               upstream calls 0, new billable rows 0, rate units 0
live Yandex                             0
```

## Gate mapping

- G0/G28/G29/G31: this status and evidence handoff, with independent acceptance retained.
- G1/G2/G24/G25/G30: architecture tests, Ruff, formatting, Pyright, deterministic non-skipped tests.
- G3/G4/G14/G15: actual OpenAPI/FastMCP contracts and common `search:read` identity.
- G5: repeatable empty/previous-head migration and durable attempt transition/constraint tests.
- G6/G23: secret/privacy tests, hashed keys, content-free accounting, pinned SearXNG image/config.
- G7/G27: deterministic provider selection, no fallback, paid response-loss evidence and conservative retry descriptor.
- G13: bounded telemetry and independent provider readiness.
- G17/G18/G20: Redis races, multi-instance caps/backpressure, dependency restart/outage recovery.
- G26: controlled SearXNG and sanitized Yandex fixture profile; live paid profile count zero.

G8–G12 and v0.3+ subsystems are intentionally outside this implementation candidate.
