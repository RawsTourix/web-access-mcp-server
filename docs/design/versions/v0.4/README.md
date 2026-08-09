# v0.4 — Managed Browser Runtime

## Статус

`ready for implementation`

Версия добавляет полноценную stateful Browser capability поверх v0.1 Foundation и v0.3 Content Core.

Подробный порядок реализации: `implementation-sequence.md`.

Точный MCP catalog **не дублируется** в этом version README. Канонические владельцы public MCP surface: `../../mcp.md`, ADR-0021 и ADR-0022.

---

# 1. Цель

После v0.4 backend/REST/MCP должны поддерживать explicit browser workflow:

```text
create BrowserSession
→ navigate
→ semantic snapshot
→ typed interactions
→ pages/popups/dialogs
→ screenshots/rendered content/downloads/uploads
→ explicit close / server expiry
```

с:

- отдельным Browser Worker runtime;
- multi-replica Control Plane routing;
- отдельным session subprocess на BrowserSession;
- отдельным Chromium process на BrowserSession;
- exact snapshot-scoped element refs;
- serialized session actions;
- action result/status recovery;
- first-class `unknown` outcome;
- Content artifact handoff;
- TTL/reaper;
- worker self-fencing;
- public-only browser egress boundary.

---

# 2. Canonical design / ADR

- `../../browser.md`;
- `../../resource-model.md`;
- `../../security.md`;
- `../../runtime-topology.md`;
- `../../rest-api.md`;
- `../../mcp.md`;
- ADR-0001 Browser Worker direct RPC;
- ADR-0009 worker registry/lease/fencing;
- ADR-0010 snapshot/ElementRef;
- ADR-0011 dialog policy;
- ADR-0012 separate Chromium per session;
- ADR-0013 session subprocess ownership/kill boundary;
- ADR-0014 browser egress proxy/gateway;
- ADR-0022 public MCP catalog freeze candidate.

При process-management conflict между ADR-0012 и ADR-0013 приоритет имеет ADR-0013.

---

# 3. Explicit non-goals

- persistent browser profiles/cookies;
- credential vault/autologin;
- arbitrary JS evaluation для обычного agent;
- CSS/XPath normal MCP targeting;
- stealth/fingerprint evasion;
- CAPTCHA bypass;
- proxy rotation/client-supplied proxy;
- durable browser workflow;
- live BrowserSession migration/failover;
- automatic Browser fallback from Retrieval;
- OCR/VLM/screenshot semantic reasoning;
- shared Chromium pool optimization;
- browser extensions/remote desktop.

---

# 4. Runtime topology

```text
Control Plane replica(s)
        │
        │ authenticated direct internal HTTP/RPC
        ▼
Browser Worker supervisor
        │
        ├── BrowserSession subprocess A
        │      └── Playwright → Chromium A → BrowserContext → Pages
        └── BrowserSession subprocess B
               └── Playwright → Chromium B → BrowserContext → Pages

Chromium
→ explicit Browser Egress Proxy/Gateway
→ public Internet
```

Browser Worker has no direct public Internet route baseline.

---

# 5. BrowserSession durable metadata

PostgreSQL `browser_sessions` stores owner/lifecycle/routing coordinates, conceptually:

```text
session_id
owner_principal_id
state
revision
worker_id | null
worker_generation | null
created/updated/ready/last_activity timestamps
idle/max expiry
closing/terminal timestamps
failure/loss metadata
creation operation ID
```

Pages/snapshots/ElementRefs are live runtime children and are not durable PostgreSQL resources baseline.

---

# 6. Session lifecycle

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

No automatic resurrection.

MCP/HTTP transport reconnect does not affect session lifecycle.

---

# 7. Worker routing

PostgreSQL is authoritative for:

```text
worker_id
worker_generation
```

Redis holds ephemeral worker registry/route cache.

Worker:

- heartbeats to Control Plane;
- has generation changing on restart;
- self-fences after lease loss;
- stops new sessions while draining.

