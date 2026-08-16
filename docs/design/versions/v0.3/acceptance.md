# v0.3 Retrieval & Content Core — implementation evidence

## Status

`implemented, pending acceptance`

This is coding-agent evidence for an implementation candidate. It is not an independent
acceptance record and does not grant the status `accepted`. v0.4 remains blocked until factual
independent acceptance of this candidate.

## Candidate identity

- Original implementation starting HEAD: `b46f1c28969d9d98facfbde4bf3089cf851e78b0`.
- Initial R22 implementation candidate: `5bae49ee862034a9ab5746cdc49dc4225b7583ab`.
- Initial evidence HEAD: `79ca7acbf7b5124445e81c3ade46148c765c8ac9`.
- First corrected implementation candidate HEAD:
  `051d1a9ed317e9cfba3767cf21cf8e1fd276462f`.
- Previous evidence HEAD: `4b5375299ca956dcd2902f068f3a0fbc11ef56cf`.
- Parser startup/readiness correction: `bb009a5e6ab7755580326079483ba7d4fafd8516`.
- Final implementation candidate HEAD: `008269bb93a9628b1ae974f3e6867e5208da2d86`.
- Final evidence: the commit containing this document; it changes documentation only.
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

Final correction chain (R1-R22 were not amended or rewritten):

```text
2fd83de hard parser isolation made reproducible with child-installed kernel seccomp
98c4d0f duplicate finalization race found by the real integration run and fixed
051d1a9 CI secret/catalog/production parser-smoke/package-metadata correction
4b53752 previous final-correction evidence
9f6d75d bounded Windows retry for concurrent staging cleanup
bb009a5 real parser seccomp installation preflight before readiness
49710fb parser soak sampling after transport-finalizer cleanup
008269b concurrent staging enumeration/removal convergence
```

The initial evidence was not sufficient for acceptance. Its parser network smoke passed only
because the local Docker daemon had a globally unconfined seccomp posture. Re-running the old
`unshare --user --map-root-user --net` mechanism under Docker's explicit builtin profile failed
with `Operation not permitted`. The corrected candidate does not rely on `unshare` or an
unconfined container profile.

The first corrected candidate still did not prove at startup that a real parser child could
install the production filter. The final correction runs a disposable `sys.executable -I -c`
child that imports and calls the same `install_no_network_filter()` used by parser work. Lifespan
awaits that child before health is marked bootstrapped. Spawn failure, timeout, cancellation, or
non-zero exit is bounded, terminated/killed as needed, reaped, normalized as parser isolation
unavailable, and prevents readiness. The API parent never installs the filter.

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

The security suite collects 62 test items. It covers:

- IPv4/IPv6 private, loopback, link-local, unspecified, multicast, reserved, metadata, internal
  CIDR, hostname, redirect, and DNS-rebinding cases;
- validated-address connect semantics, proxy-environment suppression, valid/untrusted/expired/
  wrong-hostname TLS, and absence of any verification-disable path;
- streamed Content-Length, wire, entity, compression ratio, unsupported encoding, inactivity,
  cancellation, and deadline bounds;
- parser allowlist, minimal environment, no credentials, hard network-isolation Compose proof,
  timeout/crash/cancel kill-and-reap, output bounds, and temp/path controls. A one-shot startup
  preflight uses a fresh isolated interpreter, minimal environment, private temporary working
  directory, five-second timeout, and the exact production filter installer without parsing,
  PDF, Content, or network work. Tests cover success, non-zero exit, spawn failure, timeout, and
  cancellation/reaping. Each production work child installs `no_new_privs` plus a libseccomp
  deny filter for socket/network and `io_uring` syscalls before importing parser code;
- cursor tamper, cross-owner, cross-content, stale-revision, malformed, non-canonical, and
  oversized token rejection.

The dedicated Content lifecycle fault matrix has 7 injected failure points. At every point,
public partial Content remains unavailable, the operation converges to `available` or `failed`,
and maintenance removes only unreferenced staging/final objects. Additional tests cover stale
rows, a final blob already present, missing/corrupt blobs, two reconcilers, response loss after
publication, and reference-aware GC.

The correction runs exposed real Windows concurrency races. After one finalizer linked the
content-addressed target and removed staging, another could observe staging first and then lose
it at `link(2)`; finalization accepts that outcome only after verifying immutable target hash and
size. A concurrent verifier can also hold staging briefly during unlink, so cleanup retries only
Windows sharing violation 32 with a bounded eight-attempt delay. Finally, one reconciler can
remove an orphan between another reconciler's enumeration and `stat`; that missing item is now
treated as work already completed by the winner. The eight-way duplicate-finalize regression
passed ten consecutive runs; the five-test race selector passed three consecutive runs; and the
Content-store/soak group, including deterministic enumerate/remove coverage, passed five
consecutive runs of `34 passed` with no threshold weakening.

The audited race/concurrency selector contains 23 relevant items after excluding one unrelated
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
elapsed                               0.214041 s
observed throughput                   1837110.27 B/s
configured/observed per-host pool     2 / 2
observed HTTP connections             2

large streamed entity                 6291456 B
tracemalloc peak during stream        642028 B

parser cycles                         3
parser child processes started        15
peak live parser children             2
orphan parser children                0
process handle delta after warm-up    +4
traced memory delta after warm-up     +17611 B
parser peak traced memory             100317 B

