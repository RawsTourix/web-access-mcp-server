# v0.4 — Managed Browser Runtime

## Статус

`ready for implementation`

Версия реализует stateful Browser capability поверх уже готовых v0.1 Foundation и v0.3 Content Core.

Архитектурные blockers закрыты ADR-0001, ADR-0009–ADR-0014. Реализация обязана следовать `implementation-sequence.md` и не заменять принятые boundaries более простым single-process Playwright shortcut.

---

# 1. Цель

После v0.4 REST/MCP client должен уметь выполнить полноценный browser workflow:

```text
create BrowserSession
→ navigate
→ snapshot
→ typed interactions
→ tabs/popups/dialogs
→ screenshots/rendered content/downloads/uploads
→ explicit close
```

с:

- multi-replica Control Plane routing;
- отдельным Browser Worker runtime;
- отдельным session subprocess на BrowserSession;
- отдельным Chromium process на BrowserSession;
- exact snapshot-scoped element refs;
- serialized actions;
- action status recovery;
- honest `unknown` outcomes;
- Content artifact handoff;
- TTL/reaper;
- worker self-fencing;
- public-only browser egress gateway;
- production soak/fault/load tests.

---

# 2. Prerequisites

Обязательны:

- v0.1 Foundation;
- v0.3 Retrieval & Content Core;
- `../../browser.md`;
- `../../application-contracts.md`;
- `../../resource-model.md`;
- `../../persistence.md`;
- `../../security.md`;
- `../../runtime-topology.md`;
- `../../observability.md`;
- `../../rest-api.md`;
- `../../mcp.md`;
- `../../deployment.md`;
- `../../testing.md`;
- `../../release-gates.md`.

Accepted ADR:

- ADR-0001 direct Browser Worker HTTP/RPC;
- ADR-0002 external/internal principal baseline;
- ADR-0009 worker registry/generation/lease/self-fencing;
- ADR-0010 semantic snapshot + exact ElementRefs;
- ADR-0011 per-action dialog policy;
- ADR-0012 separate Chromium per BrowserSession;
- ADR-0013 BrowserSession runtime subprocess;
- ADR-0014 isolated browser egress proxy/gateway.

---

# 3. Explicit non-goals

v0.4 не реализует:

- persistent browser profiles/cookies across sessions;
- credential vault/autologin;
- arbitrary JS evaluate обычному agent;
- CSS/XPath ordinary MCP targeting;
- stealth/fingerprint evasion;
- CAPTCHA bypass;
- proxy rotation/client-supplied proxy;
- durable browser workflows;
- BrowserSession live migration/failover;
- automatic Browser fallback from Retrieval;
- OCR/VLM/screenshot reasoning внутри Web Access;
- shared Chromium process pool optimization;
- browser extension loading;
- remote desktop UI.

---

# 4. Target runtime topology

```text
External REST/MCP client
        │
        ▼
Control Plane replica(s)
        │
        ├── PostgreSQL — BrowserSession durable metadata
        ├── Redis — worker registry + route cache
        │
        │ direct authenticated internal HTTP/RPC
        ▼
Browser Worker supervisor
        │
        ├── session subprocess A
        │      └── Playwright → Chromium A → Context → Pages
        └── session subprocess B
               └── Playwright → Chromium B → Context → Pages

Chromium
→ explicit Browser Egress Proxy/Gateway
→ public Internet
```

Browser Worker не имеет direct public Internet route baseline.

---

# 5. Target code structure

Добавляется/расширяется примерно:

```text
src/web_access/
├── domain/browser/
│   ├── models.py
│   ├── enums.py
│   └── refs.py
├── application/browser/
│   ├── service.py
│   ├── contracts.py
│   ├── lifecycle.py
│   ├── policies.py
│   └── ports.py
├── infrastructure/browser/
│   ├── worker_client.py
│   ├── worker_registry.py
│   ├── placement.py
│   └── repositories.py
├── workers/browser/
│   ├── supervisor.py
│   ├── rpc.py
│   ├── session_process.py
│   ├── session_protocol.py
│   ├── runtime.py
│   ├── snapshots.py
│   ├── actions.py
│   ├── dialogs.py
│   ├── events.py
│   └── artifacts.py
├── transport/rest/
│   └── routers/browser.py
├── transport/mcp/
│   └── tools/browser.py
└── entrypoints/
    └── browser_worker.py
```

Exact file split может уточняться без изменения layer ownership.

---

# 6. BrowserSession SQL model

Минимальная durable таблица `browser_sessions`:

```text
id / session_id
owner_principal_id
state
revision
worker_id | null
worker_generation | null
created_at
updated_at
ready_at | null
last_activity_at | null
idle_expires_at | null
max_expires_at | null
closing_at | null
terminal_at | null
failure_code | null
creation_operation_id
```

