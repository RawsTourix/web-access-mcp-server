# v0.4 — Implementation sequence

## Назначение

Обязательный порядок реализации `Managed Browser Runtime`.

Ключевой принцип:

> Не начинать с MCP/REST или локального Playwright wrapper. Сначала ownership/process/routing/egress/recovery, затем Browser semantics/actions/artifacts, и только после этого public facades.

Canonical exact targets:

- `../../browser.md`;
- Browser ADR-0001/0009..0014;
- ADR-0024/0025;
- `../../contracts/browser-api-v1.md`;
- relevant Browser sections `../../contracts/mcp-tools.md`.

---

# B0 — Preconditions

Before code:

1. v0.1/v0.3 accepted gates green;
2. existing application/result/content contracts characterized;
3. Browser package dependency/import rules test prepared;
4. controlled public/private web targets/egress fixtures prepared;
5. Playwright/Chromium dependency/container versions pinned for implementation branch;
6. public Internet is not required for default CI.

**Gate:** baseline green with no Browser runtime.

---

# B1 — Domain/application Browser contracts

Create:

```text
domain/browser/
application/browser/
```

Models/contracts:

- BrowserSessionId/PageId;
- lifecycle states/revisions;
- PageInfo/page_generation;
- typed action/result;
- Snapshot/ElementRef metadata;
- Browser events;
- normalized Browser errors;
- action ID/recovery state.

Ports:

```text
BrowserSessionRepository
BrowserWorkerRegistry
BrowserWorkerClient
BrowserPlacementPolicy
BrowserArtifactHandoff
```

State-machine/unit tests before infrastructure.

**No Playwright yet.**

---

# B2 — PostgreSQL BrowserSession persistence

Alembic `browser_sessions` according v0.4/resource design.

Repository supports:

- create `creating`;
- owner get;
- CAS revision transitions;
- stale creating/expiry/worker-generation queries;
- ready/closing/closed/failed/lost/expired;
- no hidden commit.

Race tests:

- double terminal;
- stale revision;
- close vs expiry;
- worker loss vs late ready.

---

# B3 — Browser Worker identity/auth/registration

Create Browser Worker entrypoint without real browser session.

Implement internal trusted service identity separate from external Bearer clients.

Control Plane operations:

```text
register
heartbeat
status/drain admission
```

Validate worker endpoint/network/runtime revision/generation.

Redis worker registry TTL.

Tests invalid auth, external endpoint, restart generation, TTL.

---

# B4 — Lease/self-fencing/placement

Implement ADR-0009:

- heartbeat;
- worker lease;
- self-fence;
- final loss grace;
- DB authoritative `worker_id+generation`;
- Redis route cache;
- ready-worker placement;
- capacity rejection;
- drain excludes worker.

Multi-replica Redis loss/flush/partition/stale generation/capacity tests.

---

# B5 — Direct internal Browser Worker RPC

Implement ADR-0001.

Internal minimum:

```text
create session
session status
execute action
get same action status
close session
artifact stream/status
```

Requirements:

- internal auth;
- generation/session validation;
- bounded request/result;
- propagated deadlines;
- action IDs;
- normalized internal errors;
- no Redis action bus.

Response-loss simulation with fake executor required.

---

# B6 — Session subprocess supervisor

Implement ADR-0013 before Playwright.

Supervisor:

- `asyncio.create_subprocess_exec`, no shell;
- session-private temp root;
- minimal env allowlist;
- separate process group/session;
- length-prefixed UTF-8 JSON frames;
- command <=1 MiB / result <=2 MiB baseline;
- stderr diagnostics separate;
- bounded I/O/deadline;
- graceful close → terminate → kill → reap;
- stale temp cleanup.

Fake child tests hang/crash/malformed/oversized/delayed frames.

---

# B7 — Browser egress boundary

Implement ADR-0014 before arbitrary browsing.

Reference topology:

```text
Browser Worker/session child
(no direct Internet route)
→ explicit forward proxy/gateway
→ public Internet
```

