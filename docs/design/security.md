# Security foundation Web Access MCP

## Статус документа

Этот документ является каноническим владельцем **сквозной security model, trust boundaries и обязательных защитных инвариантов** проекта.

Он задаёт security foundation для Search, Retrieval, Content, Browser, Jobs, REST, MCP и deployment.

Точные authentication protocols, network policies, container manifests, limits и capability permissions уточняются последующими design/ADR.

---

# 1. Базовая модель доверия

Web Access должен исходить из того, что недоверенными являются:

- client input;
- URL;
- DNS responses как единственный источник policy decision;
- HTTP responses;
- HTML/JavaScript/CSS;
- search result content/snippets;
- downloads;
- uploaded/referenced files;
- metadata файлов;
- archive/container contents;
- browser-rendered content;
- opaque handle до проверки existence/ownership/policy;
- provider error text;
- web content, передаваемый ИИ-агенту.

Trusted являются только собственные application contracts, validated configuration/policy и server-generated canonical metadata после соответствующей проверки.

---

# 2. Defense in depth

Ни один единственный validation layer не считается достаточной security boundary.

Для критичных областей используются несколько уровней защиты.

Например SSRF:

```text
URL validation
+ DNS/IP policy
+ redirect revalidation
+ actual network egress restrictions
+ service/network isolation
```

Browser isolation:

```text
application policy
+ Browser Worker process boundary
+ non-root execution
+ Chromium sandbox
+ container/seccomp restrictions
+ network egress policy
+ resource limits
```

---

# 3. SSRF является фундаментальной угрозой

Retrieval и Browser по назначению обращаются к произвольным внешним URL, поэтому SSRF protection является обязательной core capability.

Сервис не может использовать простой business allowlist всего интернета, поэтому основной production подход строится на строгой URL normalization, блокировке special/private destinations и network-level egress controls.

---

# 4. Разрешённые URL schemes

По умолчанию public web capabilities принимают только:

```text
http
https
```

Другие schemes (`file:`, `ftp:`, `data:`, `javascript:`, `chrome:`, internal browser schemes и т.п.) не разрешаются через обычный Retrieval/Browser navigation contract без отдельной capability/policy.

User-info/credentials внутри URL должны быть запрещены или обрабатываться отдельным явным security contract, а не неявно.

---

# 5. URL normalization

До security decision URL проходит единый parser/normalizer.

Нельзя строить SSRF policy через регулярное выражение над исходной строкой URL.

Необходимо корректно учитывать:

- IDNA/domain normalization;
- IPv4/IPv6 literal forms;
- IPv4-mapped IPv6;
- percent encoding;
- default/non-default ports;
- userinfo;
- fragments;
- ambiguous parser edge cases.

Один и тот же canonical URL interpretation должен использоваться validation и network layer настолько, насколько это технически возможно.

---

# 6. Запрещённые destination classes

Web-facing policy должна блокировать как минимум destination classes, которые не являются публичным интернетом:

- loopback;
- unspecified;
- private/internal address ranges;
- link-local;
- multicast;
- reserved/special-purpose ranges;
- cloud/container metadata endpoints;
- внутренние service networks deployment-а;
- Kubernetes/Docker/internal control endpoints;
- другие addresses, запрещённые deployment egress policy.

Точный набор должен формироваться на основании актуальных IANA/platform registries и deployment policy, а не только одной статической строки CIDR в application code.

---

# 7. DNS validation

Для hostname необходимо проверять все полученные адреса, а не только первый удобный A record.

Нельзя разрешать hostname, если он резолвится в destination, запрещённый policy.

Security design должен учитывать:

- A и AAAA;
- DNS rebinding;
- race между validation resolve и фактическим connect;
- resolver/proxy differences.

Точный safe-connect implementation определяется Retrieval design/ADR.

---

# 8. Redirect revalidation

Redirect не наследует автоматически security approval исходного URL.

Каждый redirect target проходит заново:

```text
parse
→ normalize
→ scheme check
→ destination/DNS policy
→ limits
```

Автоматическое unrestricted `follow_redirects=True` без собственного validation loop запрещено для public Retrieval.

Должен существовать configurable redirect count limit.

---

# 9. Network-level egress protection

