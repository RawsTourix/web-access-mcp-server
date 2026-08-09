# v0.3 — Retrieval & Content Core implementation sequence

## Статус

`ready for implementation`

Mandatory patch order after accepted v0.1–v0.2.

Canonical decisions:

```text
ADR-0006 aiohttp + validating resolver for arbitrary URL Retrieval
ADR-0007 Content staging/finalization/reconciliation
ADR-0008 initial L1 parser stack/isolation
ADR-0024 resource-aware retry/idempotency
```

Exact facades:

- `../../contracts/rest-api-v1.md` Retrieval/Content;
- `../../contracts/mcp-tools.md` (`web_fetch`, `content_get`, `content_parse`).

---

# R0 — Preconditions

- v0.1/v0.2 accepted;
- ContentStore filesystem foundation green;
- PostgreSQL/UoW/Alembic green;
- security controlled DNS/HTTP fixtures prepared;
- no Browser/L2 parser dependency introduced;
- current application-contract retry semantics tests green.

**Gate:** baseline before new migrations/network/parser libraries.

---

# R1 — Retrieval/Content domain/application contracts

Create/refine:

```text
domain/retrieval
domain/content
application/retrieval
application/content
```

Models:

```text
RetrievedResource metadata
ContentObject/ContentRef
Content lifecycle
ContentRepresentation/Relation
InspectionResult
NativeParseResult
parser capability identity
cursor/read result
```

Ports:

```text
SafeHttpFetcher
ContentRepository
ContentRelationRepository
ContentStore
ContentIdentifier/Inspector
NativeParserRegistry
IsolatedParserExecutor
```

No aiohttp/SQLAlchemy/pypdf/Trafilatura types in application.

---

# R2 — Content persistence migrations

Add at least:

```text
content_objects
content_relations
```

Baseline `content_objects` concepts:

```text
public content_id
owner_principal_id
state/revision
representation kind
media/detected format
filename metadata
size/hash
internal storage/staging keys
inspection bounded JSON
producer capability/revision/schema revision
created/updated/staged/available/expires/deleted timestamps
failure code
```

`content_relations` stores typed provenance such as `derived_from`.

Rules:

- storage keys internal only;
- same-owner relation enforced application-side;
- no hidden commit;
- state/revision CAS.

Migration tests empty DB→head + constraints/indexes + one head.

---

# R3 — Content lifecycle/repository

Implement ADR-0007 logical states:

```text
creating
available
failed
expired
deleted
```

Finalization:

```text
staging blob
→ hash/size verification
→ idempotent physical publish
→ DB available transition
```

Crash windows explicit and tested.

Repositories return application models, not ORM.

---

# R4 — Content reconciliation/GC foundation

Implement bounded reconciler for:

- stale `creating`;
- orphan staging files;
- final blob without available metadata where state proves safe cleanup/recovery;
- expired/deleted logical resources;
- ref-aware physical deletion.

Multiple reconcilers safe/idempotent.

Fault-injection matrix for every boundary.

---

# R5 — Safe URL/security model

Implement strict URL parser/policy before network client:

- only HTTP(S);
- hostname/port normalization;
- no embedded credential leakage;
- private/loopback/link-local/reserved/metadata/internal address deny;
- IDN/IP literal handling;
- allowed ports policy;
- redirect target revalidation;
- bounded redirect count.

Unit/property tests IPv4/IPv6/encoded/edge forms.

---

# R6 — `aiohttp` validating resolver/client

Implement ADR-0006.

Need custom validating resolver/connect path so the IP actually connected to is from validated resolution, avoiding separate validate-then-reresolve gap.

Requirements:

- TLS verification;
- no caller proxy override;
- controlled resolver caching/TTL;
- each redirect revalidated;
- absolute operation deadline;
- cancellation;
- safe peer/connection diagnostics for security tests.

Controlled DNS rebinding fixtures mandatory.

---

# R7 — Streaming/decompression limits

Request baseline:

```text
Accept-Encoding: identity
```

If upstream still sends supported compression, decode explicitly under limits.

Track separately:

```text
wire_bytes
entity_bytes
compression ratio
```

Implement hard:

- wire byte ceiling;
- entity/decompressed byte ceiling;
- expansion/ratio policy;
- bounded read chunks;
- operation deadline;
- unsupported encoding rejection.

Parser never receives unbounded body.

Tests compression bombs, truncation, slow stream, cancellation.

---

# R8 — Retrieval application pipeline

Pipeline:

```text
validate
→ fetch stream
→ stage raw Content
→ finalize raw ContentObject
→ optional L0/L1 via Content service
→ per-item result
```

Processing level:

```text
store_only
inspect
native
```

No Browser or semantic quality fallback.

Batch preserves input order/partial outcomes.

---

# R9 — Content identification/L0 inspection

Implement bounded identification registry using:

```text
declared Content-Type
+ filename/URL hint
+ magic/container/content evidence
```

Initial types:

```text
html/text
json
xml
csv
pdf
unknown/binary
```

Do not dispatch solely by suffix.

MIME mismatch becomes objective warning/diagnostic.

---

# R10 — Text/JSON/XML/CSV L1

Implement direct bounded parsers:

- text safe decoding;
- JSON stdlib;
- XML through `defusedxml`/hardened path;
- CSV bounded rows/columns/cells/total output.

Parser registry dispatches by identified format/capability.

No monolithic extension `if` chain.

