# ADR-0014 — Browser egress: isolated worker network + public-only forward proxy

**Статус:** accepted

## 1. Контекст

Browser Worker должен одновременно:

- общаться с Control Plane по internal RPC;
- позволять Chromium открывать недоверенные public websites;
- не давать page JavaScript прямой доступ к PostgreSQL/Redis/SearXNG/internal network/host LAN/cloud metadata.

Одного application-level `page.route()` недостаточно как security boundary: Chromium имеет собственный network stack, service workers/WebSockets/другие механизмы, а page-level interception может измениться между версиями Playwright/Chromium.

В то же время Browser Worker supervisor должен иметь internal network до Control Plane, поэтому простой «контейнер вообще без внутренней сети» невозможен.

---

## 2. Решение

Reference deployment использует **browser egress gateway/forward proxy**.

Topology:

```text
                     internal browser-control network

Control Plane  <──────────>  Browser Worker
                              │
                              │ Chromium explicit proxy
                              ▼
                       Browser Egress Proxy
                              │
                              │ separate internet-egress network
                              ▼
                         Public Internet
```

Browser Worker не имеет direct Internet route baseline.

Egress Proxy имеет:

- internal interface к Browser Worker;
- external Internet egress;
- **нет** доступа к PostgreSQL/Redis/SearXNG service networks;
- destination ACL public-only.

---

## 3. Reference proxy implementation

Reference Docker Compose использует version-pinned **Squid forward proxy** либо совместимый mature forward-proxy implementation, если implementation review обнаружит более подходящий maintained image.

Canonical requirement не зависит от бренда proxy:

> proxy должен resolve destination и deny private/special/internal address ranges перед connection.

Если конкретный Squid image/config не способен доказуемо выполнить policy, implementation blocked до выбора другого egress gateway.

---

## 4. Browser Worker network

Compose Browser Worker подключён только к:

```text
browser-control (internal=true)
```

где находятся:

- Control Plane internal interface;
- Browser Egress Proxy internal interface.

Worker **не подключён** напрямую к обычной internet-enabled default network.

---

## 5. Egress Proxy networks

Proxy подключён к:

```text
browser-control (internal)
browser-egress (internet-enabled)
```

`browser-egress` не содержит PostgreSQL/Redis/API service aliases кроме самого proxy.

---

## 6. Destination policy

Proxy default-deny для destination, который:

- loopback;
- RFC1918/private;
- link-local;
- multicast;
- unspecified;
- reserved/special use;
- carrier-grade/shared range according policy;
- cloud metadata/link-local;
- deployment-configured internal CIDRs.

Разрешены public globally routable destinations на approved ports.

Baseline ports:

```text
80
443
```

Operator может расширить allowlist.

---

## 7. DNS rebinding

Destination ACL должна применяться к **фактически разрешённому proxy destination IP**, а не только hostname text.

Mixed public/private DNS result должен fail closed, если proxy implementation позволяет соответствующую policy.

Required tests используют controlled DNS/target environment и подтверждают, что hostname не может заставить proxy подключиться к private IP после rebinding.

---

## 8. Chromium proxy config

BrowserSession launch profile задаёт explicit proxy:

```text
http://browser-egress-proxy:<port>
```

Client/LLM не выбирает proxy URL.

Proxy bypass list должен быть пустым/максимально закрытым; implicit localhost bypass отключается по поддерживаемому Chromium/Playwright mechanism locked version.

Exact flag/API проверяется real-browser integration test.

---

## 9. Direct network bypass

Даже если Chromium попытается direct external connection вне proxy:

```text
Browser Worker internal network
→ не имеет public Internet route
```

и connection не должна succeed.

Это ключевой defense-in-depth invariant.

---

## 10. Internal Control Plane reachability

Browser session subprocess технически находится в том же container network namespace и может адресовать Control Plane internal host.

Protection:

1. Chromium explicit proxy должен отправлять web requests через proxy без internal bypass.
2. Control Plane internal endpoints требуют service authentication.
3. Browser session subprocess **не получает internal service credentials**.
4. Browser-control network не содержит PostgreSQL/Redis/другие sensitive services.
5. Application-level Browser URL/subresource policy дополнительно blocks obvious internal destinations.

Это не заменяет proxy policy, но уменьшает impact потенциального browser bypass.

---

## 11. WebSockets

WebSocket connections должны идти через configured HTTP proxy/CONNECT path согласно Chromium behavior.

Integration test:

- public WebSocket works;
- private/internal WebSocket blocked.

Если Chromium version имеет bypass path, deployment must disable/block его до release.

---

## 12. QUIC/UDP

Browser baseline не требует QUIC.