Application SSRF checks должны дополняться сетевым запретом доступа к internal/private destinations там, где deployment это позволяет.

Это защищает от:

- parser/resolver bugs;
- DNS race;
- browser subresource requests;
- JavaScript fetch/WebSocket;
- случайной ошибки application validation.

Browser Worker особенно нуждается в отдельной egress policy, потому что страница может инициировать сетевые обращения без отдельного вызова агента.

---

# 10. Proxy-aware security

Если deployment использует HTTP/SOCKS proxy, SSRF policy должна учитывать, кто реально выполняет DNS resolution/connect.

Нельзя считать локальную DNS validation достаточной, если proxy затем разрешает hostname по-другому и имеет доступ к внутренней сети.

Proxy configuration является security-sensitive deployment setting.

---

# 11. Resource limits обязательны до parsing

До чтения/парсинга недоверенного содержимого применяются limits по возможности как можно раньше:

- request/response bytes;
- compressed bytes;
- decompressed bytes;
- read deadline;
- redirect count;
- archive member count;
- archive nesting/decompression expansion;
- document pages;
- image dimensions/pixels;
- parser CPU/time budget;
- browser pages/tabs/session count;
- downloads/uploads.

Точные значения configurable и определяются component/deployment design.

---

# 12. Streaming вместо безусловного buffering

Retrieval не должен сначала без ограничения загружать весь response в RAM, а потом проверять размер.

Содержимое читается streaming/bounded способом.

При превышении policy operation прекращается и возвращает нормализованную error/warning semantics.

---

# 13. Compression и decompression bombs

Ограничение compressed size само по себе недостаточно.

Для gzip/archive/container parsing нужно учитывать потенциальный decompressed size и recursion/nesting.

Native parser не должен без ограничений распаковывать вложенные контейнеры.

---

# 14. File type нельзя определять только по HTTP header/extension

`Content-Type`, filename и URL suffix считаются сигналами, но не единственным source of truth.

Content Inspection использует сочетание:

```text
declared media type
+ filename/suffix metadata
+ magic/signature/container inspection
```

Несоответствие должно быть отражено diagnostic/warning и не должно приводить к выполнению неподходящего опасного parser.

---

# 15. Native Parsing не выполняет активный код документа

L1 Native Parsing не должен:

- исполнять macros;
- выполнять embedded scripts;
- автоматически запускать executable content;
- выполнять shell commands;
- обращаться во внешнюю сеть по ссылкам документа без отдельной capability;
- активировать external entities/resources без explicit safe policy.

---

# 16. XML parsing hardened by default

XML-derived formats должны обрабатываться с policy, отключающей опасные внешние entities/DTD/network resolution, если конкретный parser это поддерживает.

Парсер не должен получать произвольный network access через XML entities.

---

# 17. Archive extraction

Если Native Parsing требует чтения ZIP/container structure (например OOXML/EPUB), extraction должна быть virtual/bounded, а не безусловной распаковкой пользовательских paths на filesystem.

Если физическая распаковка нужна:

- target directory создаётся сервисом;
- filenames не определяют host path напрямую;
- path traversal (`../`, absolute paths) запрещён;
- symlink/hardlink semantics контролируются;
- member count/size/depth ограничены;
- cleanup обязателен.

---

# 18. Parser risk profiles

Не все Native Parsers одинаково безопасны по resource/runtime characteristics.

Content design должен позволять классифицировать parser execution profile, например:

```text
inline_bounded
isolated_process
background/durable
unsupported
```

Это не L2 classification: даже L1 parser может требовать process isolation из-за untrusted binary/container format или resource risk.

Точный executor model определяется `content.md` и при необходимости обновляет runtime topology.

---

# 19. API process не должен быть заложником тяжёлого parser

Если конкретный Native Parser способен непредсказуемо потреблять значительные CPU/RAM или использует рискованную native dependency, design должен предусматривать execution isolation вместо безусловного запуска внутри Control Plane process.

Это открытый architecture decision для Content design.

---

# 20. ContentStore не является public webroot

Raw/derived ContentObjects не должны автоматически становиться публично доступными по storage URL.

Доступ осуществляется через application authorization/REST handlers/signed scoped mechanism, если он будет спроектирован.

