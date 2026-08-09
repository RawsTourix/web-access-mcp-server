# v0.4 — Managed Browser Runtime

## Статус

`design in progress`

Версия добавляет полноценный stateful Browser Runtime поверх уже готового Content boundary.

---

# 1. Цель

После v0.4 агент/REST client должен уметь:

```text
create BrowserSession
→ navigate
→ snapshot
→ typed interactions
→ tabs/popups
→ rendered content/screenshots/downloads
→ explicit close
```

с:

- отдельным Browser Worker runtime;
- session ownership;
- process isolation;
- exact element refs;
- action dedup/status recovery;
- unknown-outcome semantics;
- TTL/reaper;
- multi-replica routing;
- Content integration.

---

# 2. Prerequisites

- accepted v0.1;
- accepted v0.3 Content Core;
- `../../browser.md`;
- `../../resource-model.md`;
- `../../security.md`;
- `../../runtime-topology.md`;
- `../../rest-api.md`;
- `../../mcp.md`;
- `../../deployment.md`;
- `../../testing.md`;
- ADR-0001 direct Browser Worker RPC;
- ADR-0002 auth baseline;
- ADR-0009 worker registry/lease;
- ADR-0010 snapshot/element refs;
- ADR-0011 dialog policy;
- ADR-0012 process-per-session.

---

# 3. Scope

## Browser Worker

- separate runtime/image;
- Playwright Python + Chromium;
- one Chromium process per BrowserSession;
- ephemeral non-persistent BrowserContext;
- session/page registry;
- snapshot ref maps;
- action queue/ledger;
- browser events;
- temp artifacts;
- internal HTTP/RPC.

## Control Plane

- BrowserSession repository/application lifecycle;
- worker registration/heartbeat;
- Redis registry/routing cache;
- placement;
- direct worker client;
- reaper/reconciler;
- Content artifact ingest;
- REST/MCP facades.

---

# 4. Explicit non-goals

- persistent browser profiles/cookies;
- login credential vault;
- arbitrary JS evaluate;
- CSS/XPath ordinary agent tools;
- stealth/fingerprint evasion;
- CAPTCHA bypass;
- proxy rotation;
- durable browser workflows;
- live BrowserContext migration between workers;
- automatic Browser fallback from Retrieval;
- DOM mutation with service ref attributes;
- screenshot/OCR vision reasoning inside service.

---

# 5. BrowserSession SQL direction

v0.4 introduces `browser_sessions` durable metadata table.

Minimum fields:

```text
id
session_id
owner_principal_id
state
revision
worker_id | null
worker_generation | null
browser_profile_id
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

Live pages/snapshots/actions are **not PostgreSQL resources** baseline.

---

# 6. BrowserSession lifecycle

```text
creating
→ ready
→ closing
→ closed
```

Alternative terminal:

```text
creating/ready → failed
ready/closing → lost
ready → expired
```

Lost terminal resources do not resurrect.

---

# 7. Worker model

- worker_id + generation;
- registration/heartbeat via Control Plane;
- Redis registry;
- self-fencing after lease loss;
- no new sessions while draining;
- no direct DB/Redis/ContentStore credentials baseline;
- per-generation internal RPC credential.

---

# 8. Session process model

По ADR-0012:

```text
1 BrowserSession
→ 1 Chromium process
→ 1 BrowserContext
→ N Pages
```

Initial page blank.

---

# 9. Session capacity defaults

Initial operational defaults:

```text
max_sessions_per_worker = 4
max_pages_per_session = 8
max_pending_actions_per_session = 16
```

Configurable after load tests.

Hard capacity prevents OOM before autoscaling.

---

# 10. Session lifetime defaults

Initial:

```text
idle TTL = 5 minutes
maximum lifetime = 30 minutes
creating timeout = 30 seconds
closing grace = 10 seconds
```

Configurable within hard server ceilings.

Client cannot create infinite session baseline.

---

# 11. Page IDs

Worker-generated opaque:

```text
pg_<uuid4hex>
```

Page ID scoped to BrowserSession.

Popup/new tab получает новый page_id immediately on event.

---

# 12. Snapshot IDs / ElementRefs / Action IDs

```text
snapshot_id = snp_<uuid4hex>
element_ref = el_<uuid4hex>
action_id   = act_<uuid4hex>
artifact_id = bart_<uuid4hex>   internal only
```

IDs opaque.

---

# 13. Snapshot model

По ADR-0010:

- ARIA semantic representation;
- actionable element inventory;
- snapshot-scoped refs;
- short-lived ElementHandle identity anchors;
- Locator action execution;
- no selector exposed.

Initial snapshot retention:

```text
3/page
5 minutes
300 refs/snapshot
```

---

# 14. Browser events

Bounded session event buffer captures:

```text
console
network request/response metadata
page created/closed/navigation
popup
dialog
download
browser/page error
```

No network response bodies baseline.

Sequence cursor monotonic per session.

---

# 15. Browser event limits

Initial:

```text
max events/session buffer = 1000
max serialized event bytes/session ≈ 1 MiB target
MCP browser_events limit = 1..200, default 50
```

When buffer evicts old events, result exposes earliest/current sequence so client can detect gap.

---

# 16. Action ledger

Per session stores recent actions:

```text
action_id
payload hash
type/status
started/completed timestamps
terminal result summary
```

Initial bounds:

```text
max ledger entries/session = 128
terminal action retention = 10 minutes or session close
```

Duplicate action_id + same payload returns existing status/result.

Same action_id + different payload rejected `action_id_conflict`.

---

# 17. Internal RPC

Control Plane ↔ Browser Worker follows ADR-0001.

Worker internal operations include:

- create/get/close session;
- execute/get/cancel action;
- fetch temporary artifact;
- health/capacity.

Exact paths fixed in implementation-sequence.

---

# 18. Browser Profiles

BrowserProfile is operator-configured allowlisted profile.

Baseline has:

```text
default
```

Profile may define:

- locale;
- timezone;
- viewport;
- color scheme;
- user agent policy;
- JS enabled baseline;
- permissions default deny.

MCP `browser_create` baseline uses configured default profile and exposes no knobs.

REST may accept approved `profile_id`.

---

# 19. Navigation

`browser_navigate` supports semantic destinations:

```text
url
back
forward
reload
```

URL проходит Browser egress policy.

Navigation increments page generation when document replaced.

---

# 20. Dialogs

По ADR-0011:

- default dismiss-and-report;
- explicit optional per-action accept;
- no pending dialog resource;
- async dialogs outside action auto-dismiss;
- max dialogs/action bounded.

---

# 21. Browser content

`browser_content`:

```text
page.content()/rendered HTML
→ worker temp artifact
→ Control Plane Content ingest(native)
→ raw HTML + derived representations
```

No direct giant HTML MCP result.

Initial rendered HTML artifact ceiling:

```text
32 MiB
```

Configurable bounded.

---

# 22. Screenshot

Screenshot explicit.

Baseline formats:

```text
png
jpeg
```

Modes:

- viewport page;
- full_page;
- specific element_ref.

JPEG quality bounded optional.

Result ContentRef.

---

# 23. Downloads

Download is event/result of action/navigation.

Worker stores temp download, returns internal artifact handle, Control Plane persists ContentObject.

No separate `browser_download` core tool.

---

# 24. Uploads

Input:

```text
ContentRef + element_ref
```

Control Plane authenticates Content owner and streams to worker internal temp artifact/upload endpoint.

Worker never receives filesystem path from agent.

---

# 25. Required MCP tools v0.4

Core:

```text
browser_create
browser_close
browser_navigate
browser_snapshot
browser_content
browser_tabs
browser_screenshot
browser_events
browser_click
browser_fill_form
browser_type
browser_press
browser_hover
browser_drag
browser_wait
browser_upload
```

Exact schemas in implementation-sequence.

---

# 26. Required REST

REST exposes session/page/snapshot/action lifecycle from `rest-api.md`.

No raw Playwright RPC/evaluate.

---

# 27. Required gates

- G0–G6;
- G10 Browser;
- G12–G17;
- G18 Browser load baseline;
- G19 Browser soak/leak;
- G20 own-agent integration;
- G21 docs consistency.

---

# 28. Acceptance criteria

1. Browser Worker separate runtime.
2. One BrowserSession one Chromium process.
3. API replicas route to owning worker without sticky client session.
4. Worker restart changes generation and old sessions do not resurrect.
5. Redis loss/re-registration path works.
6. Worker partition self-fences.
7. BrowserSession TTL/reaper works.
8. Actions serialized per session.
9. Duplicate action does not double-execute.
10. Response loss uses action status; mutating uncertainty returns unknown.
11. Snapshot refs resolve exact same DOM node or stale.
12. Locator actionability retained.
13. Dialog default safe and explicit accept works.
14. Popup/tabs managed with page IDs.
15. Screenshot/rendered content/download persist through Content boundary.
16. Upload uses ContentRef.
17. Browser events bounded/redacted.
18. Browser private/internal egress blocked.
19. No persistent profile/evaluate/CSS-XPath baseline.
20. Real Chromium race/fault/load/soak gates green.
21. MCP Browser tools integrate with builtin agent remote-resource cleanup contract.

---

# 29. Remaining blockers

Перед `ready for implementation` нужен `implementation-sequence.md`, фиксирующий:

- exact browser SQL indexes/lease queries;
- Redis registry serialization;
- internal RPC endpoints/envelopes/auth token derivation;
- worker process/temp implementation;
- BrowserProfile defaults/config schema;
- exact snapshot/action schemas;
- exact wait/dialog fields;
- artifact transfer protocol;
- MCP hard limits/descriptions;
- REST action schemas;
- test site scenarios.
