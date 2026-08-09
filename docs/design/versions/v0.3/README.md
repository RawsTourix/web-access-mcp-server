# v0.3 — Retrieval & Content Core

## Статус

`ready for implementation`

Версия создаёт законченный direct web-reading flow без Browser и без L2 processing.

Подробный порядок: `implementation-sequence.md`.

---

# 1. Цель

После v0.3 известный URL проходит:

```text
safe HTTP(S) Retrieval
→ raw ContentObject
→ L0 Identification/Inspection
→ registered L1 Native Parsing when directly available
→ derived ContentObjects/provenance
→ bounded REST/MCP access
```

Если L1 невозможно/неподдерживаемо:

```text
raw ContentObject + diagnostics/hints
```

без автоматического Browser/OCR/LibreOffice/VLM fallback.

---

# 2. Canonical design / ADR

- `../../retrieval.md`;
- `../../content.md`;
- `../../resource-model.md`;
- `../../persistence.md`;
- `../../security.md`;
- `../../rest-api.md`;
- `../../mcp.md`;
- ADR-0006 safe Retrieval client/DNS;
- ADR-0007 Content staging/finalization;
- ADR-0008 initial Native Parser stack.

---

# 3. Non-goals

- Browser fallback;
- OCR/VLM;
- LibreOffice conversion;
- exhaustive file format support;
- arbitrary HTTP methods/cookies/session proxy;
- generic downloader to client-selected host path;
- crawl;
- durable Jobs (v0.6);
- S3 ContentStore (v0.5).

---

# 4. Retrieval responsibility

Retrieval answers:

> Что безопасно получил Web Access по известному HTTP(S)-URL?

It owns:

- URL validation;
- DNS/IP validation;
- SSRF/egress policy;
- TLS;
- redirects;
- streaming GET;
- wire/entity size limits;
- decompression limits;
- deadlines/cancellation;
- response metadata;
- handoff bytes to Content.

It does **not** decide whether page quality is sufficient or Browser should be used.

---

# 5. Safe HTTP client

ADR-0006 baseline for arbitrary user-controlled URL:

```text
aiohttp
+
custom validating resolver/connection policy
```

Reason: destination IP actually used for connection must belong to validated public DNS set; separate `getaddrinfo` followed by unrelated client re-resolution is insufficient against DNS rebinding/TOCTOU.

Configured trusted provider clients may continue using HTTPX.

---

# 6. URL policy

Baseline:

- schemes: `http`, `https` only;
- no URL userinfo;
- normalize/validate hostname/port;
- default website ports 80/443;
- private/loopback/link-local/multicast/reserved/special/internal CIDRs denied;
- cloud metadata denied;
- DNS A/AAAA full set validated;
- mixed public/private result fails closed;
- every redirect target revalidated from scratch;
- no environment proxy (`trust_env=False`) for arbitrary Retrieval baseline.

Operator allowlist/egress changes require explicit security design.

---

# 7. TLS

HTTPS:

- certificate verification enabled;
- hostname validation uses original hostname;
- SNI/Host preserve original authority even if connection is pinned to validated address;
- no user-controlled CA/client cert;
- no silent downgrade on TLS failure.

---

# 8. Redirects

Manual/explicit redirect handling.

Initial:

```text
default max redirects = 10
hard ceiling = 20
```

Each hop records bounded provenance and is revalidated through same URL/DNS security policy.

Redirect loop/limit is structured error.

---

# 9. Batch Retrieval

Application/REST naturally batch-first.

MCP direct `web_fetch` baseline:

```text
urls: 1..8
URL length <= 4096 chars
```

Application/REST initial hard batch:

```text
<= 32 URLs
URL length <= 8192 chars
```

Input order preserved; per-item result/error; one bad URL does not erase successful independent items.

---

# 10. Timeouts/deadlines

Initial defaults:

```text
connect timeout = 10 s
read inactivity = 15 s
item deadline = 45 s
operation deadline = 60 s
```

Hard ceilings:

```text
connect <= 30 s
read <= 60 s
item <= 120 s
operation <= 180 s
```

Application deadline propagates downward and can only shorten child phases.

No hidden indefinite retries.

---

# 11. Concurrency

Initial per Control Plane replica:

```text
global Retrieval concurrency = 32
per-host concurrency = 6
```

Bounded semaphores/admission; saturation returns controlled capacity result rather than unbounded tasks.

Future v0.7 policy can set lower effective principal limits.

---

# 12. Wire/decompressed bytes

Initial per response defaults:

```text
wire bytes <= 64 MiB
decoded/entity bytes <= 64 MiB
```

Initial direct batch aggregate decoded budget:

```text
128 MiB
```

Hard ceilings:

```text
wire <= 256 MiB/entity response
decoded <= 256 MiB/entity response
batch decoded <= 512 MiB
```

Limits enforced while streaming, not after full RAM buffer.

---

# 13. Content encoding

Request baseline asks:

```text
Accept-Encoding: identity
```

If upstream still returns supported content encoding (`gzip`, `deflate`, optional `br` if dependency present), Web Access decodes streaming itself under separate wire/decoded limits.

Unsupported encoding returns explicit error/raw diagnostic; no unbounded implicit client decompression.

Canonical raw ContentObject represents decoded HTTP entity bytes; Retrieval provenance records wire encoding/bytes.

---

# 14. Content creation lifecycle

ADR-0007:

```text
ContentObject(state=creating)
→ stage bytes
→ compute/persist SHA-256 + size/staging handle
→ idempotent physical finalize to content-addressed key
→ DB CAS available
```

Crash windows handled by Content reconciler.

No DB row says `available` before durable payload exists.

---

# 15. Filesystem ContentStore v0.3

Uses v0.1 storage port matured to production-quality local profile.

Final key content-addressed by SHA-256; logical ContentObject ownership remains separate.

Atomic rename/replace where filesystem semantics permit.

No client filename/path controls storage location.

---

# 16. ContentObject model

Durable metadata includes conceptually:

```text
content_id
owner_principal_id
state/revision
kind/representation
media type / detected format
size_bytes
sha256
storage handle internal
source/provenance
parser/representation revision where derived
created/available/expiry timestamps
```

Payload immutable after `available`.

New representation = new ContentObject linked to source.

---

# 17. Content L0 Identification/Inspection

L0 is cheap/deterministic and may identify:

- declared media type;
- detected format/signature;
- byte size/hash;
- charset where appropriate;
- document/page/image metadata only where safely/cheaply available;
- container/basic properties.

Extension is hint, not authority.

No semantic interpretation/OCR.

---

# 18. Initial L1 registry

ADR-0008 initial parser set:

```text
HTML
plain text
JSON
XML
CSV/tabular text
PDF native text
```

Registry descriptor records:

```text
parser_id
parser_revision
format capability
execution profile
supported representation
limits profile
```

MCP does not expose parser library IDs as required choice.

---

# 19. HTML

Use complementary roles:

```text
Trafilatura → main readable content
lxml/hardened structural parsing → metadata/links/JSON-LD/headings/forms as designed
```

No JavaScript execution.

If HTML is only JS shell:

- static/native result can be empty/sparse;
- report objective diagnostics;
- structured hint may recommend Browser;
- do not auto-launch Browser.

---

# 20. Text/JSON/XML/CSV

- text: bounded charset detection/normalization to UTF-8 representation;
- JSON: standard parser under input/output bounds;
- XML: hardened parser (`defusedxml`/safe lxml profile), no external entity/network expansion;
- CSV/tabular text: bounded rows/columns/output, explicit dialect handling without arbitrary code.

---

# 21. PDF native text

`pypdf` direct text-layer extraction only.

Runs in isolated short-lived parser subprocess due untrusted complex input/resource amplification.

If PDF pages contain no native text layer:

```text
native text unavailable
→ raw PDF remains available
→ diagnostic/hint advanced processing may be required
```

No OCR.

Encrypted/password PDF unsupported baseline unless direct metadata safely available; no password argument in MCP v0.3.

---

# 22. Isolated parser executor

For riskier parser profiles:

- fresh/spawn process;
- no shell;
- no DB/Redis/provider/auth secrets;
- bounded private input;
- versioned JSON protocol, no pickle;
- hard wall timeout;
- terminate/kill/reap;
- output size limit;
- temp cleanup/reaper;
- parser crash cannot crash Control Plane.

v0.5 extends same executor to more formats.

---

