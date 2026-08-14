# v0.3 Retrieval & Content Core — implementation evidence

## Status

`implemented, pending acceptance`

This is coding-agent evidence for an implementation candidate. It is not an independent
acceptance record and does not grant the status `accepted`. v0.4 remains blocked until factual
independent acceptance of this candidate.

## Candidate identity

- Starting HEAD: `b46f1c28969d9d98facfbde4bf3089cf851e78b0`.
- Implementation candidate HEAD: `5bae49ee862034a9ab5746cdc49dc4225b7583ab`.
- Evidence follow-up: the commit containing this document; it changes documentation only.
- Package/service version: `0.3.0`.
- Supported Python range: `>=3.11,<3.13`.
- Exercised Python: `3.11.15` on Windows x86-64.
- Alembic head: `0003_content_core`, upgrading from accepted v0.2 head
  `0002_search_attempts`.

Logical implementation chain:

```text
R1   f73a433 Retrieval/Content contracts
R2   d03c093 durable Content schema
R3   55ff1e7 staged Content lifecycle
R4   9699395 reconciler and reference-aware GC
R5   3da0189 Retrieval URL/egress policy
R6   1289d45 validating aiohttp resolver/connect path
R7   fc02836 bounded streaming/decompression
R8   d4610f0 bounded Retrieval-to-Content orchestration
R9   646a1a4 bounded L0 inspection registry
R10  8c4708f bounded text/JSON/XML/CSV parsers
R11  a05714c bounded Trafilatura+lxml HTML parser
R12  00ca39a isolated parser subprocess
R13  d10d0f0 isolated pypdf text-layer parser
R14  e39725f canonical representation convergence/reuse
R15  721d62a authorized stateless cursor reads
R16  0bed557 phase-aware Retrieval retry semantics
     d99c0bb canonical execution-phase follow-up
R17  41aaaef exact REST Retrieval/Content facade
R18  ce4649f exact four-tool MCP facade
R19  6d319bc trusted processing diagnostics
R20  f5eb1d2 Retrieval/Content security, race, and fault matrix
R21  80584f2 load/soak/leak evidence
R22  5bae49e version 0.3.0 and implementation-candidate documentation
```

## Dependency and protocol revisions

Locked runtime versions exercised by the candidate:

```text
aiohttp            3.14.3
trafilatura         2.2.0
lxml                6.1.1
charset-normalizer  3.4.9
defusedxml          0.7.1
pypdf               6.15.0
```

Retrieval revisions:

- resolver implementation: `ValidatingResolver`, source revision
  `1289d453e4736ad7ee08c83500825fc2f0f337f9`;
- actual aiohttp connector receives the validated numeric addresses from that resolver and has
  DNS cache disabled;
- security policy: `retrieval-egress-v1`, source revision
  `3da01894212465624c4223a7c9f02aa51131a6fd`;
- HTTP(S)-only, public-address-only, redirect revalidation, TLS verification, `trust_env=False`,
  separate wire/entity/ratio limits, and absolute operation/read-inactivity deadlines.

Content revisions:

- database schema: `0003_content_core`;
- inspection schema: `content-inspection-v1`;
- lifecycle: `creating → staged → available` with revision/CAS checks and immutable SHA-256
  physical keys, source revision `55ff1e7`;
- reconciler/reference-aware physical GC: source revision
  `9699395a2dfc644c4590a567edbf1126b622ba38`;
- stateless cursor schema: version `1`, HMAC-SHA256 protected owner/content/revision/byte-offset
  claims, canonical base64url, maximum token length 2048;
- isolated parser protocols: `web-access-parser-request-v1` and
  `web-access-parser-result-v1`, JSON-only and `extra=forbid`.

Parser capability/profile/representation revisions:

| Capability | Parser revision | Profile revision | Representation schema revisions |
|---|---|---|---|
| text | `text-parser-v1` | `text-default-v1` | `content-text-v1` |
| JSON | `json-stdlib-v1` | `json-default-v1` | `content-json-v1` |
| XML | `xml-defused-v1` | `xml-default-v1` | `content-xml-v1` |
| CSV | `csv-stdlib-v1` | `csv-default-v1` | `content-csv-v1` |
| HTML | `html-trafilatura-lxml-v1` | `html-default-v1` | `content-html-main-v1`, `content-html-structure-v1` |
| PDF | `pdf-pypdf-isolated-v1` | `pdf-native-text-v1` | `content-pdf-text-v1`, `content-pdf-structure-v1` |

## Public facade evidence

FastAPI and FastMCP both report version `0.3.0` and call the same application services.

The v0.3 REST facade adds exactly:

```text
POST /api/v1/retrieval/fetch
GET  /api/v1/content/{content_id}
GET  /api/v1/content/{content_id}/data
GET  /api/v1/content/{content_id}/representations
POST /api/v1/content/inspect
POST /api/v1/content/native-parse
```

Actual FastMCP discovery returns exactly:

```text
web_search
web_fetch
content_get
content_parse
```

The instructions advertise Search, Retrieval, and Content only. There are no Browser or Job
tools in the production catalog. `web_fetch` retains the conservative
`no_blind_retry_after_possible_dispatch` descriptor; `content_parse` is idempotent only because
owner/source/parser/representation convergence is proven.

## Security, race, fault, and recovery evidence

The security suite collects 57 test items. It covers:

- IPv4/IPv6 private, loopback, link-local, unspecified, multicast, reserved, metadata, internal
  CIDR, hostname, redirect, and DNS-rebinding cases;
- validated-address connect semantics, proxy-environment suppression, valid/untrusted/expired/
  wrong-hostname TLS, and absence of any verification-disable path;
- streamed Content-Length, wire, entity, compression ratio, unsupported encoding, inactivity,
  cancellation, and deadline bounds;
- parser allowlist, minimal environment, no credentials, hard network-isolation Compose proof,
  timeout/crash/cancel kill-and-reap, output bounds, and temp/path controls;
- cursor tamper, cross-owner, cross-content, stale-revision, malformed, non-canonical, and
  oversized token rejection.

The dedicated Content lifecycle fault matrix has 7 injected failure points. At every point,
public partial Content remains unavailable, the operation converges to `available` or `failed`,
and maintenance removes only unreferenced staging/final objects. Additional tests cover stale
rows, a final blob already present, missing/corrupt blobs, two reconcilers, response loss after
publication, and reference-aware GC.

The audited race/concurrency selector contains 22 relevant items after excluding one unrelated
fixture whose parameter text matched the selector. It includes exact-last-token admission,
cross-replica concurrency, single-flight ownership/expiry/cancellation, durable-attempt identity,
same-hash CAS finalization, two reconcilers, parser concurrency, concurrent representation reuse,
and bounded Retrieval batch concurrency.

Response-loss evidence remains conservative:

```text
ambiguous web_fetch response loss    acquisition calls 1, automatic duplicate calls 0
explicit second Retrieval operation  acquisition calls 2, distinct operations 2
same canonical content_parse         one logical compatible representation
```

## Load, soak, and resource evidence

The R21 load/soak group contains 6 deterministic tests. The controlled run on this candidate
recorded:

```text
Retrieval requests                    12
Retrieval entity bytes                393216
elapsed                               0.250392 s
observed throughput                   1570403.49 B/s
configured/observed per-host pool     2 / 2

large streamed entity                 6291456 B
tracemalloc peak during stream        642028 B

parser cycles                         3
parser child processes started        15
peak live parser children             2
orphan parser children                0
process handle delta after warm-up    +4
traced memory delta after warm-up     +17499 B

same-hash logical Content sources     18
repeated cursor reads                 144
staging objects after soak            0
remaining referenced final blobs      2
```

Capacity evidence includes pre-task rejection of a 33-item Retrieval batch and a structured
`capacity/response_too_large` item result for an oversized controlled HTTP response. No test
disables SafeResolver, TLS, streaming/hash limits, CAS, ownership, or parser subprocess isolation.

## Test gate

Final coding-agent commands:

```text
uv lock --check
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q
```

Final result: `425 passed in 57.72s`; skips `0`; xfail `0`; xpass `0`; flaky-marked
tests `0`.

Counted evidence:

```text
full test suite                  425
unit                             237
contract                          34
architecture + security           71
integration                       82
package smoke                      1
security test items              57
dedicated lifecycle fault items   7
audited race/concurrency items    22
R21 load/soak items                6
```

PostgreSQL and Redis integration tests use real local containers. The v0.2 accepted Search gates
remain green. The final `web-access-r22-candidate:local` image built successfully with package
`0.3.0`; its Linux hard-network-isolation smoke blocked the controlled child TCP connection, and
its isolated-pypdf smoke passed under the configured process/network limits.

## Hidden orchestration and scope boundary

Instrumented call counts for the complete candidate:

```text
Browser calls       0
OCR calls           0
VLM calls           0
LibreOffice calls   0
Job/arq calls       0
```

No Browser, OCR/VLM, LibreOffice, durable Job, arq worker, public raw HTTP proxy, public storage
path, or generic parser-selection capability was added. v0.4 implementation has not started.

## Pending independent acceptance

No known implementation defect is hidden by a skip, xfail, flaky marker, weakened policy, or
performance shortcut. The remaining status is intentionally `implemented, pending acceptance`:
an independent reviewer must verify the candidate/evidence and may then create a separate factual
acceptance record. This coding task does not do that itself.