Requirements:

- owner index;
- state/expiry indexes для reconciler;
- worker_id/generation index;
- optimistic revision/CAS;
- terminal resources immutable кроме retention/audit fields.

Pages/snapshots/refs не получают отдельные durable rows baseline.

---

# 7. BrowserSession lifecycle

```text
creating
→ ready
→ closing
→ closed
```

Alternative terminal:

```text
creating → failed
ready/closing → lost
ready → expired
```

No resurrection.

---

# 8. Worker identity

Browser Worker startup создаёт/имеет:

```text
worker_id
worker_generation
internal service principal/credential
runtime/profile revision
capacity
```

`worker_generation` новый на каждый process startup.

Redis registry и heartbeat semantics — ADR-0009.

---

# 9. Worker lease defaults

Initial defaults:

```text
heartbeat interval = 5 s
worker lease TTL = 20 s
final loss grace = 30 s without confirmed heartbeat
```

Configurable с validation:

```text
heartbeat interval << lease TTL <= final loss grace
```

Worker self-fences после потери lease: reject new work и начинает bounded cleanup.

---

# 10. Session process model

Canonical:

```text
1 BrowserSession
→ 1 session subprocess
→ 1 Playwright runtime
→ 1 Chromium process
→ 1 non-persistent BrowserContext
→ N Pages
```

Session subprocess не получает:

- DB credentials;
- Redis credentials;
- Search provider secrets;
- external client bearer registry;
- ContentStore credentials.

---

# 11. Supervisor ↔ session IPC

ADR-0013 baseline:

```text
async subprocess stdin/stdout
→ length-prefixed UTF-8 JSON frames
```

Initial frame ceilings:

```text
command <= 1 MiB
result <= 2 MiB
```

Большие snapshots/artifacts externalized.

No pickle.

Child logs идут отдельно (stderr), чтобы не повреждать protocol stream.

---

# 12. Process cleanup

Production Linux:

- session subprocess запускается как отдельная process group/session where appropriate;
- worker/container использует init/subreaper (`tini`/`init: true` или equivalent);
- graceful close bounded;
- затем terminate;
- затем hard kill process tree;
- child всегда reaped;
- stale session temp dirs очищаются startup/reaper.

Нельзя строить kill guarantee на private Playwright Chromium PID API.

---

# 13. Capacity defaults

Initial:

```text
max_sessions_per_worker = 4
max_pages_per_session = 8
max_pending_actions_per_session = 16
```

Configurable внутри hard deployment ceilings.

Capacity slot освобождается только после child process reap и required cleanup.

---

# 14. Session lifetime defaults

Initial:

```text
idle TTL = 5 minutes
maximum lifetime = 30 minutes
creating timeout = 30 seconds
closing graceful deadline = 10 seconds
forced termination grace = bounded additional interval
```

Exact hard ceilings config-validated.

Server-side expiry обязателен независимо от client cleanup.

---

# 15. Session creation protocol

Canonical flow:

1. validate principal/scope/quota;
2. DB insert `creating`;
3. select ready compatible worker from registry;
4. DB persist intended worker_id/generation;
5. RPC create with server-generated `session_id`;
6. worker local capacity reservation;
7. spawn session subprocess;
8. child starts Playwright/Chromium/context/page;
9. worker returns initial `page_id`;
10. DB CAS `creating → ready`;
11. Redis route cache best effort;
12. response.

Crash after child create but before DB ready → reconciler closes orphan child and marks logical resource failed.

---

# 16. Page model

Opaque IDs:

```text
page_id = pg_<uuid4hex>
```

Scoped к session.

Initial blank page создаётся на session startup.

Popup/tab автоматически получает новый page_id и browser event.

---

# 17. Action IDs

```text
action_id = act_<uuid4hex>
```

Server-generated internal stable ID.

Worker supervisor ведёт recent action ledger для network response recovery.

Child знает executing action state и terminal result enough for supervisor coordination.

---

# 18. Session action serialization

Одна BrowserSession имеет один logical serial lane.

Concurrent caller requests:

- bounded queue;
- deterministic order согласно accepted admission;
- overflow → structured capacity/rejection;
- no parallel mutating commands same session.

Different sessions исполняются параллельно.

---

# 19. Action result recovery

При worker RPC response loss:

```text
query same action_id
→ known terminal → return
→ running → same execution
→ uncertain after possible side effect → unknown
```

Never blind retry mutating action.

---

# 20. Session revision

`revision` монотонна для accepted server-side state transitions/commands.

Она не означает DOM revision.