Gateway denies private/loopback/link-local/reserved/internal/metadata destinations and unsupported ports.

No direct fallback when egress gateway unavailable.

Controlled network tests are release blocker before B8 real browsing.

---

# B8 — Playwright session child foundation

Session child:

```text
start Playwright
→ launch dedicated Chromium through controlled proxy
→ non-persistent BrowserContext
→ initial blank Page
→ PageId
```

Rules:

- one logical session = one child = one Chromium;
- headless baseline;
- sandbox/security not silently disabled;
- no client launch args/proxy/profile/extensions/CDP;
- no internal credentials child-side.

Isolation/egress/kill tests with sibling sessions.

---

# B9 — Real session create/close/reconciler

Connect B2–B8.

Create protocol follows Browser design.

Reconcile:

- stale creating/orphan child;
- lost worker generation;
- stuck closing;
- idle/max expiry;
- disappeared child.

Close idempotent; capacity released only after child reap/required cleanup.

Fault windows:

- child created before DB ready crash;
- response loss after ready commit;
- worker crash create/close.

---

# B10 — Pages/generations/event buffer

Implement:

- initial Page;
- opaque PageIds;
- page create/close/list;
- navigate;
- popup/new-page events;
- page generation;
- bounded sequenced event log/gap indicator.

No required hidden active page.

Closing last page rejected.

Navigation/document replacement invalidates old refs.

---

# B11 — Semantic snapshot + exact ElementRef

Implement ADR-0010:

```text
semantic/ARIA snapshot
→ bounded ref inventory
→ private locator recipe
→ snapshot-time ElementHandle anchor
```

Action resolution:

```text
re-resolve Locator
→ exactly one candidate
→ exact DOM identity == anchor
→ actionability
```

Tests:

- same node;
- identical replacement stale;
- ambiguous;
- iframe;
- representative shadow DOM;
- snapshot/ref limits;
- huge snapshot Content fallback;
- ref disposal on eviction/navigation/close.

No heuristic retargeting.

---

# B12 — Action ledger + core interaction primitives

Implement per-session serialized queue and action ledger first:

```text
received
→ dispatched
→ running
→ terminal | unknown
```

Then typed actions in this order:

1. click;
2. fill form;
3. type;
4. structured press key;
5. hover;
6. drag;
7. scroll;
8. wait.

Rules from exact contracts:

- no selectors/coordinates/force/JS;
- fill-form sequential **fail-fast**, remaining `not_attempted`;
- select/check/radio are typed values inside fill-form, not separate MCP intents;
- press uses structured named/character key + modifiers;
- scroll uses direction + viewport units, optional scrollable ElementRef;
- scroll does not auto-snapshot;
- wait typed/bounded, no JS/networkidle semantic shortcut.

Response-loss tests prove no second click/press/scroll etc. after uncertain dispatch.

---

# B13 — Dialog policy

Implement ADR-0011:

- default dismiss-and-report;
- per-action accept/dismiss;
- prompt text only accept;
- async dialog auto-dismiss/report;
- bounded dialogs/action.

Test beforeunload/dialog interaction with action outcome recovery.

---

# B14 — Browser → Content artifacts

Implement:

```text
screenshot
rendered page content
downloads
```

Flow:

```text
child private temp
→ supervisor validate/stream
→ Control Plane Content ingest/finalize
→ ContentRef
→ temp delete after ack
```

No base64 giant result, no child ContentStore credentials/path leakage.

Artifact creation participates in Content quota/lifecycle and conservative retry semantics ADR-0024.

Fault tests each handoff crash window.

---

# B15 — Content → Browser multi-file upload

After artifact/content handoff exists, implement file-input upload:

```text
owner-authorized ContentIds[]
→ bounded temporary materialization
→ file input ElementRef
→ Playwright set input files
```

Exact rules:

- MCP 1..16 ContentIds;
- REST 1..32;
- target supporting `multiple` required when >1;
- no silent truncation;
- no local host path;
- temp cleanup;
- action recovery/no blind retry.

---

# B16 — Browser diagnostics/events

