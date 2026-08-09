# v0.4 — Implementation sequence

## Назначение

Документ задаёт обязательный порядок реализации `Managed Browser Runtime`.

Он предназначен прежде всего для Codex/ChatGPT implementation work и не заменяет канонические design docs/ADR.

Ключевое правило:

> Нельзя начинать с MCP tools или простого локального Playwright wrapper. Сначала строятся runtime ownership, worker protocol, lifecycle и recovery; затем Browser semantics; только после этого REST/MCP facades.

---

# Patch B0 — Preconditions / characterization

До production-кода:

1. убедиться, что v0.1/v0.3 migrations/tests зелёные;
2. зафиксировать текущие application/result/content contracts тестами;
3. добавить architecture import assertions для будущего Browser package;
4. добавить test fixtures для controlled public/private HTTP targets и browser egress scenarios;
5. зафиксировать exact Playwright dependency/image compatibility в `uv.lock`/container build;
6. CI не выполняет произвольный public Internet browser test по умолчанию.

**Gate:** baseline зелёный без Browser implementation.

---

# Patch B1 — Browser domain/application contracts

Добавить:

```text
domain/browser
application/browser
```

Модели:

- BrowserSessionId;
- BrowserPageId;
- BrowserSessionState;
- BrowserSession metadata;
- BrowserPageInfo;
- BrowserAction type/result;
- Snapshot metadata;
- Browser event model;
- Browser-specific errors.

Ports:

- BrowserSessionRepository;
- BrowserWorkerRegistry;
- BrowserWorkerClient;
- BrowserPlacementPolicy;
- BrowserArtifactHandoff;
- Clock/ID dependencies reused from foundation.

Реализовать state-machine unit tests до infrastructure.

**Не добавлять Playwright.**

---

# Patch B2 — PostgreSQL BrowserSession persistence

Alembic migration:

```text
browser_sessions
```

Минимум fields/indexes согласно `README.md`.

Repository:

- create `creating`;
- CAS revision updates;
- get owner-scoped;
- list stale creating/expiring/worker generation sessions;
- mark ready/closing/closed/failed/lost/expired;
- no hidden commits.

Race tests:

- double terminal transition;
- stale revision;
- close vs expiry;
- loss vs late ready.

**Gate:** lifecycle persistence deterministic.

---

# Patch B3 — Browser Worker internal authentication and registration

Создать Browser Worker entrypoint **без Playwright session execution пока**.

Реализовать internal service principal/config отдельно от external Bearer clients.

Control Plane internal endpoints/application operations:

- register worker;
- heartbeat worker;
- optional drain state transition/status.

Validate advertised endpoint:

- internal scheme/address policy;
- allowed port/network;
- generation/runtime revision.

Redis worker registry TTL.

Tests:

- invalid credential;
- malicious external endpoint;
- restart same worker_id/new generation;
- TTL.

---

# Patch B4 — Worker lease/self-fencing + placement

Реализовать ADR-0009:

- heartbeat loop;
- lease tracking;
- self-fenced state;
- final loss grace;
- Redis route registry/cache;
- DB authoritative owner coordinates;
- placement among ready workers;
- local final capacity rejection.

Пока worker create_session может быть fake/test executor.

Multi-replica integration tests:

- Redis flush/rebuild;
- temporary partition/recover;
- stale generation;
- capacity race;
- drain excludes worker.

**Gate:** routing correct before real browser state exists.

---

# Patch B5 — Browser Worker direct RPC protocol

Реализовать ADR-0001:

Control Plane → owning worker authenticated internal HTTP/RPC.

Operations internal minimum:

```text
create session
session status
execute action
get action status
close session
artifact stream/status as required
```

Requirements:

- bounded bodies;
- deadline propagation;
- operation/action IDs;
- internal auth;
- generation/session validation;
- normalized internal errors;
- no Redis action queue.

Add response-loss simulation tests with fake session executor.

---

# Patch B6 — Session subprocess supervisor protocol

Реализовать ADR-0013 **до Playwright actions**.

Supervisor:

- `asyncio.create_subprocess_exec`, no shell;
- generated session temp root;
- minimal environment allowlist;
- process group/session semantics;
- length-prefixed UTF-8 JSON frames;
- 1 MiB command / 2 MiB result initial ceilings;
- stderr separate diagnostics;
- bounded read/write/deadline;
- graceful close → terminate → kill → reap;
- startup stale temp cleanup.

Сделать fake child entrypoint, который:

- отвечает ping;
- симулирует hang;
- crash;
- malformed/oversized frame;
- delayed result.

**Gate:** supervisor process lifecycle доказан без Playwright.

---

# Patch B7 — Browser egress gateway reference deployment

Реализовать ADR-0014 infrastructure before allowing real arbitrary browsing.

Reference Compose:

```text
browser-control internal network
browser-egress network
egress proxy/gateway
Browser Worker without direct Internet route
```

Выбрать и **pin** конкретный maintained forward-proxy image/config during implementation review.

Proxy policy:

- public-only destinations;
- ports 80/443 baseline;
- deny loopback/private/link-local/reserved/internal/metadata;
- no direct fallback.

Controlled network tests must pass before Playwright browsing enabled.

**Release blocker:** если reference proxy не может доказуемо enforce destination policy, заменить implementation, а не ослаблять ADR.

---

# Patch B8 — Playwright session runtime foundation

Добавить Playwright dependency/browser image.

Session child:

```text
start Playwright
→ launch Chromium with server-controlled profile/proxy
→ new non-persistent context
→ initial blank page
→ return page_id
```

Requirements:

- one child → one Chromium;
- headless baseline;
- sandbox enabled in supported production topology;
- no client launch args;
- no persistent profile;
- no extensions;
- explicit egress proxy;
- no internal credentials in child env.

Tests:

- two sessions → two children/two Chromium;
- cookie/storage isolation;
- public site fixture works through proxy;
- private target blocked;
- child kill does not affect sibling.

---

# Patch B9 — Real BrowserSession create/close/reconciler

Connect B2–B8.

Create protocol exactly follows v0.4 README.

Implement reconciler for:

- stale `creating` with worker child created;
- worker generation loss;
- `closing` stuck;
- idle/max expiry;
- child disappeared.

Close:

- idempotent application semantics;
- capacity slot release only after reap;
- forced kill observable.

Fault injection:

- Control Plane crash after child create before DB ready;
- response loss after ready commit;
- worker crash during create/close.

---

# Patch B10 — Pages, generations and events

Session child registry:

- page IDs;
- initial page;
- navigate;
- popup/new page events;
- page close;
- page generation;
- active/default page convenience only, backend actions remain unambiguous.

Implement bounded event buffer with sequence/gap metadata.

Navigation invalidates old generation snapshot refs.

Tests for SPA/navigation/popups/page close.

---

# Patch B11 — Semantic snapshot + ElementRef

Реализовать ADR-0010.

Do not start with public CSS/XPath.

Pipeline:

1. semantic/ARIA-oriented snapshot;
2. bounded actionable inventory;
3. `element_ref` generation;
4. private locator recipe;
5. snapshot-time ElementHandle anchor;
6. retention/TTL;
7. handle dispose on eviction/navigation/close.

Action resolution exact identity tests:

- same node still works;
- identical replacement becomes stale;
- ambiguous locator rejected;
- iframe;
- representative shadow DOM;
- max refs/snapshot;
- huge snapshot Content fallback.

**Gate:** no heuristic retargeting.

---

# Patch B12 — Typed browser interactions + action ledger

Implement typed actions incrementally:

1. click;
2. fill form;
3. select;
4. check/uncheck;
5. press key;
6. type text;
7. additional justified interactions.

Use Locator actionability.

Implement supervisor recent action ledger/status recovery:

```text
received
dispatched
running
terminal
unknown
```

Response-loss tests must prove click/submit not executed twice.

No `force` baseline.

---

# Patch B13 — Dialogs

Implement ADR-0011:

- default dismiss-and-report;
- per-action accept/dismiss;
- prompt text validation;
- async dialogs auto-dismiss;
- max dialogs/action;
- bounded events.

Test beforeunload and response-loss/unknown semantics.

---

# Patch B14 — Content artifacts

Implement Browser → Content handoff for:

- screenshot;
- rendered HTML/content;
- downloads;
- upload materialization from ContentRef.

