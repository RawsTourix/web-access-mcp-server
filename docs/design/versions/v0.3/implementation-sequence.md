# v0.3 — Retrieval & Content Core implementation sequence

## Статус

`ready for implementation`

Этот документ закрывает implementation choices v0.3. Codex/ChatGPT не должен самостоятельно заменять security/parser/storage решения без обновления design/ADR.

---

# 1. Зафиксированные implementation choices

## 1.1 Retrieval HTTP stack

По ADR-0006:

```text
arbitrary HTTP(S) Retrieval
→ aiohttp ClientSession
→ TCPConnector(custom validating resolver)
→ manual redirects
→ trust_env=False
```

Configured Search providers продолжают использовать HTTPX.

Добавить runtime dependency:

```text
aiohttp
```

## 1.2 URL/batch hard limits

### MCP `web_fetch`

```text
urls: 1..8
URL length: max 4096 characters
```

### REST/application safety ceiling

```text
max_batch_urls = 32
max_url_chars = 8192
```

Operator policy может быть строже, но не шире hard safety ceiling без contract/version change.

## 1.3 Redirect limits

Default/configured:

```text
max_redirects = 10
```

Application hard ceiling:

```text
20
```

Redirect chain хранится bounded metadata.

## 1.4 Retrieval time budgets

Initial defaults:

```text
connect_timeout = 10s
read_inactivity_timeout = 15s
per_item_total_timeout = 45s
request_bound_operation_timeout = 60s
```

Hard safety ceilings configurable code constants/settings validation:

```text
connect <= 30s
read inactivity <= 60s
per item <= 120s
request-bound operation <= 180s
```

ExecutionContext deadline всегда может быть короче.

MCP не получает timeout fields.

## 1.5 Retrieval concurrency defaults

Per API replica defaults:

```text
global in-flight Retrieval items = 32
per-host in-flight = 6
```

Batch scheduler уважает меньший из:

- batch size;
- global capacity;
- per-host capacity;
- remaining deadline.

Точные production defaults позже могут меняться по benchmark как configuration, не API contract.

## 1.6 Response byte limits

Initial defaults:

```text
max_wire_bytes_per_item = 64 MiB
max_decoded_bytes_per_item = 64 MiB
max_batch_decoded_bytes = 128 MiB
```

Hard server ceilings:

```text
max_wire_bytes_per_item <= 256 MiB
max_decoded_bytes_per_item <= 256 MiB
max_batch_decoded_bytes <= 512 MiB
```

Limits централизованы в RetrievalSettings, не разбросаны magic numbers.

`Content-Length` используется только для early rejection; streaming limit остаётся authoritative.

## 1.7 Content-Encoding

Request отправляет:

```text
Accept-Encoding: identity
```

чтобы предпочитать несжатый entity payload и упростить accounting/security.

ClientSession:

```text
auto_decompress = False
```

Если upstream всё равно вернул `Content-Encoding`, v0.3 поддерживает вручную bounded streaming decode:

```text
identity
gzip
deflate
br
```

Dependencies:

```text
brotli
```

Не рекламировать `br`, если implementation не готова его safely decode; `identity` остаётся request preference.

Unsupported Content-Encoding:

```text
item failed: unsupported_content_encoding
```

без передачи compressed bytes parser-у как будто это исходный файл.

## 1.8 Wire vs Content payload

Raw `ContentObject` представляет **decoded HTTP entity body после Content-Encoding**, а не exact wire-compressed bytes.

Retrieval metadata отдельно фиксирует:

```text
wire_bytes
entity_bytes
content_encoding
```

Почему:

- `Content-Type` относится к decoded entity;
- parsers должны получать actual PDF/HTML bytes;
- повторное parsing не должно зависеть от transport compression.

Web Access не является packet/archive capture service.

## 1.9 Streaming decompression

Decoder получает chunks и одновременно считает:

```text
wire_bytes
entity_bytes
```

Hard decoded limit проверяется после каждого output chunk.

Не выполнять `gzip.decompress(full_bytes)` после загрузки всего payload.

`deflate` implementation должна корректно обрабатывать supported zlib/raw-deflate variants через bounded state machine без бесконечного retry parser chain.

## 1.10 Request profile

Canonical v0.3 headers:

```text
User-Agent: configured Web Access UA
Accept: */*
Accept-Encoding: identity
```

`Accept-Language` не входит v0.3 MCP. REST также не получает arbitrary headers.

