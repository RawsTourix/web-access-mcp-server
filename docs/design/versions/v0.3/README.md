# v0.3 — Retrieval & Content Core

## Статус

`implemented, pending acceptance`

Coding-agent evidence: [`acceptance.md`](acceptance.md). Independent acceptance has not been granted.

v0.3 реализует законченный безопасный flow:

```text
known HTTP(S) URL
→ Safe Retrieval
→ raw ContentObject
→ L0 Inspection
→ available L1 Native Parsing
→ bounded REST/MCP result + ContentRefs
```

Implementation order: `implementation-sequence.md`.

---

# 1. Canonical design/contracts

- `../../retrieval.md`;
- `../../content.md`;
- `../../application-contracts.md`;
- `../../resource-model.md`;
- `../../persistence.md`;
- `../../security.md`;
- `../../rest-api.md`;
- `../../mcp.md`;
- `../../contracts/rest-api-v1.md`;
- `../../contracts/mcp-tools.md` (`web_fetch`, `content_get`, `content_parse`);
- `../../contracts/common-models.md`;
- ADR-0006 safe DNS/client;
- ADR-0007 Content staging/finalization;
- ADR-0008 initial parser stack;
- **ADR-0024 resource-aware retry**.

---

# 2. Non-goals

- Browser fallback;
- OCR/VLM/LibreOffice/L2;
- broad Office/media parser expansion (v0.5);
- durable retrieval/parse Jobs (v0.6);
- arbitrary HTTP methods/body/headers/proxy;
- raw filesystem paths/public storage keys;
- client-selected parser library;
- generic file conversion;
- hidden re-fetch on Content read.

---

# 3. Retrieval responsibility

Retrieval owns:

```text
URL parsing/security
DNS/IP validation
HTTP(S) GET acquisition
redirect validation
streaming/body/decompression limits
headers/status/final URL
raw Content creation handoff
```

Retrieval does not decide semantic page quality and does not launch Browser.

Known URL fetch is explicit.

---

# 4. Safe HTTP implementation

ADR-0006:

- arbitrary URL Retrieval uses `aiohttp` with validating resolver/connect strategy;
- configured Search providers may remain HTTPX because endpoint is trusted config;
- every DNS/connect/redirect hop revalidated against egress/SSRF policy;
- TLS verification on;
- only HTTP(S);
- private/loopback/link-local/metadata/internal destinations denied by default.

No naïve `getaddrinfo validate → separate client re-resolve` window.

---

# 5. Streaming/decompression

Baseline direction:

```text
Accept-Encoding: identity
```

If server still returns supported compression, service decodes itself under separate:

```text
wire-byte ceiling
entity/decompressed-byte ceiling
ratio/safety policy
absolute deadline
```

Parser never receives unbounded decompression bomb.

Exact limits belong implementation sequence/settings and are contract-tested where public.

---

# 6. Content resource lifecycle

ADR-0007:

```text
creating
→ staged blob
→ validate hash/size
→ idempotent physical finalization
→ DB available
```

Failure/crash windows produce recoverable states; reconciler cleans orphan staging/final blobs only according reference/state rules.

Public ContentRef never exposes storage key/path.

Physical dedup by hash does not merge logical owner/resource identity.

---

# 7. Content persistence/provenance

PostgreSQL stores Content metadata/lifecycle/provenance.

ContentStore stores large immutable payload.

Derived representation records:

```text
source ContentObject
producer capability/revision
representation kind/media type
creation metadata
```

Original raw object remains immutable/available according retention even after derived parse.

---

# 8. L0 Inspection

v0.3 supports deterministic cheap identification/inspection for initial core types.

At minimum detect/inspect:

```text
HTML/text
JSON
XML
CSV
PDF
unknown/binary
```

Identification uses:

```text
declared Content-Type
+ URL/filename hint
+ magic/container/content inspection
```

Declared MIME is not blindly trusted.

Inspection returns objective facts; no semantic quality score controlling hidden escalation.

---

# 9. Initial L1 parsers

ADR-0008 baseline:

```text
HTML → Trafilatura main-content + lxml structural metadata/links
JSON → stdlib safe parse
XML → defusedxml/hardened XML path
CSV → stdlib bounded parser
text → explicit safe decoding
PDF → pypdf text-layer parse in isolated parser subprocess
```

No OCR if PDF has no text layer.

No Browser if HTML is JS shell.

Instead return diagnostics/hints.

---

# 10. Parser isolation

Riskier parser (initially PDF) runs through bounded isolated process executor:

- no network;
- minimal env;
- hard input/output/time/memory/process constraints as platform supports;
- kill/reap on timeout/crash;
- no DB/Redis/provider credentials;
- structured protocol, no pickle.