Chromium QUIC/direct UDP paths должны быть disabled/blocked where needed so they cannot bypass HTTP egress proxy.

Network namespace без direct public route является final backstop.

Exact launch policies/flags version-tested.

---

## 13. WebRTC

Web Access v0.4 не обещает peer-to-peer WebRTC capability.

Direct/non-proxied UDP/IP-discovery paths должны быть disabled/restricted by Chromium policy/launch configuration to avoid internal IP exposure/egress bypass.

Sites requiring unrestricted WebRTC may not fully function baseline; this is accepted security trade-off.

---

## 14. DNS prefetch

Chromium DNS prefetch/speculation может существовать, но Browser Worker network не должен предоставлять direct route к public/private target независимо от proxy.

Optional Chromium privacy/performance settings могут disable unnecessary prefetch; correctness не должна зависеть только от них.

---

## 15. Proxy authentication

Browser Egress Proxy находится в isolated internal network and may use network-level trust from Browser Worker interface.

Если proxy supports service auth conveniently, scoped credential can be added, but **page content must not learn reusable proxy credentials**.

No client-supplied proxy credentials.

---

## 16. HTTPS

Baseline proxy использует CONNECT tunneling без TLS interception/MITM.

Website TLS remains end-to-end Chromium ↔ target.

Web Access не устанавливает собственный CA в BrowserSession для normal browsing.

---

## 17. Browser request interception — secondary control

Browser session runtime дополнительно проверяет navigation/request URLs where Playwright gives reliable interception hooks:

- explicit top-level navigation policy;
- obvious private IP/forbidden schemes;
- download/navigation constraints;
- diagnostic blocked event.

Но это **secondary application policy**, не единственный SSRF barrier.

---

## 18. Allowed schemes

Top-level `browser_navigate` baseline разрешает:

```text
http
https
```

Internal page subresources follow browser/proxy policy.

Explicit agent navigation к:

```text
file:
data:
javascript:
chrome:
about:
```

rejected baseline, кроме internal blank page lifecycle (`about:blank`) controlled server-side.

---

## 19. Production deployment

На Kubernetes/cloud вместо Squid sidecar/service может использоваться organisation egress gateway/network policy, если он обеспечивает те же invariants:

- Browser pod direct egress denied;
- only egress gateway allowed;
- gateway public-only destination ACL;
- internal/private denied;
- WebSocket/HTTPS supported;
- auditable logs/metrics without sensitive URL leakage beyond policy.

Public application contracts не меняются.

---

## 20. Local developer deployment

Reference Compose поднимает egress proxy автоматически вместе с Browser capability.

Developer не обязан вручную настраивать system proxy.

Browser Worker без egress proxy не считается Browser-ready в normal profile.

Test profile может использовать controlled fake proxy/targets.

---

## 21. Failure semantics

Proxy unavailable:

```text
Browser capability degraded/unavailable
```

Existing session network action returns normalized upstream/network policy error.

Worker/process remains alive; no automatic direct-network fallback.

---

## 22. Observability

Proxy/application metrics:

- allowed connections;
- denied internal/private destination;
- connection failures;
- bytes/latency aggregate;
- active connections.

Raw full URLs/query strings not metric labels.

Security denial visible in Browser action result/event without exposing proxy internal details.

---

## 23. Tests

Required:

1. public HTTP/HTTPS reachable through proxy;
2. direct public route from Browser Worker unavailable;
3. private IPv4 blocked;
4. loopback blocked;
5. link-local/cloud metadata blocked;
6. IPv6 private/link-local blocked;
7. hostname resolving private blocked;
8. mixed/rebinding fixture blocked;
9. WebSocket public works/private blocked;
10. explicit browser navigation to forbidden scheme rejected;
11. internal API endpoint direct page request cannot authenticate;
12. proxy outage does not trigger direct fallback;
13. Chromium proxy bypass settings verified locked version;
14. Browser subprocess env contains no proxy bypass secret/internal auth token.

---

## 24. Consequences

Плюсы:

- Browser network security не зависит только от Playwright interception;
- Browser Worker no direct Internet route;
- DB/Redis/SearXNG isolated networks;
- consistent public-only egress;
- production egress gateway can replace reference proxy.

Минусы:

- additional service/network hop;
- proxy configuration/security requires own tests/maintenance;
- some WebRTC/QUIC-heavy sites may degrade;
- local Compose becomes more complex.

Trade-off принимается, потому что arbitrary browser Internet access является high-risk boundary.

---

## 25. Не определяется

- exact Squid image/version/config syntax;
- production egress gateway vendor;
- detailed WebRTC policy flags;
- proxy metrics exporter;
- optional proxy auth.

Implementation sequence фиксирует reference Compose configuration после version-specific verification.