# 23. Derived representation/provenance

Example:

```text
raw PDF cnt_A
→ native text cnt_B
```

Derived object records:

```text
source_content_id
representation/schema revision
parser_id/revision
parameters/profile revision
created_at
warnings/diagnostics
```

Compatible existing representation can be reused by same owner/application policy.

---

# 24. Content read/cursor

Large textual Content read is bounded/chunked.

MCP `content_get` accepts batch items with opaque cursor and common `max_chars` bound.

Cursor is server-generated/versioned/opaque.

Chunk boundaries preserve valid UTF-8/text representation semantics.

Binary raw object without readable representation does not pretend to be text.

---

# 25. `content_parse`

Direct request-bound L1 parsing existing ContentObjects.

Freeze baseline later v0.8:

```text
content_ids: 1..8
```

No parser library ID; server registry chooses canonical direct parser.

No L2/Job. Durable variant added later as separate `content_parse_job` per ADR-0021.

---

# 26. `web_fetch`

Direct MCP tool is intentionally simple:

```text
urls[]
```

plus only stable useful retrieval options if design requires them.

Semantics:

```text
safe HTTP
→ raw ContentObject
→ L0
→ request-bound default L1 when registered/applicable
```

No `mode=auto|browser`, no Browser fallback, no `web_fetch_many`.

---

# 27. Hints

Trusted service-generated examples:

```text
browser_may_be_required
advanced_processing_may_be_required
alternative_representation_available
```

Hints use objective diagnostics/capability state and do not execute next step.

Recommendation to Browser can be precise because Browser is same-service capability (once v0.4 exists); v0.3 can expose generic capability code forward-compatibly.

---

# 28. Failure model

Normalize:

```text
invalid_url
ssrf/egress denied
dns resolution denied/failed
redirect denied/loop/limit
tls failure
timeout
body_limit/decompression_limit
unsupported_content_encoding
storage failure
content integrity failure
format unsupported
native_parse_failed
native_text_unavailable
parser_timeout/resource_limit
```

Per-item outcome preserved.

---

# 29. Security

Mandatory:

- SSRF/DNS-rebinding fixture tests;
- redirect revalidation;
- IPv4/IPv6 private/link-local/metadata deny;
- no env proxy trust;
- streaming limits;
- decompression bombs;
- XML attacks;
- parser process isolation;
- path/storage traversal prevention;
- Content owner isolation;
- web content untrusted in agent context.

---

# 30. Observability

Measure:

- Retrieval latency/wire/decoded bytes/outcomes;
- redirect/DNS/security denies;
- per-host/global saturation;
- Content create/finalize/reconcile;
- parser type/revision/outcome/time/kill;
- Content bytes/representation counts.

No full URLs/content as high-cardinality metric labels.

---

# 31. REST

REST adds powerful typed operations for:

- batch Retrieval;
- Content metadata/data streaming;
- L0/L1 existing Content parse;
- representations/provenance.

REST can expose more stable options than MCP but not raw HTTP proxy/library internals.

---

# 32. Required tests

- URL/SSRF/DNS/redirect matrix;
- TLS;
- slow stream/deadline/cancel;
- wire/decompressed limits;
- batch order/partial;
- Content crash windows/reconciliation;
- filesystem store contract;
- HTML/text/JSON/XML/CSV fixtures;
- PDF native text/no-text/malformed/timeout;
- isolated process kill/reap;
- owner isolation;
- cursor/chunk;
- actual REST OpenAPI;
- actual FastMCP `web_fetch/content_get/content_parse` schemas;
- no Browser/L2 fallback.

---

# 33. Definition of Done

v0.3 complete only if:

1. Arbitrary URL Retrieval is SSRF/DNS-rebinding safe by design/test.
2. Streaming/decompression/deadlines are bounded.
3. Raw Content becomes durable only through staged/finalized lifecycle.
4. Reconciliation covers crash windows.
5. L0/L1 model is explicit and L2 remains outside service.
6. PDF/native parser failures cannot crash Control Plane.
7. Large data uses ContentRef/cursor rather than giant result.
8. REST/MCP reuse one application backend.
9. `web_fetch` remains direct HTTP operation with no hidden Browser/Job.
10. Applicable Retrieval/Content/security release gates are green.