same-hash logical Content sources     18
repeated cursor reads                 144
staging objects after soak            0
remaining referenced final blobs      2
```

Capacity evidence includes pre-task rejection of a 33-item Retrieval batch and a structured
`capacity/response_too_large` item result for an oversized controlled HTTP response. No test
disables SafeResolver, TLS, streaming/hash limits, CAS, ownership, or parser subprocess isolation.

## Test gate

Final coding-agent gates used the locked environment and real temporary PostgreSQL/Redis
containers. The production Docker builder also ran `uv sync --locked --no-dev --no-editable`.

```text
uv lock --check                    resolved 137 packages, lock unchanged
ruff check .                       all checks passed
ruff format --check .              276 files already formatted
pyright                            0 errors, 0 warnings, 0 informations
```

Counted evidence:

```text
suite                       passed  failed  skipped  xfail  xpass  duration
unit                           238       0        0      0      0    5.62 s
contract                        34       0        0      0      0   18.99 s
architecture + security         77       0        0      0      0   13.68 s
integration                     84       0        0      0      0   23.28 s
full test suite                434       0        0      0      0   52.22 s
migration regression             5       0        0      0      0    2.10 s
R21 load/soak                    6       0        0      0      0    8.63 s
```

The 434 total is 238 unit + 34 contract + 77 architecture/security + 84 integration + 1 package
smoke. There are 62 security items, 7 dedicated lifecycle fault items, 23 audited
race/concurrency items, and 6 R21 load/soak items. No flaky marker or broad ignore was added.

Alembic reports exactly one head, `0003_content_core`. The migration suite proves clean DB to
head, accepted v0.2 DB to head, and repeated upgrade success; no schema correction was added.

## Production image and Compose evidence

The final runtime image is `web-access-mcp-server:0.3`, image ID
`sha256:dbf8f4942f5ae341feccd320d3b72676faaa2895a4aeac877642515e953eec42`.
It contains Python `3.11.9` and `libseccomp2 2.5.4-1+deb12u1`, and runs as
`uid=10001(webaccess) gid=10001(webaccess)`. Direct smokes under
`--security-opt seccomp=builtin` passed:

```text
parent process connected to controlled 127.0.0.1 TCP endpoint
parser child network attempt blocked by the kernel seccomp filter with errno=EPERM
isolated real PDF parse passed under seccomp/process limits
```

The full local Compose equivalent of the required CI job passed `config --quiet`, locked build,
`up --wait`, REST/MCP smoke, pinned SearXNG smoke, PostgreSQL/Redis recovery, graceful shutdown,
repeat migration, UID check, parser network smoke, PDF parser smoke, and cleanup. FastMCP
discovery returned exactly `web_search`, `web_fetch`, `content_get`, `content_parse`. Runtime
inspection reported:

```text
User=10001:10001
Privileged=false
CapAdd=null
SecurityOpt=["seccomp=builtin"]
```

No `seccomp=unconfined`, privileged mode, added capability, `CAP_SYS_ADMIN`, Docker socket,
socket monkeypatch, or reduced-isolation production path is used. The local daemon advertised a
global unconfined default, so the explicit per-container builtin profile was material and was
verified on the running API container.

The final current-source image was then rebuilt from implementation HEAD, resolving 137 locked
packages and installing 125 runtime packages. A fresh scoped stack reached healthy only after
the lifespan preflight completed. REST/MCP smoke again reported zero live Yandex calls; the
production network smoke connected from the parent and observed exact `errno=EPERM` in the
parser child; the isolated PDF smoke passed under the same builtin seccomp profile.

CI now supplies the required synthetic `WEB_ACCESS_CONTENT_CURSOR_SECRET` in job scope and runs
both production parser smokes through the built `api` image. Local Compose validation used
`config --quiet`; no secret value was printed in command output or application logs. One first
Windows-only invocation used the Linux relative bind syntax and failed before the parser smoke
because `/tests` was not mounted; the same command with an absolute Windows host path passed.
The checked-in relative command remains the correct GitHub Actions/Linux form.

Host evidence environment: Windows NT `10.0.26200` x86-64, Docker Desktop `4.40.0`, Docker
Engine `28.0.4`, Compose `v2.34.0-desktop.1`, runc `1.2.5`, Docker VM Linux
`5.15.167.4-microsoft-standard-WSL2` amd64. Two no-cache image attempts encountered external
registry/PyPI DNS/timeouts and did not produce passing images. The final current-source locked
build passed with the existing BuildKit dependency cache; the failed external-download attempts
are not counted as green gates.

## Hidden orchestration and scope boundary

Instrumented call counts for the complete candidate:

```text
Browser calls       0
OCR calls           0
VLM calls           0
LibreOffice calls   0
Job/arq calls       0
public Search calls 0
public Retrieval calls 0
live Yandex calls   0
```

No Browser, OCR/VLM, LibreOffice, durable Job, arq worker, public raw HTTP proxy, public storage
path, or generic parser-selection capability was added. v0.4 implementation has not started.
Application tests used only localhost-controlled servers and Compose mock providers. Docker Hub,
GHCR, and the locked Python package registry were contacted only to construct infrastructure
images; these were build dependency downloads, not Web Access product retrieval/search calls.

## Pending independent acceptance

No known implementation defect is hidden by a skip, xfail, flaky marker, weakened policy, or
performance shortcut. The remaining status is intentionally `implemented, pending acceptance`:
an independent reviewer must verify the candidate/evidence and may then create a separate factual
acceptance record. This coding task does not do that itself.
