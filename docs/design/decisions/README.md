# Architecture Decision Records

Каталог содержит значимые архитектурные решения Web Access MCP.

ADR используется, когда существует несколько реалистичных вариантов, а выбор влияет на contracts, runtime topology, security, consistency или последующие implementation stages.

## Статусы

- `proposed` — решение подготовлено, но ещё может быть изменено до implementation;
- `accepted` — решение принято и является частью текущего design;
- `superseded` / `superseded in part` — полностью или частично заменено более новым ADR;
- `rejected` — вариант рассмотрен и явно не принят.

## Правила

ADR должен содержать:

1. контекст;
2. требования;
3. рассмотренные варианты;
4. решение;
5. последствия/trade-offs;
6. что решение намеренно не определяет;
7. ссылки на затронутые design docs.

Если ADR меняет ранее принятый design, канонический документ-владелец темы и связанные version docs обновляются согласованным consistency patch.

## Реестр

| ADR | Решение | Статус |
|---|---|---|
| [ADR-0001](ADR-0001-browser-worker-transport.md) | Control Plane вызывает owning Browser Worker через direct internal HTTP/RPC; Redis — coordination/routing, не action bus | accepted |
| [ADR-0002](ADR-0002-authentication-principal-baseline.md) | Внешний REST/MCP использует заменяемый `AuthProvider`; baseline — configured Bearer service principals + scopes | accepted |
| [ADR-0003](ADR-0003-search-language-region-model.md) | Search language — common normalized tag; region — canonical configured `SearchRegionId` с provider mapping | accepted |
| [ADR-0004](ADR-0004-yandex-search-adapter.md) | Yandex Search — отдельный billable provider через официальный REST API и HTTPX, не hidden SearXNG engine | accepted |
| [ADR-0005](ADR-0005-search-cache-rate-capacity.md) | Search cache, distributed rate limiting и provider concurrency — три отдельные Redis-backed responsibilities | accepted |
| [ADR-0006](ADR-0006-retrieval-http-client-and-safe-dns.md) | Arbitrary URL Retrieval использует aiohttp + validating resolver; configured provider HTTP остаётся на HTTPX | accepted |
| [ADR-0007](ADR-0007-content-staging-finalization.md) | Content создаётся через durable `creating` → staged blob → explicit/idempotent finalization → `available` | accepted |
| [ADR-0008](ADR-0008-v0.3-native-parser-stack.md) | Initial L1 parser stack: Trafilatura + lxml + hardened XML + stdlib JSON/CSV/text + isolated pypdf | accepted |
| [ADR-0009](ADR-0009-browser-worker-registry-and-lease.md) | PostgreSQL authoritative BrowserSession ownership; Redis worker registry/route cache; worker self-fencing lease | accepted |
| [ADR-0010](ADR-0010-browser-snapshot-element-refs.md) | Browser snapshot — semantic/ARIA view + snapshot-scoped exact `element_ref` с identity-anchor validation | accepted |
| [ADR-0011](ADR-0011-browser-dialog-policy.md) | JavaScript dialogs используют explicit per-action policy; default — dismiss-and-report | accepted |
| [ADR-0012](ADR-0012-browser-process-per-session.md) | Отдельный Chromium process на BrowserSession; первоначальная direct worker ownership часть заменена ADR-0013 | superseded in part |
| [ADR-0013](ADR-0013-browser-session-subprocess.md) | Browser Worker — supervisor; каждая BrowserSession живёт в отдельном Python subprocess, который владеет Playwright/Chromium | accepted |
| [ADR-0014](ADR-0014-browser-egress-proxy.md) | Browser egress идёт через public-only forward proxy/gateway; Browser Worker не имеет direct Internet route | accepted |
| [ADR-0015](ADR-0015-v0.5-native-content-expansion.md) | v0.5 расширяет только direct L1 readers/inspectors: OOXML, ODF, EPUB/FB2/SVG, image/audio metadata; без LibreOffice/OCR/VLM | accepted |
| [ADR-0016](ADR-0016-s3-content-store.md) | S3-compatible ContentStore использует boto3 в bounded I/O executor и сохраняет тот же staged/finalized Content lifecycle | accepted |
| [ADR-0017](ADR-0017-job-outbox-arq-delivery.md) | Durable Jobs доставляются `PostgreSQL outbox → arq wake-up → authoritative DB claim`; Redis не является source of truth | accepted |
| [ADR-0018](ADR-0018-v0.6-durable-job-types-and-items.md) | Первые durable workloads — retrieval/content parse batches с persistent `JobItem` checkpoints; crawl/browser workflow отложены | accepted |
| [ADR-0019](ADR-0019-dynamic-policy-registry.md) | Dynamic non-secret policy хранится как revisioned PostgreSQL snapshots; replicas используют bounded-staleness immutable PolicySnapshot | accepted |
| [ADR-0020](ADR-0020-durable-quota-and-usage-accounting.md) | Durable resource quotas/billable budgets учитываются transactionally в PostgreSQL; Redis остаётся flow limiter, не accounting source | accepted |
| [ADR-0021](ADR-0021-mcp-durable-job-tool-boundary.md) | Request-bound Retrieval/Content и durable Job creation — разные MCP tools из-за разных lifecycle/retry semantics | accepted |
| [ADR-0022](ADR-0022-v0.8-mcp-tool-catalog.md) | v0.8 MCP freeze candidate: explicit 27-tool semantic catalog; one stable execution class per tool | accepted |

## Browser ADR progression

```text
ADR-0001  direct worker RPC
ADR-0009  worker registry / generation / lease
ADR-0010  snapshot / element refs
ADR-0011  dialogs
ADR-0012  отдельный Chromium per session (сохраняемый инвариант)
ADR-0013  session subprocess ownership/kill boundary
ADR-0014  browser egress boundary
```

При конфликте старой process-management формулировки ADR-0012 с ADR-0013 приоритет имеет ADR-0013.

## Content ADR progression

```text
ADR-0007  Content staging/finalization + reconciliation
ADR-0008  initial v0.3 native parser stack/isolation
ADR-0015  v0.5 direct native format expansion
ADR-0016  S3-compatible shared ContentStore
```

L2 processing остаётся вне Web Access.

## Jobs ADR progression

```text
ADR-0017  durable outbox/arq delivery + DB claim/fencing
ADR-0018  typed batch Job workloads + JobItem checkpoints
ADR-0021  explicit MCP Job-creation tool boundary
```

Queue/runtime generic внутри backend; public creation typed.

## Policy/operations ADR progression

```text
ADR-0019  revisioned dynamic non-secret policy registry
ADR-0020  durable principal quota/billable usage accounting
```

Secrets остаются deployment configuration; policy не расширяет auth scopes/hard ceilings.

## MCP stabilization

```text
ADR-0021  direct vs Job resource creation split
ADR-0022  semantic freeze candidate catalog
```

При противоречии exploratory MCP examples ранних version docs с ADR-0021/0022 приоритет имеют ADR-0021/0022 и актуальный `mcp.md`; такие хвосты должны быть удалены consistency pass до implementation соответствующей версии.