---

# R11 — HTML L1

ADR-0008:

```text
Trafilatura → main readable content
lxml       → structural metadata/links/headings/JSON-LD support
```

Bound input/output/links/metadata.

Malformed HTML handled safely.

JS shell/native text absence:

```text
objective diagnostics
+ optional browser_may_be_required hint
```

No auto-Browser.

---

# R12 — Isolated parser subprocess

Before PDF parser, implement generic bounded isolated executor:

```text
parent
→ bounded structured request
→ parser child
→ bounded result
```

Requirements:

- no shell/pickle;
- no network;
- minimal env;
- no DB/Redis/provider/auth secrets;
- input/output/time limits;
- terminate/kill/reap;
- structured crash/timeout result;
- temp cleanup;
- concurrency limiter.

Production Linux is hard isolation acceptance target; dev platform may use equivalent reduced process controls where documented.

---

# R13 — PDF native text parser

Use `pypdf` inside isolated executor.

Support:

- metadata/page count;
- native text layer/page text;
- page/content-stream/resource ceilings;
- encrypted/protected diagnostics.

No OCR.

Image-only/no-text PDF returns native-text-unavailable diagnostic/hint, not failure requiring hidden L2.

Test text/scanned/encrypted/malformed/pathological/timeout/crash fixtures.

---

# R14 — Representation identity/reuse

Canonical compatible derived identity:

```text
source content
+ parser capability/revision/profile
+ representation kind
```

Race-safe behavior:

- find/reuse compatible existing representation;
- otherwise one logical winner finalizes;
- concurrent/replayed callers converge;
- no arbitrary duplicate logical derived resources.

This proof is required before trusted `content_parse` idempotent classification (ADR-0024).

---

# R15 — Content read/cursor

Owner-authorized metadata/read.

Text:

- UTF-8 bounded character chunk;
- opaque resource/version-bound cursor;
- next cursor/null.

Binary:

- metadata/representations;
- no fake text.

REST bytes stream separately; MCP never giant base64.

---

# R16 — Retry/resource semantics

Implement ADR-0024 explicitly.

## `web_fetch`

Possible acquisition/Content creation + lost result:

```text
no blind new call
```

Internal retry only at evidence-proven safe phase in same Operation.

Do not classify by HTTP GET alone.

## `content_get`

Pure owner-authorized read can be safe retry.

## `content_parse`

Idempotent trusted class only after R14 replay/concurrency proof.

Add phase-aware response-loss tests.

---

# R17 — REST facade

Implement Retrieval/Content from `contracts/rest-api-v1.md`:

- fetch;
- Content metadata/data/representations;
- inspect;
- native parse.

Requirements:

- auth/owner;
- exact processing-level schema;
- streaming Content;
- no arbitrary HTTP proxy;
- no parser library selector;
- normalized errors/hints;
- actual OpenAPI tests.

---

# R18 — MCP facade

Implement exactly:

```text
web_fetch
content_get
content_parse
```

from `contracts/mcp-tools.md`.

Do not implement Job variants before v0.6.

Requirements:

- Russian descriptions;
- exact bounds/results;
- no `*_many`;
- ContentRefs/cursors;
- no Browser/L2;
- actual FastMCP schema tests;
- own-agent retry metadata ADR-0024.

---

# R19 — Trusted hints

Generate only from trusted application diagnostics.

At least:

```text
browser_may_be_required
advanced_processing_may_be_required
native_processing_unsupported
```

Web/document content cannot create trusted hint.

No hint auto-executes next capability.

---

# R20 — Security/fault/race suite

Controlled tests:

- SSRF private/metadata IPv4/IPv6;
- DNS rebinding;
- redirect to forbidden target;
- TLS failure;
- timeout/cancellation;
- wire/entity/decompression bombs;
- malformed parsers;
- isolated parser timeout/crash;
- Content staging/finalize crash windows;
- two reconcilers;
- representation duplicate race;
- owner isolation;
- cursor misuse;
- response loss after fetch/resource creation no blind duplicate;
- no Browser/OCR fallback.

---

# R21 — Load/soak

Measure:

- concurrent Retrieval under limits;
- bounded streaming memory;
- parser child capacity/reaping;
- filesystem ContentStore concurrency;
- orphan temp/process count over long run;
- representation reuse under repeated parse;
- cursor/read throughput.

Do not optimize away isolation/lifecycle for benchmark.

---

# R22 — Acceptance closure

Record:

- aiohttp/resolver versions;
- parser library revisions;
- migration head;
- security/fault/race counts;
- no live Browser/L2 calls;
- exact OpenAPI;
- actual FastMCP schemas;
- `web_fetch` conservative retry descriptor;
- `content_parse` replay/concurrency proof before idempotent descriptor;
- reconciler evidence.

v0.3 accepted only when README DoD + applicable gates green.

---

# Forbidden shortcuts

Do not:

- validate DNS then let unrelated resolver reconnect by hostname;
- trust redirect without revalidation;
- stream/decompress unlimited;
- run riskier PDF parsing unbounded in API process;
- use suffix alone as format authority;
- auto-Browser empty HTML;
- auto-OCR scan PDF;
- expose ContentStore paths/keys;
- classify `web_fetch` safe solely because HTTP GET;
- mark `content_parse` idempotent without canonical reuse proof;
- add durable Job tools before v0.6;
- put parser library names in MCP arguments.