Local filesystem storage располагается вне webroot и не использует пользовательский filename как physical path.

---

# 21. Filename является metadata

Имя файла из HTTP `Content-Disposition`, URL или upload считается недоверенной metadata.

Physical storage key генерируется сервисом.

Filename:

- нормализуется/ограничивается для отображения;
- не определяет filesystem path;
- не используется как authorization identity;
- не позволяет overwrite чужого resource.

---

# 22. Content serving

При выдаче недоверенного content программному/Web UI клиенту необходимо избегать превращения Web Access origin в execution origin этого content.

Для бинарных/download responses должны использоваться безопасные response headers/presentation policy.

HTML/SVG и другой active content не должен безусловно inline-render-иться в административном UI на доверенном origin.

Точная serving policy определяется REST/Web UI design.

---

# 23. Browser Worker — повышенная trust boundary

Browser Worker исполняет недоверенный JavaScript и обрабатывает внешние сайты.

Он рассматривается как отдельный более рискованный runtime.

Он не должен иметь больше privileges, чем необходимо для browser execution.

---

# 24. Browser Worker запускается non-root

Production Browser Worker не должен запускать Chromium как root с отключённым sandbox без отдельного чрезвычайного обоснования.

Целевое направление:

- отдельный непривилегированный OS user;
- Chromium sandbox enabled;
- подходящий seccomp profile;
- dropped Linux capabilities;
- no privileged container;
- no Docker socket;
- no host PID/network namespace.

Deployment details фиксируются `deployment.md`.

---

# 25. Browser Worker filesystem

Browser Worker получает ограниченное временное filesystem пространство.

Требования:

- отдельные temp/download dirs;
- bounded disk quota;
- cleanup при session close/worker maintenance;
- отсутствие writable mount исходного кода/host home;
- отсутствие доступа к ContentStore credentials шире необходимого contract.

Downloaded content передаётся в Content boundary, а не возвращается как local path.

---

# 26. Browser Worker secrets

Browser Worker не должен иметь provider/database/admin credentials, которые не нужны его функции.

В идеале он получает только:

- scoped service identity для Control Plane communication;
- минимальные credentials к Content transfer, если выбранная architecture требует прямого доступа;
- browser-specific config.

Чем меньше secrets доступны runtime, исполняющему недоверенный JS, тем лучше security boundary.

---

# 27. Internal Browser Worker API аутентифицируется

Browser Worker не должен принимать команды от произвольного клиента только потому, что доступен по internal network.

Control Plane ↔ Browser Worker protocol должен иметь service authentication/integrity protection, соответствующую deployment threat model.

Точная технология (scoped token, mTLS, другое) определяется ADR/deployment design.

---

# 28. Browser navigation policy применяется не только к top-level URL

Browser page может обращаться к:

- subresources;
- XHR/fetch;
- WebSocket;
- redirects;
- iframes;
- workers.

Security не может ограничиться проверкой только аргумента `browser_navigate`.

Нужна combination browser-level request policy и network-level egress controls.

---

# 29. Persistent browser profiles не входят в базовый contract

Ephemeral BrowserSession является default.

Persistent cookies/storage/auth profiles существенно повышают security/privacy требования.

Если они появятся позднее, потребуется отдельный design:

- encrypted storage;
- explicit owner;
- ACL;
- revocation;
- expiration;
- domain scoping;
- secret handling;
- audit.

Нельзя незаметно сохранить пользовательскую авторизацию только потому, что Playwright умеет `storage_state`.

---

# 30. Browser action permissions

Browser capability должна позволять policy разделять как минимум:

- read/navigation actions;
- state-changing interaction;
- file upload/download;
- advanced evaluation/debug capabilities.

Опасные advanced tools не включаются автоматически только ради полноты Playwright API.

---

# 31. Arbitrary code execution не является базовым browser tool

Universal tool вида:

```text
browser_run_code
```

не должен быть доступен обычному MCP principal по умолчанию.

Если low-level JavaScript evaluate понадобится:

- отдельная capability permission;
- строгий contract;
- audit;
- ограничения result/timeout;
- понимание, что это значительно расширяет attack surface.

Shell/Python execution вообще не относится к Browser MCP capability.