Expose bounded:

- console;
- request/response failures;
- egress denies;
- dialogs/downloads/popups;
- browser disconnect/lifecycle.

No unbounded HAR/network recording baseline.

Sensitive values redacted.

---

# B17 — REST Browser facade

Only after runtime/actions/artifacts stable.

Implement exactly from:

```text
../../contracts/browser-api-v1.md
../../contracts/common-models.md
```

Routers call application services only.

Tests:

- auth/owner;
- exact OpenAPI unions/bounds;
- page/session lifecycle;
- snapshot refs;
- scroll;
- fail-fast form;
- structured press;
- multi-upload;
- unknown/retry projection;
- no raw Playwright/internal worker fields.

---

# B18 — MCP Browser facade

Implement only Browser subset of:

```text
../../contracts/mcp-tools.md
```

Current semantic Browser tools include explicit:

```text
browser_scroll
```

and use:

- Russian descriptions;
- exact bounds/unions;
- no selectors;
- one stable execution class/tool;
- ADR-0024 conservative resource/side-effect retry metadata;
- actual FastMCP schema tests.

Agent workflow test:

```text
list tools
→ description chooses tool
→ get schema
→ arguments understandable
→ result/hints/resources usable
```

---

# B19 — TTL/reaper/drain race hardening

Matrix:

- expiry while action queued/running;
- close vs expiry;
- self-fence vs incoming action;
- worker drain/restart;
- proxy outage;
- Redis loss;
- Control Plane replica restart;
- child crash during action/artifact/upload.

No Browser resource depends on MCP connection lifetime.

---

# B20 — Security audit

Mandatory:

- private IPv4/IPv6/metadata blocked;
- DNS rebinding controlled fixture blocked by egress boundary;
- direct worker Internet route absent;
- WebSocket/internal access tested under gateway policy;
- proxy failure no fallback;
- child env secret scan;
- temp/path traversal;
- upload ownership;
- malformed IPC;
- untrusted browser/dialog/event text;
- no raw scheme/selector/JS escape.

---

# B21 — Soak/load/fault roast

Run:

- thousands create/close;
- forced kill;
- repeated navigate/snapshot/action/scroll;
- long/lazy page exploration;
- popup/dialog/download/upload loops;
- worker restart/drain;
- multi-worker placement;
- response-loss injection;
- memory/process/temp/ref leak checks.

Measure:

```text
session launch p50/p95/p99
RAM/session
action latency
snapshot latency/size
scroll/snapshot workflow latency
max stable sessions/worker
forced cleanup/drain time
```

Do not optimize to shared Chromium in v0.4.

---

# B22 — Documentation/acceptance closure

Before v0.4 complete:

1. code layout respects dependency rules;
2. ADR tests represented;
3. actual Browser OpenAPI matches exact contract;
4. actual FastMCP Browser schemas match exact contract;
5. retry metadata matches ADR-0024;
6. scroll/fail-fast/key/multi-upload tested;
7. current/version status updated only from factual evidence;
8. release gates recorded;
9. no single-process/selector/direct-egress shortcut remains.

---

# Forbidden shortcuts

Do not:

- run Playwright in FastAPI handler;
- store authoritative BrowserContexts in Control Plane RAM;
- use Redis action queue;
- share one global Chromium baseline;
- retry stateful action after timeout without same-action status recovery;
- omit `browser_scroll` and compensate by hidden snapshot scrolling;
- expose CSS/XPath/JS because ElementRef is harder;
- keep separate select/check MCP aliases instead of exact fill-form contract;
- accept free-form keyboard shortcuts instead of structured key model;
- truncate multi-file upload silently;
- bypass egress gateway;
- give child DB/Redis/ContentStore/provider secrets;
- mark artifact success before Content handoff where durable result expected;
- auto-launch Browser from Retrieval;
- weaken flaky Browser tests.

---

# Final acceptance

Implementation sequence complete only when v0.4 README/Browser design/exact contracts and applicable Browser/security/race/soak/schema gates are proven by automated + controlled integration evidence.
