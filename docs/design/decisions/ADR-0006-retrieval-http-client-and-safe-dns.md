# ADR-0006 — Retrieval transport: aiohttp + validating resolver, HTTPX remains provider client

**Статус:** accepted

## 1. Контекст

Retrieval принимает произвольные HTTP(S) URL от клиента и поэтому является SSRF boundary.

Недостаточно выполнить:

```text
DNS resolve
→ проверить IP
→ вызвать обычный HTTP client по hostname
```

если HTTP client затем самостоятельно выполняет **второй DNS resolve** перед connect. Между двумя resolution результат может измениться (DNS rebinding / TOCTOU).

Изначальная концепция предполагала HTTPX для всех HTTP clients. При детальном проектировании выяснилось, что HTTPX high-level transport API не предоставляет first-class custom DNS resolver hook; безопасная pinning реализация потребовала бы собственного низкоуровневого transport поверх httpcore/network backend и сильнее связала бы Retrieval с внутренними деталями HTTPX stack.

Для configured trusted provider endpoints (SearXNG/Yandex) такой arbitrary-URL SSRF threat отсутствует, поэтому HTTPX остаётся хорошим provider client.

---

## 2. Требования Retrieval transport

SafeHttpFetcher должен:

1. принимать только `http`/`https`;
2. валидировать IP literals;
3. разрешать hostname через контролируемый resolver;
4. проверять **те адреса, к которым реально будет подключён socket**;
5. сохранять original hostname для Host/TLS SNI/certificate validation;
6. отклонять private/link-local/loopback/special/internal targets;
7. вручную проверять каждый redirect;
8. не использовать environment HTTP proxy автоматически;
9. поддерживать connection pooling;
10. streaming response;
11. TLS verify;
12. cancellation/deadlines;
13. bounded DNS/connect/read behavior;
14. не зависеть от private API library без необходимости.

---

## 3. Рассмотренные варианты

### A. HTTPX + pre-resolve validation + обычный AsyncClient

Отклонён: второй DNS resolve клиента создаёт TOCTOU/rebinding окно.

### B. HTTPX + собственный AsyncBaseTransport/httpcore network backend

Технически возможно и сохраняет одну HTTP library, но требует существенно более низкоуровневой integration с httpcore transport/network backend и повышает maintenance risk при обновлении HTTPX/httpcore.

### C. aiohttp + `TCPConnector` с custom `AbstractResolver`

aiohttp предоставляет публичный resolver extension point: Connector использует адреса, возвращённые resolver, для actual connection, сохраняя original host для HTTP/TLS semantics.

### D. Отдельный network proxy/sandbox service

Сильная security boundary, но слишком тяжёлая обязательная инфраструктура для базового Retrieval. Network-level egress всё равно используется defense-in-depth.

---

## 4. Решение

Для **arbitrary URL Retrieval** использовать:

```text
aiohttp ClientSession
+
TCPConnector(custom validating resolver)
+
manual redirect loop
+
trust_env = false
```

Для configured upstream integrations оставить:

```text
HTTPX
```

То есть проект осознанно использует два HTTP client stack по разным security responsibilities.

---

## 5. Почему два клиента лучше одного abstraction leak

HTTPX остаётся удобным для:

- SearXNG;
- Yandex;
- других configured providers/internal APIs.

aiohttp используется только там, где arbitrary-host DNS/connect control является core security requirement.

Application layer всё равно видит ports:

```text
SearchProvider
SafeHttpFetcher
```

и не знает concrete libraries.

Следовательно использование двух libraries не дублирует business logic.

---

## 6. SafeResolver

Реализовать собственный resolver adapter поверх публичного aiohttp resolver interface.

Conceptual flow:

```text
normalize hostname
→ resolve A/AAAA через system/async resolver
→ получить полный набор addresses
→ validate every address
→ если любой address forbidden/ambiguous по policy → reject resolution
→ вернуть connector только validated public addresses
```

Почему reject весь mixed result:

```text
public + private addresses
```

не должен позволять connector случайно выбрать private target.

---

## 7. Actual connect uses validated addresses

Ключевой invariant:

> После SafeResolver не должно происходить независимого повторного DNS resolution hostname перед TCP connect.

Contract/integration test должен доказывать это через resolver fixture, возвращающий разные результаты при повторном resolve.

Если будущая aiohttp version меняет эту guarantee, dependency upgrade blocked до re-review ADR/security tests.

---

## 8. Original hostname сохраняется

Несмотря на connect к validated IP, HTTPS должен использовать original hostname для:

- SNI;
- certificate hostname verification;
- HTTP Host header.

Нельзя заменять request URL на `https://<resolved-ip>/...` и случайно ломать TLS/virtual hosting.

---

## 9. IP policy

IP validation использует explicit policy поверх Python `ipaddress` + regression corpus special ranges.

Baseline deny:

- loopback;
- private;
- link-local;
- multicast;
- unspecified;
- reserved/special-use;
- carrier-grade/shared ranges, которые не считаются обычным public internet;
- IPv4-mapped IPv6, если mapped address forbidden;
- IPv6 scoped/zone identifiers;
- deployment configured internal CIDRs.