Initial direction:

```text
heartbeat = 5 s
lease TTL = 20 s
final loss grace = 30 s
```

Configurable with validated relationship.

No live migration of BrowserSession to another generation.

---

# 8. Session process boundary

Canonical invariant:

```text
1 BrowserSession
→ 1 session subprocess
→ 1 Playwright runtime
→ 1 Chromium process
→ 1 non-persistent BrowserContext
→ N Pages
```

Session subprocess owns all live Playwright objects and snapshot handles.

Supervisor owns:

- process lifecycle;
- capacity;
- internal RPC;
- routing to child;
- artifact forwarding;
- drain/reaping.

Child receives no PostgreSQL/Redis/Search provider/ContentStore/external auth secrets.

---

# 9. Supervisor ↔ child protocol

ADR-0013 baseline:

```text
async subprocess stdin/stdout
→ length-prefixed UTF-8 JSON frames
```

Initial ceilings:

```text
command <= 1 MiB
result <= 2 MiB
```

No pickle.

Large snapshot/artifact externalized through Content boundary.

Child stderr is diagnostics, not protocol stream.

---

# 10. Process cleanup

Browser Worker must be able to:

```text
cooperative close
→ bounded grace
→ terminate session subprocess
→ bounded grace
→ hard-kill process tree if needed
→ reap
→ temp cleanup
```

No reliance on private Playwright Chromium PID APIs.

Production worker uses init/subreaper/process-group semantics preventing orphan Chromium.

Capacity slot releases only after child reap/required cleanup.

---

# 11. Initial capacity/lifetime profile

Initial defaults:

```text
max sessions/worker = 4
max pages/session = 8
max pending actions/session = 16

idle TTL = 5 min
maximum lifetime = 30 min
create timeout = 30 s
close graceful deadline = 10 s
```

These are measured/tunable operational defaults, not universal constants.

---

# 12. Page identity

Each page/tab/popup gets opaque:

```text
page_id = pg_<uuid4hex>
```

Initial blank page is created with session.

Navigation is always explicit separate operation.

There is no required hidden “active page” state in public MCP freeze; page actions accept explicit `page_id`.

---

# 13. Session action serialization

One BrowserSession has one logical serial lane.

Different sessions run concurrently.

This protects ordering for:

- cookies/storage;
- page/navigation state;
- dialogs/popups;
- snapshot/ref validity;
- action recovery/cancellation.

No parallel mutating commands inside same session baseline.

---

# 14. Action identity / recovery

Internal:

```text
action_id = act_<uuid4hex>
```

If Control Plane loses worker response:

```text
query same action_id
→ terminal known → return same result
→ still running → same execution
→ outcome cannot be proven after possible side effect → unknown
```

Never retry click/fill/press/navigation blindly.

---

# 15. Snapshot / ElementRef

Snapshot:

- semantic/ARIA-oriented;
- bounded;
- actionable inventory;
- `snapshot_id`;
- `page_generation`;
- explicit `element_ref`s;
- optional full ContentRef for large representation.

ElementRef exact strategy ADR-0010:

```text
element_ref
→ private LocatorRecipe + original ElementHandle
→ re-resolve Locator
→ exactly one candidate
→ compare exact DOM node identity
→ Locator actionability
→ action
```

Replacement node is `stale_target`; no fuzzy retargeting.

Initial:

```text
3 snapshots/page
5 min ref TTL
300 refs/snapshot
MCP inline snapshot <= 30k chars
REST inline default <= 100k chars
backend hard generation <= 256k chars
```

---

# 16. Browser actions

Backend supports typed semantic operations, including:

- navigation;
- page create/close/list;
- snapshot;
- click;
- form fill;
- typing/key press;
- hover/drag/wait where justified;
- screenshot;
- rendered content;
- upload/download artifact handling;
- bounded events/diagnostics.

The **exact MCP decomposition** follows ADR-0022, not this README.