---

# 32. Upload в Browser идёт через ContentObject

Browser upload не принимает arbitrary local path клиента/Control Plane.

Предпочтительный flow:

```text
client-owned ContentObject
→ ownership/policy validation
→ bounded staging для Browser Worker
→ upload action
```

Это сохраняет storage/security boundary и multi-node compatibility.

---

# 33. Download из Browser идёт через Content boundary

Download считается недоверенным content.

До завершения BrowserSession нужный download:

- получает bounded handling;
- проходит Content Inspection настолько, насколько требуется policy;
- сохраняется как ContentObject;
- получает ownership/provenance.

Client не получает path Browser Worker.

---

# 34. Prompt injection boundary

Web Access не может гарантировать, что текст внешней страницы не содержит prompt injection для LLM.

Но сервис обязан сохранять структурную границу между:

```text
trusted server metadata/instructions
```

и

```text
untrusted web content
```

Web content не должен иметь возможность подменить:

- `StructuredHint.code`;
- server error code;
- MCP tool description;
- canonical warning;
- policy decision.

---

# 35. Trusted metadata и untrusted content сериализуются раздельно

MCP/REST result должен по возможности структурно отличать:

- extracted page/document content;
- server-generated metadata;
- warnings;
- hints;
- errors.

Нельзя строить response как одну строку, где недоверенный HTML/text и trusted server recommendation визуально неразличимы.

---

# 36. Search snippets недоверенные

Search title/snippet/url являются внешними данными.

Они не должны трактоваться как server instructions и не должны влиять на policy кроме явно определённых normalizations.

---

# 37. Secrets и provider credentials

Secrets не хранятся:

- в source code;
- в public MCP schemas;
- в REST responses;
- в logs;
- в Content metadata;
- в browser-visible environment без необходимости.

Configuration должна поддерживать secret references/environment/deployment secret store.

---

# 38. Logging redaction

Нельзя безусловно логировать:

- Authorization/Cookie headers;
- browser storage;
- query parameters с tokens;
- full request/response bodies;
- uploaded file contents;
- provider secrets;
- internal auth tokens.

URL logging требует redaction policy, поскольку credentials/tokens часто передаются query parameters.

---

# 39. Ownership isolation

Все addressable resources проверяют owner/policy.

Обязательные негативные тесты:

```text
principal A знает content_id principal B
→ access denied

principal A знает browser_session_id principal B
→ access denied

principal A знает job_id principal B
→ access denied
```

Cross-owner deduplication не меняет logical ACL.

---

# 40. Capability quotas и abuse resistance

Architecture должна позволять вводить ограничения по principal/deployment:

- requests/time;
- batch size;
- total retrieved bytes;
- ContentStore quota;
- concurrent BrowserSessions;
- pages per session;
- browser action rate;
- Job count/concurrency;
- provider cost budget;
- download/upload size.

Точные значения не хардкодятся в design без обоснования.

---

# 41. Backpressure является security/availability control

При перегрузке сервис должен контролируемо отклонять/замедлять новую работу, а не принимать бесконечную очередь в RAM.

Capacity error является нормализованным application failure, а не process crash.

Browser capacity особенно должна быть explicit.

---

# 42. Provider isolation

Search provider adapter получает только необходимые credentials/configuration.

Provider error/body не считается trusted application message.

Provider-specific HTTP redirects/content не должны обходить Retrieval security policy, если provider adapter начинает получать secondary URLs/resources.

---

# 43. Supply-chain security

Production build должен использовать воспроизводимые/pinned dependency versions через lock mechanism.

Не рекомендуется runtime dependency вида `@latest`/неограниченный floating package для критичной browser/security infrastructure.

Playwright package и installed browser binaries должны иметь совместимые версии.

Container base images и dependencies обновляются управляемо и тестируются.

---

# 44. Database/Redis network exposure

PostgreSQL и Redis не должны быть публично доступны из интернета.

Доступ ограничивается внутренней service network и минимально необходимыми runtime identities.

Browser Worker не должен автоматически получать unrestricted доступ к этим systems.

---

# 45. CORS/CSRF

REST browser-facing usage требует отдельной CORS/CSRF модели, особенно для будущего Web UI/admin interface.