User-Agent configuration default должен идентифицировать сервис честно, без browser impersonation/stealth semantics.

## 1.11 SafeResolver

Реализовать `aiohttp.abc.AbstractResolver` adapter.

Resolver:

1. получает hostname/port/family;
2. normalizes hostname/IDNA;
3. использует async/system `getaddrinfo` equivalent;
4. deduplicates returned addresses;
5. validates **каждый** address через central EgressAddressPolicy;
6. mixed public/forbidden result → reject whole resolution;
7. возвращает только validated records connector-у;
8. no independent re-resolve перед connect.

Baseline connector:

```text
use_dns_cache=False
limit=<global>
limit_per_host=<per-host>
```

Connection reuse остаётся доступным.

## 1.12 Allowed ports

Default:

```text
80
443
```

Operator может добавить numeric ports через allowlist settings.

Client не может расширить ports per request.

## 1.13 Format identification

Добавить pure-Python signature detector:

```text
puremagic
```

но использовать его только как **один из signals**.

Canonical identification pipeline:

```text
source filename suffix
+ declared HTTP Content-Type
+ puremagic signature hint
+ format-specific lightweight validators/sniffers
→ ContentInspection.detected_format
```

При конфликте signals:

- format-specific strong signature/validator имеет приоритет;
- mismatch сохраняется warning/diagnostic;
- extension никогда не является единственным доказательством.

Initial custom sniffers/validators обязательны для:

```text
PDF (%PDF signature)
HTML/HTM
JSON
XML
plain text
CSV candidate
```

`puremagic` помогает broadly identify unsupported images/archives/Office/media for L0 metadata/hints, но Web Access не обещает L1 для всех распознанных formats.

## 1.14 Content SQL schema

### `content_objects`

Поля baseline:

```text
id                  BIGINT identity PK
content_id           VARCHAR(64) UNIQUE NOT NULL
owner_principal_id   VARCHAR(128) NOT NULL
state                VARCHAR/enum NOT NULL
revision             BIGINT NOT NULL default 1
representation_kind  VARCHAR(32) NOT NULL
media_type           VARCHAR(255) NULL
detected_format      VARCHAR(64) NULL
source_filename      VARCHAR(512) NULL
size_bytes           BIGINT NULL
sha256               CHAR(64) NULL
storage_key          TEXT NULL
staging_key          TEXT NULL
inspection           JSONB NOT NULL default '{}'
producer_id           VARCHAR(128) NULL
producer_revision     VARCHAR(64) NULL
schema_revision       VARCHAR(64) NULL
created_at            timestamptz NOT NULL
updated_at            timestamptz NOT NULL
staged_at             timestamptz NULL
available_at          timestamptz NULL
expires_at            timestamptz NULL
deleted_at            timestamptz NULL
failure_code          VARCHAR(128) NULL
```

Indexes:

```text
unique(content_id)
(owner_principal_id, state, expires_at)
(state, updated_at)                 -- reconciler
(storage_key)                       -- physical ref/GC
(sha256) where sha256 is not null   -- diagnostics/dedup lookup
```

`storage_key`/`staging_key` internal only.

### `content_relations`

```text
id                  BIGINT identity PK
owner_principal_id   VARCHAR(128) NOT NULL
source_content_id    FK content_objects(id)
target_content_id    FK content_objects(id)
relation_type        VARCHAR(64) NOT NULL
metadata             JSONB NOT NULL default '{}'
created_at            timestamptz NOT NULL
```

Unique:

```text
(source_content_id, target_content_id, relation_type)
```

Baseline relation:

```text
derived_from
```

Application validates same-owner relation in v0.3.

## 1.15 Content lifecycle

v0.3 durable states:

```text
creating
available
failed
expired
deleted
```

`creating` may have internal phase metadata (`staged_at`, `staging_key`).

No public read of `creating`.

## 1.16 Content retention defaults

Initial policy:

```text
transient fetched/raw/derived content TTL = 24 hours
creating timeout = 10 minutes
orphan staging cleanup grace = 30 minutes
unreferenced final blob GC grace = 60 minutes
reconciler interval = 60 seconds
```

All configurable.

Reading ContentObject does **not** automatically extend TTL.

Future explicit save/retention class may extend lifetime through explicit application operation; v0.3 does not add it.

## 1.17 Content read cursor

Use stateless opaque base64url JSON cursor:

```json
{"v":1,"content_id":"cnt_...","offset":12345}
```

