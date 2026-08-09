# v0.4 — Managed Browser Runtime

## Статус

`ready for implementation`

Version добавляет полноценную stateful Browser capability поверх accepted v0.1 Foundation и v0.3 Retrieval/Content Core.

Implementation order: `implementation-sequence.md`.

---

# 1. Цель

После v0.4 backend/REST/MCP поддерживают explicit workflow:

```text
create BrowserSession
→ explicit navigation
→ semantic snapshot / ElementRefs
→ typed interactions / scroll / wait
→ pages/popups/dialogs
→ screenshot/rendered Content/download/upload
→ explicit close or server expiry
```

с:

- multi-replica Control Plane routing;
- separate Browser Worker supervisor;
- one session subprocess + dedicated Chromium per BrowserSession;
- session action serialization;
- exact stale-safe refs;
- action result recovery/`unknown`;
- Content artifact boundary;
- TTL/reaper/drain;
- self-fencing worker lease;
- public-only egress gateway.

---

# 2. Canonical design/contracts

Semantic:

- `../../browser.md`;
- `../../resource-model.md`;
- `../../security.md`;
- `../../runtime-topology.md`;
- `../../rest-api.md`;
- `../../mcp.md`.

Exact facade:

- `../../contracts/browser-api-v1.md`;
- Browser subset `../../contracts/mcp-tools.md`;
- `../../contracts/common-models.md`.

ADR:

```text
0001 direct Browser Worker RPC
0009 worker registry/lease/fencing
0010 snapshot/ElementRef
0011 dialog policy
0012 dedicated Chromium invariant (partially superseded)
0013 session subprocess ownership/kill boundary
0014 browser egress gateway
0024 resource/side-effect-aware retry
0025 explicit scroll
```

При conflict ADR-0012 process ownership с ADR-0013 приоритет ADR-0013.

---

# 3. Non-goals

- persistent browser profiles/cookies across sessions;
- credential vault/autologin;
- arbitrary JS evaluate;
- CSS/XPath ordinary MCP targeting;
- raw Playwright/CDP public API;
- CAPTCHA/stealth/fingerprint bypass;
- client-supplied proxy rotation;
- durable browser workflow;
- live session migration;
- automatic Retrieval→Browser fallback;
- OCR/VLM visual reasoning;
- shared Chromium pool optimization;
- remote desktop.

---

# 4. Runtime ownership

```text
Control Plane replicas
        │ authenticated direct internal RPC
        ▼
Browser Worker supervisor
        │
        ├── session child A → Playwright → Chromium A
        └── session child B → Playwright → Chromium B

Chromium
→ controlled Browser Egress Gateway
→ public Internet
```

BrowserSession metadata durable in PostgreSQL; Pages/snapshots/ElementRefs live in owning session child.

Redis only worker registry/route cache/coordination.

---

# 5. BrowserSession lifecycle

```text
creating → ready → closing → closed
creating → failed
ready/closing → lost
ready → expired
```

No automatic resurrection/migration.

MCP/HTTP connection close does not close BrowserSession.

---

# 6. Worker generation/lease

PostgreSQL stores authoritative:

```text
worker_id
worker_generation
```

Worker heartbeat/lease/self-fencing follows ADR-0009.

Reference direction:

```text
heartbeat ~5 s
lease ~20 s
final loss grace ~30 s
```

validated/configurable.

Stale generation cannot accept/revive work.

---

# 7. Session process boundary

```text
1 BrowserSession
→ 1 Python session subprocess
→ 1 Playwright runtime
→ 1 Chromium
→ 1 non-persistent context
→ <= bounded Pages
```

Child has no DB/Redis/provider/ContentStore/external auth credentials.

Supervisor can cooperative-close, terminate, hard-kill/reap entire session process tree without private Playwright PID hacks.

---

# 8. Initial capacity/lifetime direction

```text
max sessions/worker = 4
max pages/session = 8
max pending actions/session = 16
idle TTL = 5 min
max lifetime = 30 min
create timeout = 30 s
close graceful deadline = 10 s
```

Tunable from measurements within hard ceilings.

---

# 9. Page identity/state

Each page/popup gets opaque PageId.

Initial blank page created with session.

No hidden active-tab requirement in public facade; actions use explicit `page_id`.

Closing final remaining page rejected; whole session closes via session operation.

`page_generation` invalidates old snapshot refs after document replacement/navigation.

---

# 10. Action lane/recovery

One logical serialized action lane per BrowserSession.

Different sessions parallel.

Internal `action_id` + ledger/status recovery:

```text
response lost
→ query same action ID
→ known terminal → recover result
→ running → same execution
→ impossible to prove after possible side effect → unknown
```

Never blind retry a new stateful action call.

---

# 11. Snapshot/ElementRef

Bounded semantic/ARIA-oriented snapshot:

```text
snapshot_id
page_generation
semantic view
element_refs <= bounded count
optional ContentRef for externalized large view
```

ADR-0010 exact target identity:

```text
ref
→ private locator recipe + original ElementHandle
→ re-resolve Locator exactly
→ DOM identity comparison
→ actionability
```

Replacement node = `stale_target`; no fuzzy retargeting.

Baseline:

```text
3 snapshots/page
ref TTL 5 min
300 refs/snapshot
MCP inline 30k chars
REST inline 100k chars
backend generation hard 256k chars
```

---

# 12. Browser interaction surface

Backend supports typed:

```text
navigate
page list/create/close
snapshot
click
fill form
type
structured key press
hover
drag
scroll
wait
screenshot
rendered content
events
download artifacts
multi-file upload from ContentRefs
```

Important exact semantics:

- fill form sequential fail-fast, later fields `not_attempted`;
- select/check/radio encoded as typed form values, not separate MCP aliases;
- press uses structured key+modifiers;
- scroll is explicit viewport-relative action, optional scrollable ElementRef;
- scroll never auto-snapshot;
- no arbitrary selectors/coordinates/JS;
- upload supports multiple ContentRefs only when target control supports multiple.

---

# 13. Dialogs

Default:

```text
dismiss + report
```

Per action explicit accept/dismiss where schema supports it.

Prompt text only accept.

Unexpected async dialog auto-dismissed/recorded.

Bounded dialogs/action.

---

# 14. Artifacts/Content

Browser generated:

```text
screenshot
rendered HTML/content
download
```

flows through Content lifecycle before durable handoff.

Upload reverse flow:

```text
owner-authorized ContentRefs
→ bounded session-private materialization
→ file input
```

No host path, no ContentStore credentials child-side.

Finalized Content survives BrowserSession close.

---

# 15. Browser egress

Website traffic:

```text
session child/Chromium
(no direct Internet route)
→ forward proxy/gateway
→ public Internet
```

Gateway denies loopback/private/link-local/reserved/internal/metadata destinations.

No direct fallback if gateway unavailable.

Top-level URL HTTP(S) only.

---

# 16. Public facades

REST exact owner:

```text
../../contracts/browser-api-v1.md
```

MCP semantic/exact owners:

```text
../../mcp.md
../../contracts/mcp-tools.md
```

Current overall MCP freeze candidate = 28 tools; v0.4 implements only Browser subset.

Version docs do not invent alternate public catalog.

---

# 17. Retry/resource semantics

ADR-0024 applies.

Pure observations such as snapshot/events/status can be safe reads.

Artifact/resource-producing operations such as rendered Content/screenshot are not blind replay safe after uncertain response merely because target website was not mutated.

Stateful interactions/navigation/scroll/upload are never automatic retry after dispatch uncertainty.

---

# 18. Required evidence

At minimum:

- owner isolation;
- multi-replica route/generation/lease;
- session subprocess/dedicated Chromium;
- cookie/storage isolation;
- exact stale refs;
- serial actions/recovery/unknown;
- scroll + lazy/infinite fixture;
- form fail-fast;
- structured press;
- multi-upload;
- dialogs;
- artifact Content handoff;
- TTL/reaper/forced kill/drain;
- private/internal egress block;
- no direct browser Internet route;
- response-loss no duplicate side effects;
- real-browser soak/leak;
- exact Browser OpenAPI;
- actual Browser FastMCP schemas.

---

# 19. Definition of Done

v0.4 complete only if:

1. Browser is separate worker/session-process runtime, not request-handler Playwright.
2. Durable owner/generation routing works across Control Plane replicas.
3. Worker partition self-fences.
4. ElementRefs exact/stale-safe.
5. Mutating response loss never blindly duplicates action.
6. `unknown` supported end-to-end.
7. Scroll explicitly enables bounded/lazy-page exploration.
8. Form/key/upload semantics match exact contracts.
9. Browser artifacts use Content boundary.
10. Egress cannot reach private/internal network.
11. Server TTL cleans without MCP connection.
12. Forced cleanup leaves no orphan Chromium/temp/ref leaks.
13. REST/MCP actual schemas match exact contracts.
14. Applicable Browser/security/race/soak/load gates green.