Предпочтительная baseline semantics:

```text
allow only addresses classified as globally routable public by policy
```

с explicit tests, а не длинным непроверенным handwritten list единственным источником.

---

## 10. IP literals

URL с literal IP проходит ту же policy **до connector**.

Private literal rejected без DNS.

Alternative textual IP forms должны нормализоваться стандартным URL/IP parser или rejected как ambiguous.

Не писать собственный parser decimal/octal/hex IPv4.

---

## 11. Hostname normalization

Использовать стандартное IDNA normalization/library behavior, совместимое с HTTP client.

Нужно сохранять:

- user-provided requested URL для provenance;
- normalized hostname для policy;
- final URL после redirects.

Control characters/invalid Unicode/ambiguous host rejected.

---

## 12. Credentials/userinfo

URL form:

```text
https://user:password@example.com/
```

не входит canonical Retrieval.

Userinfo rejected, а не silently forwarded.

---

## 13. Ports

Baseline egress policy разрешает:

```text
http: 80
https: 443
```

Operator может добавить explicit public destination ports через SecuritySettings allowlist.

Client/LLM не расширяет allowlist per request.

Custom public ports useful для controlled deployments, но не являются default internet-scanning capability.

---

## 14. DNS cache

Baseline SafeResolver/Connector не должен использовать длительный unchecked DNS cache.

Допустим short cache только для **уже validated address records**, если:

- TTL bounded;
- cache entry содержит validated IPs;
- connect uses those cached IPs без re-resolve;
- security policy/config revision invalidates cache.

Первая implementation может использовать `use_dns_cache=False` ради простоты/correctness и полагаться на connection pool; performance измеряется позже.

---

## 15. Redirects

aiohttp automatic redirects отключаются:

```text
allow_redirects = false
```

RetrievalApplication/SafeHttpFetcher выполняет explicit loop:

```text
response 3xx
→ parse Location
→ resolve relative URL
→ full URL/security validation
→ новый request
```

Каждый hostname получает новый SafeResolver decision.

---

## 16. Proxy environment

ClientSession создаётся с:

```text
trust_env = false
```

чтобы `HTTP_PROXY`/`HTTPS_PROXY` на host/container не перенаправил arbitrary Retrieval через proxy с иным network access и не обошёл SafeResolver assumptions.

Если deployment когда-либо требует explicit egress proxy, это отдельный ADR/security mode с trusted proxy contract.

---

## 17. TLS

TLS verification обязательна.

Caller не имеет `verify=false`.

Custom CA допускается только operator/deployment configuration.

Original hostname проверяется сертификатом.

---

## 18. HTTP protocol trade-off

aiohttp baseline ориентирован на надёжный HTTP/1.1 arbitrary Retrieval.

Web Access не обещает HTTP/2 как public capability.

Если отсутствие HTTP/2 реально создаст compatibility/performance проблему для meaningful websites, transport может быть пересмотрен отдельным ADR.

Security/connect correctness имеет приоритет над единообразием libraries.

---

## 19. Connection pooling

Один long-lived ClientSession/Connector на Control Plane runtime/profile.

Pool bounded:

- total connections;
- per-host connections;
- keepalive;
- DNS policy compatible.

Не создаётся новая ClientSession на каждый URL.

---

## 20. Network-level defense

Даже validated resolver не является единственной защитой.

Production Browser/Retrieval egress policy/firewall должен запрещать internal ranges/network services.

Это защищает от:

- library bug;
- resolver bug;
- proxy/config drift;
- future parser bypass.

---

## 21. Tests

Обязательны:

1. hostname resolving only public → allowed;
2. only private → rejected;
3. mixed public/private → rejected;
4. resolver first call public, second private → доказать, что actual request не делает второй uncontrolled resolve;
5. public redirect → private hostname → rejected;
6. public redirect → private IP literal → rejected;
7. IPv4-mapped IPv6 private → rejected;
8. localhost names/IPs;
9. custom forbidden port;
10. allowed configured public custom port;
11. TLS original hostname semantics;
12. `trust_env=false` with malicious proxy env set;
13. connector reuse;
14. cancellation/timeout;
15. dependency upgrade regression.

---

## 22. Consequences

Плюсы:

- DNS/connect TOCTOU закрывается на client architecture level;
- используется public resolver extension point;
- redirects контролируются;
- proxy bypass предотвращён;
- provider clients остаются простыми HTTPX adapters;
- application contract не меняется.

Минусы:

- две HTTP libraries в dependency tree;
- нужно поддерживать SafeResolver/connector security tests;
- HTTP/2 arbitrary Retrieval baseline отсутствует;
- часть общих HTTP observability helpers придётся адаптировать к двум clients.

Trade-off принимается ради security/maintainability arbitrary URL boundary.

---

## 23. Затронутые документы

Этот ADR уточняет/заменяет предварительное упоминание «HTTPX для Retrieval» в concept/design как implementation detail.

Канонически:

```text
Retrieval arbitrary URL → aiohttp SafeHttpFetcher
Configured provider HTTP → HTTPX
```

При следующем consistency patch concept/technology tables должны быть обновлены.