- UTF-8 JSON;
- base64url no padding;
- parser rejects unknown version/negative/oversized offset/content mismatch;
- cursor is not authorization; owner checked separately;
- no signing required for correctness because fields are validated and immutable content prevents race.

Offset = **byte offset** in stored ContentObject.

## 1.18 Text chunk semantics

Agent-readable derived text/Markdown representations are canonical UTF-8.

`content_get` reads from byte cursor, over-reads bounded bytes as needed, and returns only complete UTF-8 code points.

MCP schema:

```text
items: 1..8
  content_id
  cursor | null
max_chars: 1..30000, default 12000
```

`max_chars` common for batch.

Server may read more bytes than chars requested only within a small bounded UTF-8 decoding window.

`next_cursor` uses exact byte offset after returned text.

If specified ContentObject is binary/non-textual:

- metadata + available derived refs returned;
- no fake text conversion;
- hint can recommend `content_parse` when L1 parser exists.

## 1.19 Plain text canonicalization

If raw plain-text payload is valid UTF-8 and no normalization is needed, raw ContentObject may be directly readable.

If source encoding differs, Native Parsing creates UTF-8 `text/plain` derived ContentObject.

This keeps MCP chunking stable without rewriting raw bytes.

## 1.20 Initial parser input defaults

Central `ParserPolicySettings`, not per-module magic constants.

Defaults:

### HTML / text / JSON / XML / CSV

```text
max input = 16 MiB
max derived output = 16 MiB
parser wall deadline = 10s
```

### PDF

```text
max input = 64 MiB
max pages = 500
max derived text output = 16 MiB
hard wall timeout = 20s
Linux child address-space limit target = 512 MiB
Linux CPU time limit target = 15s
```

Server hard ceilings can be higher but bounded; operator defaults configurable.

These are resource protection defaults, not quality heuristics.

## 1.21 Structured format limits

Initial defaults:

```text
JSON max nesting depth = 128
XML max nesting depth = 128
CSV max rows = 100000
CSV max columns = 1000
CSV max cell chars = 1 MiB
HTML structural links/elements retained = bounded configurable count
```

If representation exceeds output limit, parser returns controlled limit error/partial metadata according parser contract; no silent giant output.

## 1.22 Isolated parser subprocess protocol

Per ADR-0008.

Parent creates private temp directory:

```text
<parser_tmp_root>/<operation_id>/<random>/
```

Files:

```text
input.bin
request.json
result.json
output-*.bin/text
```

Child invoked with only:

```text
--request <absolute internal temp path>
```

Request JSON includes:

```text
protocol_version = 1
parser_id
parser_revision
input_path
output_dir
limits
```

Child output `result.json` written atomic temp→rename within private dir.

No pickle/stdin arbitrary code.

Parent validates every returned output path is under exact output_dir and size limits before ingest.

## 1.23 Child process spawning

Use `asyncio.create_subprocess_exec` with:

```text
sys.executable -m web_access.workers.parser_once --request ...
```

fresh process per isolated parse.

Child environment built from minimal allowlist:

- PATH/Python runtime necessities;
- locale/temp as needed;
- **exclude** DB/Redis/Yandex/Auth bearer secrets.

Linux resource limits applied child-side before parser import/execution.

## 1.24 Child timeout/kill

Parent:

1. `wait_for(process.wait(), timeout)`;
2. timeout → terminate;
3. bounded grace e.g. 2s;
4. still alive → kill;
5. await exit;
6. cleanup temp.

Parser timeout cannot leave background child consuming resources.

## 1.25 Parser result statuses

Internal typed statuses:

```text
parsed
no_native_representation
unsupported
encrypted
malformed
limit_exceeded
timeout
crashed
failed
```

`no_native_representation` for image-only PDF is not equivalent to crash.

## 1.26 HTML Browser hint objective signal

Baseline `browser_may_be_required` emitted only when all are true:

1. detected format = HTML;
2. structural parse succeeds;
3. normalized visible/body textual content is empty or effectively absent after removing script/style/template/noscript-only text;
4. document contains executable/module script references or known app-root-like empty structural shell;
5. no parser error explains absence.

Do **not** use generic threshold like `<500 chars`.

Implementation returns diagnostic fields supporting why hint was generated.

## 1.27 L2 hint

`advanced_processing_may_be_required` can be emitted on strong format/parser state:

- valid PDF page structure with no native text;
- image format has no L1 textual parser;
- unsupported legacy document where L0 identified format but no native parser.