Optional expected revision REST/application checks могут rejected stale client state.

---

# 21. Page generation

`page_generation` меняется при navigation/document replacement, делающем старые refs invalid.

Все old snapshot maps данной generation dispose eagerly.

Dynamic SPA replacement без navigation обнаруживается exact ElementHandle identity check.

---

# 22. Snapshot model

IDs:

```text
snapshot_id = snp_<uuid4hex>
element_ref = el_<uuid4hex>
```

Snapshot metadata:

```text
session_id
page_id
page_generation
session_revision
url/title
created_at
expires_at
truncated
full_content_id | null
```

Public representation:

- semantic ARIA/accessibility-oriented view;
- bounded actionable inventory;
- no raw selectors.

---

# 23. ElementRef exactness

ADR-0010 implementation invariant:

```text
element_ref
→ child SnapshotRefMap
→ private LocatorRecipe + original ElementHandle
→ re-resolve Locator
→ ensure exactly one candidate
→ compare candidate DOM identity with original handle
→ Locator actionability
→ action
```

Replacement element → `stale_target`, даже если похож по role/text.

No fuzzy retargeting.

---

# 24. Snapshot limits

Initial:

```text
max snapshots/page = 3
snapshot/ref TTL = 5 minutes
max refs/snapshot = 300
MCP inline semantic snapshot <= 30,000 chars
REST inline default <= 100,000 chars
backend hard snapshot generation budget <= 256,000 chars
```

Large bounded representation → ContentObject.

---

# 25. Browser action classes

Backend должен покрыть:

```text
navigate
snapshot
click
fill form
select option
check/uncheck
press key
type text
page/tab inspection/switch/close
screenshot
rendered content
download handling
upload from ContentRef
events/diagnostics
```

MCP projection может быть компактнее и объединять только семантически близкие input fields, но не скрывать последовательные state transitions в giant action batch.

---

# 26. Dialog policy

ADR-0011:

Default:

```text
dismiss_and_report
```

Per-action explicit:

```text
behavior = dismiss | accept
prompt_text = optional only for accept
```

Initial max dialogs/action = 5.

Async dialog outside active action auto-dismissed and recorded.

---

# 27. Browser events

Bounded event stream/buffer includes selected:

- page/popup open/close;
- dialogs;
- downloads;
- console entries;
- request/response failures;
- security blocks;
- browser disconnect.

Overflow/gap explicit.

Events are diagnostic, not authoritative business history.

---

# 28. Screenshot/rendered content/download artifact protocol

Child writes only under assigned private session temp root.

Child returns bounded relative artifact descriptors.

Supervisor validates path/size/type and streams artifact through internal RPC/handoff.

Control Plane creates `ContentObject` using v0.3 staging/finalization protocol.

After acknowledgement temp artifact deleted.

Large artifact never base64-embedded in JSON.

---

# 29. Upload protocol

Client supplies owner-authorized `ContentRef`.

Control Plane/Content layer provides bounded artifact stream to worker/supervisor/session temp.

Session subprocess sees only generated temporary materialization, not ContentStore root/credential.

---

# 30. Browser egress

ADR-0014 reference topology:

```text
Browser Worker (no direct Internet)
→ explicit Chromium proxy
→ Browser Egress Proxy/Gateway
→ public Internet
```

Proxy/gateway denies:

- loopback;
- private;
- link-local;
- reserved/special/internal ranges;
- deployment internal CIDRs;
- cloud metadata endpoints.

Baseline outbound website ports: 80/443.

No direct fallback if proxy unavailable.

Top-level client navigation only `http`/`https`.

---

# 31. Internal Browser Worker authentication

External agent bearer token не используется для worker RPC.

Worker registration/heartbeat и Control Plane action calls используют отдельные internal credentials/principals.

Session subprocess не получает эти credentials.

Endpoint registration валидируется против internal network policy.

---

# 32. Worker drain

1. mark/advertise `draining`;
2. no new sessions;
3. existing sessions receive bounded close;
4. after drain deadline terminate/kill remaining children;
5. confirm no child sessions/processes;
6. shutdown worker.

---

# 33. REST API v0.4

REST должен предоставить typed endpoints для:

```text
POST   /api/v1/browser/sessions
GET    /api/v1/browser/sessions/{session_id}
DELETE /api/v1/browser/sessions/{session_id}

browser page/navigation/snapshot/action operations
browser events
screenshot/rendered content/download/upload operations
```

Exact resource/action route shape фиксируется implementation schemas/OpenAPI, сохраняя `rest-api.md` semantics.

REST может раскрывать больше diagnostic/options, чем MCP, но не raw Playwright API.

---

# 34. MCP v0.4