Нельзя включать wildcard CORS с credentialed access как универсальный default.

Точная policy зависит от authentication design.

MCP transport security проектируется отдельно в соответствии с используемой MCP/auth model.

---

# 46. Authentication и authorization

Точная user/service auth model пока не фиксируется, но design должен поддерживать:

- service-to-service principal;
- будущего user principal;
- capability permissions;
- owner-scoped resources;
- admin/operator permissions;
- revocation/expiration credentials.

Authorization происходит server-side на application/resource boundary.

---

# 47. Error information disclosure

Public error должен быть repairable, но безопасным.

Не возвращаются:

- stack traces;
- SQL;
- Redis keys;
- local paths;
- internal IP/hostnames без необходимости;
- secret config;
- raw provider exception objects.

Полные diagnostics идут в secure logs/traces с correlation ID.

---

# 48. Cleanup как security property

Неочищенные resources могут привести к:

- утечке cookies/browser state;
- заполнению disk/storage;
- повторному доступу к чужим downloads;
- исчерпанию browser capacity.

Поэтому TTL/reaper/retention и cleanup tests являются частью security acceptance, а не только housekeeping.

---

# 49. Security testing — обязательные классы

Минимально должны существовать автоматизированные tests для:

## Retrieval

- localhost/private IP rejection;
- IPv6/private/special ranges;
- redirects public → private;
- hostname resolving to blocked IP;
- DNS rebinding-safe connect design;
- encoded/ambiguous URLs;
- response size/decompression limits.

## Content

- spoofed Content-Type;
- path traversal archive member;
- symlink archive entry;
- decompression bomb limits;
- XML external entity attempts;
- oversized PDF/image/container;
- unsupported format returns safe diagnostics rather than execution.

## Resources

- cross-owner handles;
- expired/closed/lost resource access;
- guessed/invalid handles;
- retention/cleanup races.

## Browser

- navigation to private/internal targets;
- subresource attempts to private/internal network;
- browser worker runs without privileged/root assumptions;
- session isolation;
- download/upload path isolation;
- worker loss cleanup;
- advanced capability permission denial.

## Transport

- schema validation;
- auth failures;
- error redaction;
- untrusted content separated from trusted hint/error metadata.

---

# 50. Security review gates

Перед production release необходимо как минимум:

1. Threat model review.
2. SSRF test matrix.
3. Browser isolation review.
4. Dependency/container vulnerability scan.
5. Secrets/log redaction audit.
6. Ownership/authorization negative tests.
7. File/parser abuse tests.
8. Resource-limit/load abuse tests.
9. Restart/reaper cleanup tests.
10. Review MCP/REST exposure опасных capabilities.

Полный release gate определяется `release-gates.md`.

---

# 51. Security-related open decisions

До соответствующей реализации требуется закрыть:

1. Safe-connect implementation против DNS rebinding для HTTPX.
2. Browser-level request interception + network egress implementation.
3. Нужен ли отдельный isolated Content Parser Worker/process pool для части L1 parsers.
4. Service authentication Control Plane ↔ Browser Worker.
5. Authentication/authorization model REST/MCP.
6. Content serving/download headers и отдельный download origin при Web UI.
7. Malware scanning policy: требуется ли она для сохранённых downloads/uploads или остаётся external L2/security integration.
8. Точные resource quotas.
9. Persistent browser profiles — будут ли вообще поддерживаться в раннем roadmap.
10. Deployment-specific private network ranges/metadata protections.

Открытые решения не ослабляют уже принятые обязательные security invariants.

---

# 52. Нормативные внешние ориентиры

При реализации security controls необходимо сверяться с актуальными первичными/авторитетными рекомендациями, в частности:

- OWASP Server-Side Request Forgery Prevention Cheat Sheet;
- OWASP File Upload Cheat Sheet;
- OWASP Input Validation guidance;
- официальной документацией Playwright по Docker/sandbox для работы с недоверенными сайтами;
- актуальными IANA registries special-purpose IPv4/IPv6 ranges;
- security guidance конкретного deployment platform/cloud.

Design этого репозитория остаётся каноническим владельцем требований Web Access, а внешние материалы используются для проверки корректности реализации конкретных controls.