Message stays generic; it does not hardcode LiteParse/LibreOffice unless such external integration later becomes a configured capability.

---

# 2. Patch R0 — Retrieval/Content models and DB migration

Create domain/application packages.

Implement SQLAlchemy models/migration exactly around §1.14.

Add repositories:

```text
ContentRepository
ContentRelationRepository
```

No hidden commits.

Tests:

- owner queries;
- revision CAS;
- state constraints;
- relation uniqueness/same-owner application check;
- migration empty/current→head.

---

# 3. Patch R1 — Content staging/finalization application

Implement ADR-0007 against existing filesystem ContentStore.

Application service:

```text
reserve
stage
persist staged metadata
finalize
publish available
```

Add Content reconciler functions, but no separate Job system.

Reconciler can run bounded periodic loop owned by Control Plane foundation.

Fault injection every ADR-0007 crash window.

---

# 4. Patch R2 — Content identification/L0

Dependencies:

```text
puremagic
charset-normalizer
```

Implement ContentFormatRegistry + inspection pipeline.

Do not trust puremagic blindly; use custom validators.

Fixtures include:

- PDF with misleading `.txt`;
- HTML served application/octet-stream;
- PNG served text/plain;
- OOXML ZIP recognized broadly as container/format when possible;
- arbitrary binary unsupported.

Inspection schema contract tests.

---

# 5. Patch R3 — Safe URL policy/resolver

Implement ADR-0006:

- URL parser;
- allowed scheme/port;
- no userinfo;
- EgressAddressPolicy;
- custom aiohttp resolver;
- `trust_env=False`;
- DNS tests;
- private/special IPv4/IPv6 corpus.

Before actual external fetch integration, tests must prove no uncontrolled second resolve with a custom resolver fixture.

---

# 6. Patch R4 — streaming SafeHttpFetcher

Implement:

- aiohttp pooled session lifecycle;
- manual redirects;
- `Accept-Encoding: identity`;
- auto_decompress false;
- identity/gzip/deflate/br streaming decode;
- wire/entity byte limits;
- timeouts/deadlines/cancellation;
- response metadata;
- controlled 4xx/5xx body handling.

Use controlled local HTTP server.

Tests:

- all redirects;
- TLS fixture where practical;
- compression bomb;
- misleading Content-Length;
- chunked response;
- slow stream;
- connection reset;
- proxy env malicious but ignored.

---

# 7. Patch R5 — RetrievalApplicationService batch

Implement batch scheduler with bounded concurrency/per-host limits.

Flow each item:

```text
SafeHttpFetcher
→ ContentApplication ingest(native)
→ Retrieval item result
```

At this patch Content native parsers may still be fake/stub except L0; tests verify no Browser/Job call.

Batch total byte budget shared safely across concurrent items through atomic/async counter policy.

---

# 8. Patch R6 — inline Native Parsers

Dependencies:

```text
trafilatura
lxml
defusedxml
```

stdlib json/csv.

Implement parser registry:

- html-main-trafilatura;
- html-struct-lxml;
- text-native;
- json-native;
- xml-native;
- csv-native.

All parser outputs typed/application-defined.

HTML produces canonical UTF-8 Markdown derived object when main content exists.

Plain text non-UTF8 produces UTF-8 text derived.

JSON/XML/CSV derived object only when output size/usefulness warrants contract; inspection/summary always bounded.

No external fetch from parsers.

---

# 9. Patch R7 — isolated PDF parser

Dependency:

```text
pypdf
```

Implement:

- `IsolatedProcessParserExecutor`;
- `workers/parser_once.py` entrypoint;
- minimal environment;
- temp protocol v1;
- Linux rlimits;
- hard timeout/terminate/kill;
- result schema validation;
- PDF parser.

Fixtures:

- text PDF;
- multi-page;
- image-only;
- encrypted;
- malformed;
- huge/complex synthetic;
- hanging synthetic parser test adapter for timeout/kill.

Do not add OCR library.

---

# 10. Patch R8 — Content read/cursor

Implement `ContentApplicationService.get/read`.

Cursor v1 from §1.17.

Text rules:

- UTF-8 derived representations;
- bounded chars;
- exact byte next cursor;
- binary content returns metadata/derived refs, no base64 giant result.

REST streaming raw/data can bypass text cursor and use ContentStore stream.

Tests multibyte UTF-8 boundaries, invalid cursor, content mismatch, expired/deleted content, cross-owner access.