Rules:

- child only writes generated session temp;
- no arbitrary paths;
- no ContentStore credential child-side;
- large artifact streamed, not JSON/base64;
- Content uses v0.3 `creating → available` protocol;
- temp deleted after acknowledgement;
- Content survives BrowserSession close.

Fault tests at every handoff phase.

---

# Patch B15 — Browser diagnostics/events surface

Add bounded useful diagnostics:

- selected console;
- request/response failures;
- egress denies;
- browser disconnect;
- downloads/dialogs/popups.

Do not implement unbounded network recorder/HAR baseline.

Sensitive values redacted.

---

# Patch B16 — REST facade

Only now add public Browser REST projection.

Use application services; routers never call Playwright/supervisor directly.

Implement typed session/page/action/content/event endpoints according `rest-api.md`.

Requirements:

- owner/scopes;
- operation envelopes/errors;
- no internal worker endpoint/process fields;
- no raw Playwright types;
- OpenAPI schema tests;
- negative auth/owner tests.

---

# Patch B17 — MCP facade

Implement only LLM-useful compact tools from approved catalog.

Requirements:

- Russian tool/field descriptions;
- every public nested field documented;
- no `*_many` stateful variants;
- no selectors;
- `element_ref` targeting;
- accurate annotations/retry class;
- structured hints/errors;
- no authentication secret argument;
- actual FastMCP schema extracted/tested.

Before merge review catalog against real agent workflow:

```text
mcp_list_tools
→ description sufficient for discovery
→ mcp_get_tool_schema
→ arguments understandable without guesswork
```

---

# Patch B18 — TTL/reaper/drain hardening

Run real timing/race matrix:

- idle expiry while action queued/running;
- explicit close vs expiry;
- worker self-fence vs incoming action;
- rolling drain;
- worker crash;
- proxy outage;
- Redis loss;
- Control Plane replica restart.

No resource may depend on MCP connection lifetime.

---

# Patch B19 — Security audit

Mandatory checks:

- private IPv4/IPv6 blocked;
- metadata/link-local blocked;
- DNS rebinding fixture blocked at gateway;
- WebSocket direct/internal blocked;
- direct worker Internet route absent;
- proxy failure no fallback;
- child env credential scan;
- temp path traversal;
- upload ownership;
- malformed IPC;
- browser dialog/page text untrusted;
- no arbitrary schemes;
- no raw secrets/log leaks.

---

# Patch B20 — Soak/load/fault roast

Run dedicated Browser roast:

- thousands create/close cycles;
- forced kill cycles;
- repeated navigation/snapshot/action;
- popup/dialog/download loops;
- worker restart/drain loops;
- multi-worker placement;
- response-loss injection;
- memory/process/temp leak checks.

Measure:

```text
session launch p50/p95/p99
RAM/session
action latency
snapshot latency/size
max stable sessions/worker
forced cleanup time
drain time
```

Do **not** optimize to shared Chromium as part of v0.4. Measurements only inform future ADR.

---

# Patch B21 — Documentation/acceptance closure

Before marking v0.4 complete:

1. actual code layout matches dependency rules;
2. all ADR acceptance tests represented;
3. actual OpenAPI reviewed;
4. actual MCP schemas reviewed;
5. README/version status updated;
6. `current.md` updated with evidence;
7. release gates recorded;
8. unresolved defects/flakes explicitly listed;
9. no «temporary» single-process Browser shortcut remains.

---

# Forbidden shortcuts

Codex/implementation must not:

- instantiate Playwright inside FastAPI request handler;
- keep all BrowserContexts directly in Control Plane memory;
- use Redis queue as Browser action bus;
- use one global Chromium process baseline;
- retry click after timeout without action status recovery;
- expose CSS/XPath because ElementRef is harder;
- allow direct Browser Worker Internet egress instead of proxy/gateway;
- give Browser child DB/Redis/ContentStore credentials;
- store downloads only in browser temp and call operation successful without Content handoff when durable result expected;
- launch Browser automatically from Retrieval;
- weaken tests because browser cases are flaky.

---

# Final acceptance

Implementation sequence считается завершённой только когда все criteria из `README.md` и applicable release gates доказаны automated tests + controlled integration/soak evidence.