No arbitrary Playwright code/selector ordinary facade.

---

# 17. Dialogs

ADR-0011:

Default unexpected dialog:

```text
dismiss + report
```

Per-action explicit accept/dismiss may be requested where schema supports it.

Prompt text only with explicit accept.

Async dialog outside active action auto-dismissed and recorded.

Initial max dialogs/action = 5.

---

# 18. Content artifacts

Browser-generated:

```text
screenshot
rendered HTML/content
download
```

must cross Content lifecycle:

```text
session temp artifact
→ supervisor validates/streams
→ Control Plane Content ingest
→ ContentObject available
→ child temp delete
```

Upload is reverse:

```text
owner-authorized ContentRef
→ bounded internal materialization
→ file input
```

No host path/client ContentStore access.

Content survives BrowserSession close.

---

# 19. Browser egress security

ADR-0014:

```text
Browser Worker/session child
(no direct Internet route)
→ explicit forward proxy/gateway
→ public Internet
```

Gateway denies private/loopback/link-local/reserved/internal/cloud-metadata destinations.

Baseline public ports 80/443.

No direct fallback if proxy unavailable.

Top-level navigation only `http`/`https`.

Application interception is defense in depth, not sole SSRF boundary.

---

# 20. Worker drain/loss

Drain:

1. advertise draining/no new sessions;
2. bounded close children;
3. force terminate remaining after deadline;
4. ensure zero children;
5. worker exits.

Worker generation lost after lease/grace:

```text
live sessions → lost
```

Late stale worker cannot resurrect them.

---

# 21. REST projection

REST exposes rich typed Browser API according `rest-api.md`:

- session lifecycle;
- pages;
- navigation/snapshot/actions;
- events;
- screenshot/rendered content/upload/download artifacts;
- authorized diagnostics.

No raw Playwright API/internal worker endpoint/PID.

---

# 22. MCP projection

Current canonical MCP surface = `mcp.md` + ADR-0022.

Important version invariant:

- tool identity has one stable execution class;
- explicit page IDs;
- no CSS/XPath;
- no stateful `*_many` variants;
- Russian descriptions;
- exact ElementRefs;
- structured errors/hints;
- lifecycle/retry metadata compatible with own Agent Dispatcher.

Version implementation must **not** invent its own tool catalog from old examples.

---

# 23. Observability

Measure:

- worker generations/leases/capacity;
- session subprocess/Chromium process counts;
- launch/action/snapshot latency;
- action outcomes/unknown;
- snapshot size/ref retention;
- dialogs/events;
- artifacts;
- egress denies/proxy failures;
- forced kills;
- expiry/reaper/drain;
- zombie/orphan/temp leak.

---

# 24. Required tests

- owner isolation;
- multi-replica routing;
- generation/lease/self-fencing;
- separate session subprocess/Chromium;
- cookie/storage isolation;
- exact stale-safe refs;
- action serialization/recovery;
- response-loss unknown/no duplicate;
- dialogs;
- Content artifact handoff;
- TTL/reaper;
- forced kill/reap;
- worker crash/drain;
- egress private/internal block/no direct route;
- real-browser soak;
- actual REST OpenAPI;
- actual FastMCP schemas according current `mcp.md`.

---

# 25. Definition of Done

v0.4 complete only if:

1. Browser is separate worker runtime, not request-handler Playwright.
2. Each session owns isolated child + Chromium.
3. Control Plane replicas route by durable worker generation, not local RAM.
4. Worker partition self-fences.
5. Element refs exact/stale-safe.
6. Mutating response loss never blindly duplicates action.
7. `unknown` supported end-to-end.
8. Browser artifacts use Content boundary.
9. Egress cannot reach private/internal network.
10. Server TTL cleans without client/MCP connection.
11. Forced cleanup kills child tree and soak leaves no zombies/leaks.
12. REST is rich while MCP follows compact canonical catalog.
13. Applicable Browser/security/race/soak/schema release gates are green.