Canonical compact surface ориентировочно:

```text
browser_create
browser_get
browser_close
browser_navigate
browser_snapshot
browser_tabs
browser_click
browser_fill_form
browser_select
browser_press
browser_screenshot
browser_content
browser_events
browser_upload
```

Download обычно возвращается как artifact результата action/navigation и не обязан иметь отдельный «download URL» tool, если реальный workflow этого не требует.

Перед implementation actual catalog сверяется с `mcp.md`; каждый tool должен иметь русские descriptions и actual FastMCP schema tests.

No `*_many` stateful tool variants.

---

# 35. Execution annotations/retry classes

Read-only examples:

```text
browser_get
browser_snapshot
browser_tabs
browser_events
```

Mutating/stateful examples:

```text
browser_navigate
browser_click
browser_fill_form
browser_select
browser_press
browser_upload
```

Mutating tools имеют `never_automatic` semantics после uncertain dispatch.

`browser_close` idempotent cleanup operation.

---

# 36. Structured hints

Примеры:

```text
stale_target
→ recommendation: получить новый snapshot

session_expiring
→ recommendation: закончить workflow/создать новую session

browser_egress_denied
→ объяснить network policy без предложения bypass
```

Hints — typed application data; page text не становится trusted hint.

---

# 37. Observability

Обязательные metrics/log/traces:

- worker generations/heartbeat/lease;
- placement/capacity;
- sessions by state;
- session subprocess count;
- launch latency;
- Chromium/session process crash;
- actions by type/outcome/latency;
- queue wait/overflow;
- unknown outcomes;
- snapshots size/truncation/ref count;
- stale refs;
- dialog events;
- artifact bytes/handoff failures;
- egress denies/proxy failures;
- forced kills;
- TTL/reaper actions;
- drain duration;
- zombie/orphan detection.

No raw sensitive page content in metric labels.

---

# 38. Required tests

## Unit/contract

- Browser state machine;
- ownership/scopes;
- routing generation checks;
- dialog schema;
- action semantics/error mapping;
- MCP field descriptions/annotations.

## Real-browser integration

- create/navigate/snapshot;
- exact click;
- stale replacement target;
- iframe/shadow DOM representative cases;
- form fill/select/check/press;
- popup/tab;
- dialogs;
- screenshot;
- rendered content;
- download/upload Content handoff.

## Race/fault

- two API replicas concurrent create;
- worker capacity race;
- Redis registry loss/rebuild;
- heartbeat partition/self-fencing;
- worker restart new generation;
- response loss after click;
- child crash mid-mutating action;
- crash child during close;
- Control Plane crash after child create before DB ready;
- egress proxy outage.

## Process/soak

- repeated create/close;
- forced kill;
- worker drain;
- worker/container kill;
- no orphan Python/Playwright/Chromium;
- temp dir cleanup;
- ElementHandle/snapshot memory bounded.

## Network security

- public HTTP/HTTPS works;
- private/loopback/link-local/metadata blocked;
- DNS rebinding fixture blocked by proxy/gateway;
- WebSocket public works/private blocked if supported baseline;
- no direct internet route from worker;
- no proxy bypass;
- session child has no internal credentials.

## Load baseline

Measure:

- session creation latency;
- RAM/session;
- action latency;
- stable concurrent sessions/worker;
- snapshot cost;
- cleanup/drain latency.

No shared-process optimization until measurements justify separate ADR.

---

# 39. Release gates

Applicable минимум:

- architecture/import boundaries;
- DB migrations/reconciliation;
- auth/owner isolation;
- Browser lifecycle gate;
- security/egress gate;
- race/fault gate;
- soak/leak gate;
- actual REST/OpenAPI gate;
- actual MCP schema/behavior gate;
- observability/readiness gate;
- local Compose reproducibility.

---

# 40. Definition of Done

v0.4 завершена только если:

1. Browser работает через отдельный Browser Worker runtime.
2. Каждая session имеет отдельный subprocess + Chromium.
3. Multi-replica Control Plane routing не зависит от local RAM map.
4. Worker partition self-fences.
5. Live sessions не мигрируют молча.
6. Element refs не являются public selectors и exact stale-safe.
7. Mutating response loss не дублирует action.
8. `unknown` реально поддерживается.
9. Content artifacts переживают BrowserSession close.
10. Browser egress не видит private/internal network.
11. Session TTL/reaper работает без client cleanup.
12. Forced cleanup действительно уничтожает child process tree.
13. Soak не оставляет zombies/temp leaks.
14. REST предоставляет мощный Browser API.
15. MCP предоставляет компактный LLM-oriented Browser facade с русскими schemas.
16. Все v0.4 release gates зелёные.