---

# 11. Patch R9 — retention/reconciliation

Implement periodic bounded maintenance loop(s) for:

- stale creating;
- orphan staging;
- available missing blob detection;
- expired logical content;
- unreferenced final blob GC after grace;
- parser temp leftovers.

Multi-replica safe via PostgreSQL claim/locking for logical resources; physical cleanup always rechecks refs/state.

No Job subsystem dependency.

Tests fake Clock + real DB/store race cases.

---

# 12. Patch R10 — REST Retrieval/Content

Implement common routes from `rest-api.md`:

```text
POST /api/v1/retrieval/fetch
GET  /api/v1/content/{content_id}
GET  /api/v1/content/{content_id}/data
POST /api/v1/content/native-parse
```

Optional batch inspect endpoint only if needed by implementation tests/client use; do not add redundant API for symmetry.

REST fetch can expose processing level:

```text
store_only | inspect | native
```

default `native` for normal use.

Content data streamed, not giant JSON.

Actual OpenAPI tests.

---

# 13. Patch R11 — MCP `web_fetch`

Register:

```text
web_fetch(urls: list[HttpUrl])
```

Schema:

- 1..8 URLs;
- max length 4096;
- no other inputs baseline.

Description Russian and explicitly says:

- ordinary HTTP(S) retrieval;
- direct L0/L1 processing;
- no JavaScript/browser;
- no OCR/advanced processing;
- use Browser tools later when hint indicates/agent decides.

Result per URL bounded.

Preferred inline preview max:

```text
12000 characters
```

Large text returns ContentRef + total length.

---

# 14. Patch R12 — MCP `content_get`

Schema:

```text
items: 1..8
  content_id: opaque ID
  cursor: optional opaque string
max_chars: int 1..30000 = 12000
```

No representation selector.

Specified `content_id` **is** the chosen representation.

Result item:

- metadata;
- text chunk if readable;
- next_cursor;
- available derived ContentRefs;
- warnings/hints.

---

# 15. Patch R13 — MCP `content_parse`

Schema:

```text
content_ids: 1..8
```

No parser ID/options baseline.

Canonical registry chooses L1.

If:

- already compatible derived exists → reuse;
- parser unavailable → structured outcome/hint;
- isolated parser required → run request-bound isolated process if within limits;
- parser execution profile future `job_required` → `processing_requires_job`, but v0.3 does not create Job.

---

# 16. Patch R14 — observability/health

Add Retrieval/Content telemetry:

- target host safe form;
- bytes wire/entity;
- redirects;
- SSRF rejection;
- parser ID/revision/outcome;
- subprocess timeout/crash;
- Content staging/finalization/reconciliation;
- active Retrieval concurrency.

Detailed status:

- Retrieval client ready;
- ContentStore;
- parser registry/revisions;
- maintenance backlog.

No raw URL/query/page text metric labels.

---

# 17. Patch R15 — E2E/security/race/fault

Full flows:

1. HTTP HTML → Markdown.
2. Search result URL manually passed → web_fetch.
3. JS shell → browser hint, Browser calls = 0.
4. PDF text → derived text.
5. scanned PDF → raw + L2 hint, OCR calls/deps = 0.
6. 404 body preserved non-success.
7. redirect public→private blocked.
8. gzip/deflate/br limits.
9. Content crash windows.
10. concurrent identical bytes/owners.
11. parser child killed on timeout.
12. content_get cursors.
13. cross-owner denial.
14. Redis/PostgreSQL/API restart does not corrupt available Content.

Randomized/race loops for Content finalize/cleanup.

---

# 18. Docker/CI updates

Application image adds:

- aiohttp;
- brotli;
- puremagic;
- charset-normalizer;
- Trafilatura/lxml/defusedxml;
- pypdf.

No Playwright/LibreOffice/OCR.

Linux image must support subprocess rlimits and parser temp root.

CI controlled HTTP service can be Python fixture/ASGI/HTTP server within integration job.

---

# 19. Release evidence v0.3

Record:

- aiohttp/puremagic/parser versions;
- parser registry revision;
- DB migration head;
- Retrieval limit profile;
- security SSRF matrix results;
- compression bomb results;
- parser subprocess timeout/kill tests;
- Content fault/race counts;
- actual OpenAPI/MCP schema tests;
- OCR/LibreOffice/Playwright calls/dependencies = 0.

After all required gates green v0.3 accepted and v0.4 Browser implementation may begin.