Later v0.5 reuses/extents this model.

---

# 11. Content representation reuse

Canonical parse should avoid duplicate logical derived representations for same compatible parse identity.

Identity concept:

```text
source content
+ parser capability/revision/profile
+ representation kind
```

Concurrent/replayed parse must converge on existing compatible representation or one logical winner.

This is required before `content_parse` can be trusted as idempotent (ADR-0024).

---

# 12. `web_fetch`

Exact MCP target from `contracts/mcp-tools.md`:

```text
urls 1..8
```

For each URL:

```text
safe Retrieval
→ raw Content
→ L0
→ available request-bound L1
```

Result contains ContentRefs/inspection/representations/preview, not giant raw HTML/PDF.

No Browser, no Job.

---

# 13. `web_fetch` retry semantics

Critical ADR-0024:

```text
HTTP GET does not mutate target website
≠ tool call is safe to blindly replay
```

`web_fetch` creates Web Access resources/provenance and may consume remote/network work.

After ambiguous response loss where acquisition/Content creation may have occurred:

```text
no blind Agent/client replay
```

Implementation may retry only **inside same Operation** at provably pre-dispatch/safe transient phases.

No generic «GET therefore safe_retry» rule.

---

# 14. `content_get`

Reads existing selected ContentObject.

Exact MCP:

```text
items 1..8
max_chars 1..30000 default12000
opaque cursor
```

No re-fetch/no parse escalation/no Browser.

Pure read safe retry subject to owner/deadline/capacity.

---

# 15. `content_parse`

Request-bound L1 parse for existing ContentObjects.

Exact MCP:

```text
content_ids 1..8 unique
```

No parser library selector.

No L2.

Trusted idempotent retry class is enabled only after canonical representation reuse/concurrency tests prove it.

---

# 16. REST

Exact v1 baseline provides:

```text
POST /api/v1/retrieval/fetch
GET  /api/v1/content/{id}
GET  /api/v1/content/{id}/data
GET  /api/v1/content/{id}/representations
POST /api/v1/content/inspect
POST /api/v1/content/native-parse
```

Retrieval processing level:

```text
store_only
inspect
native
```

REST richer than MCP but still no arbitrary HTTP proxy or parser internals.

---

# 17. Structured hints

Examples:

```text
HTML shell / native text unavailable
→ browser_may_be_required

PDF no text layer
→ advanced_processing_may_be_required

unsupported L1 format
→ native_processing_unsupported
```

Hint generated from objective inspection/parser facts and does not execute Browser/L2 automatically.

---

# 18. Failure model

Normalize at least:

```text
invalid_url
scheme_not_allowed
blocked_destination
dns_resolution_failed
redirect_blocked
too_many_redirects
tls_error
upstream_timeout
response_too_large
decompression_limit
unsupported_content_encoding
content_store_error
content_not_found/content_expired
format_unsupported
native_text_unavailable
parser_timeout
parser_crash
parser_output_limit
content_quota/policy rejection when applicable
```

Raw parser/client exception not public.

---

# 19. Observability/security

Measure:

- acquisition latency/status/bytes;
- redirects/security rejects;
- decompression ratio/limits;
- Content staging/finalization/reconciler;
- parser duration/crash/kill;
- representation reuse;
- retry phase classification.

Do not log full URLs/content indiscriminately; follow redaction policy.

No untrusted content as metric label/trusted hint.

---

# 20. Required tests

- URL parser/SSRF/private IPv4/IPv6/metadata;
- DNS rebinding controlled fixture;
- redirect chain validation;
- TLS/timeout/cancellation;
- streaming wire/entity limits;
- compression bombs;
- Content staging crash matrix/reconciliation;
- hash/dedup logical owner separation;
- HTML/JSON/XML/CSV/text/PDF fixtures;
- PDF isolated parser timeout/crash/no text;
- no OCR/Browser hidden fallback;
- Content cursor/binary behavior;
- concurrent/replayed native parse canonical reuse;
- **web_fetch ambiguous response loss no blind duplicate**;
- exact REST OpenAPI;
- actual MCP schemas and retry descriptors.

---

# 21. Definition of Done

v0.3 accepted only if:

1. Arbitrary URL Retrieval closes DNS/redirect SSRF windows.
2. Content lifecycle survives crash windows/restart.
3. L0/L1 initial parsers are bounded and riskier parser isolated.
4. No Browser/L2 hidden fallback.
5. Public result uses ContentRefs/bounded preview.
6. `web_fetch` is not mislabeled blind-safe because HTTP GET.
7. `content_parse` idempotency is proven by canonical representation reuse tests before trusted classification.
8. REST/MCP reuse same application backend and exact contracts.
9. Reconciler/storage/parser fault/race/security gates green.
