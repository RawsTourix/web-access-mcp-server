# Retrieval subsystem design

## Статус документа

Этот документ является каноническим владельцем **безопасного HTTP(S) получения известных ресурсов** в Web Access MCP.

Retrieval отвечает за network acquisition и наблюдаемую HTTP response semantics.

Content отвечает за inspection/native parsing/storage representation.

Browser является отдельной explicit capability.

---

# 1. Purpose

Retrieval отвечает на вопрос:

> Что фактически вернул HTTP(S)-сервер по известному URL в рамках заданной network/security policy?

Retrieval не отвечает на вопрос:

> Что означает содержимое страницы и какой следующий шаг следует выполнить?

---

# 2. Responsibilities

Retrieval отвечает за:

- batch-first получение одного или нескольких известных URL;
- URL parsing/normalization;
- SSRF/egress validation;
- DNS/target validation;
- HTTP GET;
- redirects с повторной security validation;
- TLS verification;
- streaming response body;
- compressed/decompressed limits;
- deadlines/cancellation;
- безопасную фиксацию HTTP response metadata;
- передачу raw payload в Content boundary;
- provenance redirect/request chain;
- normalized network/upstream errors;
- bounded retry;
- observability.

---

# 3. Non-goals

Retrieval не должен:

- выполнять Search;
- автоматически запускать Browser;
- выполнять JavaScript;
- поддерживать browser cookies/session state;
- выполнять OCR/VLM/advanced document processing;
- парсить HTML/PDF/Office как свою основную ответственность;
- обходить CAPTCHA/anti-bot protection;
- автоматически логиниться на сайты;
- выполнять произвольные POST/PUT/PATCH/DELETE как generic HTTP client;
- обходить `robots.txt` как обязательное правило direct URL fetch;
- рекурсивно переходить по ссылкам;
- оценивать «качество» полученного content.

---

# 4. Основная application operation

Концептуально:

```text
RetrievalApplicationService.fetch(
    ExecutionContext,
    RetrievalBatchRequest,
) -> OperationResult[RetrievalBatchResult]
```

Retrieval является request-bound operation по умолчанию.

---

# 5. Batch-first

Input:

```text
RetrievalBatchRequest
└── items[]
    └── RetrievalRequestItem
```

Один URL передаётся как список из одного элемента.

Не создаётся отдельная operation `fetch_many`.

Batch наследует общие semantics:

- input order сохраняется;
- item errors независимы;
- partial success поддерживается;
- concurrency bounded infrastructure policy;
- deadline может ограничивать оставшиеся items.

---

# 6. RetrievalRequestItem

Минимальный common application contract:

```text
RetrievalRequestItem
├── url
├── language_preference | null
└── request_profile | null
```

На первом design-уровне не предполагается бесконтрольный набор arbitrary headers/options.

Точные safe request profiles определяются implementation/REST design.

---

# 7. HTTP method

Canonical Retrieval является read-oriented operation и выполняет:

```text
GET
```

Generic arbitrary HTTP methods не входят в основной contract.

Причины:

- POST/PUT/PATCH/DELETE могут создавать side effects;
- требуют другого retry/idempotency model;
- часто требуют authentication/body/header controls;
- превращают Web Access в общий HTTP proxy/client вместо сервиса web access.

Если позднее потребуется programmable API request capability, она проектируется отдельно и не маскируется под `Retrieval.fetch`.

---

# 8. HEAD

HEAD не является отдельной публичной Retrieval operation на текущем design-уровне.

Infrastructure может использовать HEAD только если конкретный будущий application contract явно это разрешает и это не меняет semantics.

Нельзя автоматически делать HEAD→GET цепочку как обязательный скрытый heuristic pipeline без причины.

---

# 9. URL schemes

Canonical Retrieval принимает только:

```text
http
https
```

Другие schemes rejected до network dispatch.

---

# 10. Stateless HTTP semantics

Обычный Retrieval не хранит persistent cookie jar между operations.

```text
fetch A
fetch B
```

не образуют browser-like session.

`Set-Cookie` от первого response не должен автоматически влиять на второй запрос.

Если stateful web session нужна клиенту, используется Browser.

---

# 11. Authentication

Canonical public Retrieval не принимает произвольные:

- Cookie;
- Authorization;
- client certificate;
- provider secret headers.

Authenticated HTTP acquisition может быть добавлен только через отдельный explicit security/capability contract.

Нельзя позволять LLM передавать произвольный Authorization header в generic fetch и тем самым превращать Retrieval в credential-forwarding proxy.

---

# 12. Request headers

Infrastructure использует контролируемый request profile.

Базовые headers могут включать:

- configured User-Agent;
- safe Accept;
- Accept-Language из explicit application preference;
- protocol-required headers.

Client-controlled arbitrary header map не является частью common application contract.

REST advanced projection может быть расширена позднее только после security review.

---

# 13. User-Agent

User-Agent задаётся configuration/profile Web Access.

Он не должен скрыто меняться per-request ради anti-bot evasion.

Client может выбирать только из разрешённых request profiles, если такая capability будет добавлена.

---

# 14. URL normalization

До request URL проходит единый parsing/normalization pipeline.

Необходимо сохранить:

- `requested_url`;
- canonical parsed target для security decision;
- `final_url` после redirects;
- redirect chain.

Normalization не должна агрессивно менять semantic query parameters.

---

# 15. SSRF validation

Retrieval использует требования `security.md`.

До connect необходимо проверить:

- scheme;
- credentials/userinfo policy;
- hostname/IP form;
- DNS result(s);
- special/private/internal destinations;
- configured egress restrictions.

Каждый redirect target валидируется заново.

---

# 16. Safe-connect boundary

Application Retrieval не должен самостоятельно реализовывать socket/DNS details.

Он зависит от infrastructure port уровня:

```text
SafeHttpFetcher
```

или эквивалентного набора ports, гарантирующего security contract.

Конкретный HTTPX transport/DNS pinning/connect mechanism требует отдельного implementation design/ADR из-за DNS rebinding race.

---

# 17. Network-level protection

Application SSRF validation дополняется deployment egress policy.

Это особенно важно, потому что DNS resolution и actual connect могут расходиться из-за race/proxy/configuration.

Retrieval correctness не должна зависеть только от одной Python-функции `is_private_ip()`.

---

# 18. Redirects

Redirect handling выполняется вручную/control-loop с security validation каждого target.

Response chain концептуально сохраняет:

```text
status
location
resolved/normalized target
```

до configured maximum redirects.

Redirect loop/limit возвращает нормализованный failure.

---

# 19. TLS

HTTPS certificate verification включена по умолчанию и не отключается public client parameter.

Custom CA/internal HTTPS требует operator/deployment configuration, а не `verify=false` от MCP/REST caller.

TLS errors нормализуются как network/upstream failure.

---

# 20. Connection pooling

HTTPX connection pooling является infrastructure optimization.

Pool lifecycle принадлежит Control Plane bootstrap/lifespan.

Application contract не зависит от конкретного connection reuse.

---

# 21. Streaming body

Response body читается streaming способом.

Retrieval не должен выполнять:

```text
await response.read()
→ потом проверить размер
```

для потенциально неограниченного response.

Limits применяются во время чтения.

---

# 22. Response size limits

Должны существовать configurable limits как минимум для:

- raw/compressed bytes;
- decompressed bytes;
- total operation bytes;
- batch total bytes при необходимости.

При превышении hard limit canonical behavior:

```text
item outcome = failed/rejected according to stage
error = response_too_large / decompression_limit
```

Partial raw payload не объявляется полноценным доступным ContentObject без отдельного explicit truncated-content contract.

---

# 23. Truncation

Automatic silent truncation запрещена.

Если в будущем появится explicit `allow_truncated` capability, result обязан ясно отражать:

- что content incomplete;
- фактический byte count;
- причину truncation.

На базовом contract превышение hard limit считается controlled failure.

---

# 24. Content-Encoding

Infrastructure может декомпрессировать standard HTTP content encodings, но обязан учитывать expansion limits.

Declared `Content-Length` не является достаточной защитой.

Если decompression limit превышен, operation прекращается.

---

# 25. Timeout/deadline

Retrieval использует несколько инфраструктурных timeout classes:

- connect;
- read inactivity;
- total/application deadline.

Они не должны противоречить общему ExecutionContext deadline.

Batch item timeout не уничтожает successful siblings.

---

# 26. Cancellation

Cancellation во время streaming fetch должна:

- прекратить дальнейшее чтение;
- закрыть/вернуть connection согласно HTTP client semantics;
- очистить staged Content payload;
- вернуть `cancelled`, если side effect/outcome semantics это допускает.

HTTP GET считается read-oriented, но provider/server может логировать/считать запрос; это не превращает Retrieval в mutating operation приложения.

---

# 27. Retry

Retrieval является кандидатом `safe_retry`, но retry консервативен.

Допустимые кандидаты:

- DNS/connect failure до получения response;
- transient connection reset до meaningful response;
- отдельные retryable HTTP gateway failures, если policy это разрешает.

Не следует автоматически retry:

- policy rejection;
- response too large;
- invalid redirect;
- certificate error;
- arbitrary 4xx;
- после исчерпания deadline.

Retry count bounded и observable.

---

# 28. HTTP status semantics

Наличие HTTP response и application success — связанные, но не идентичные понятия.

Retrieval должен сохранять HTTP response metadata даже при 4xx/5xx, если response был безопасно получен.

Canonical item result может содержать response data/content reference вместе с non-success `upstream_http_error` outcome.

Это позволяет агенту/REST client увидеть:

```text
404 + body
403 + response metadata
500 + error page content
```

без ложного утверждения, что target resource успешно получен как normal success.

Точная mapping таблица HTTP status → item outcome/error фиксируется implementation contract/REST projection, но не должна терять response body автоматически.

---

# 29. 2xx semantics

Валидный 2xx response с body, успешно сохранённым/ingested Content subsystem, является обычным `succeeded` item.

204/пустой 2xx является successful HTTP result с пустым content semantics, а не автоматически browser fallback.

---

# 30. Response metadata

Canonical observed response metadata должна включать как минимум:

```text
requested_url
final_url
redirect chain
status_code
selected safe headers/fields
received bytes
retrieved_at
content reference, если body сохранён
```

Не следует возвращать все raw headers как обязательный common result.

---

# 31. Safe response header projection

Полезные normalized fields могут включать:

- declared Content-Type;
- Content-Length;
- Content-Encoding;
- ETag;
- Last-Modified;
- Content-Disposition filename metadata;
- Cache-Control/Expires при будущей cache semantics.

`Set-Cookie`, Authorization-related или sensitive headers не должны бездумно возвращаться agent-facing клиенту.

REST diagnostics может иметь более полный authorized view с redaction.

---

# 32. Content-Disposition filename

Filename является недоверенной metadata.

Retrieval передаёт его в Content Inspection как metadata, но не использует как storage path.

Path separators/control characters нормализуются/ограничиваются согласно Content security policy.

---

# 33. Handoff в Content

Retrieval не владеет parsing/storage implementation.

Типовой application flow:

```text
HTTP response stream
→ Content ingest boundary
→ raw ContentObject
→ Retrieval result содержит ContentRef
```

Content отвечает за:

- storage lifecycle;
- hash;
- format identification;
- L0/L1 processing;
- representations.

---

# 34. Raw ContentObject как canonical body handle

Успешно полученный body должен иметь стабильный ContentObject reference, если operation contract обещает последующее чтение/processing.

Это позволяет:

```text
Retrieval
→ raw ContentObject
→ позже Content Native Parsing
```

без повторного HTTP request.

Retention raw objects определяется Content policy и может быть коротким/configurable.

---

# 35. Empty body

Response без body может не создавать physical Content payload.

Application может вернуть nullable ContentRef + response metadata.

Не следует создавать пустой blob только ради uniformity, если Content design не требует этого.

---

# 36. Failure при Content persistence

Если HTTP body получен, но required Content ingestion/persistence не завершена:

- Retrieval не должен возвращать ложный durable `content_id`;
- staged payload очищается/reconciles;
- item получает normalized infrastructure/content persistence failure.

Response metadata может быть сохранена как diagnostic result, если это безопасно и contract допускает.

---

# 37. Declared media type не является detected format

Retrieval записывает **declared** HTTP Content-Type.

Detected format/media type определяется Content Inspection.

Это принципиально:

```text
Retrieval: server сказал application/pdf
Content: signature показывает фактический формат
```

Несоответствие принадлежит Content warning/diagnostics.

---

# 38. Browser hint не формируется по одному HTTP status/size heuristic

Retrieval не должен сам решать:

```text
HTML маленький → Browser
```

`browser_may_be_required` обычно требует Content-level observation, например native HTML содержимое минимально при наличии script shell.

Retrieval предоставляет факты, а Content/application composed result может создать trusted hint.

---

# 39. 401/403

401/403 фиксируются как upstream HTTP response.

Retrieval может предоставить нейтральную diagnostic metadata.

Не следует автоматически:

- запускать Browser;
- пытаться подобрать cookies;
- повторять с другим User-Agent;
- использовать credentials.

Если позднее появится hint `authentication_may_be_required`, он должен основываться на объективном status/protocol signal и не выполнять auth сам.

---

# 40. Anti-bot/CAPTCHA

Retrieval не пытается обходить anti-bot protection.

Ответ CAPTCHA/challenge является фактическим upstream content/status.

Client/agent может решить использовать Browser, но Web Access не обещает bypass.

---

# 41. Robots.txt

Direct user-requested Retrieval не обязан автоматически проверять `robots.txt` перед каждым fetch.

`robots.txt` policy относится прежде всего к automated crawl/job semantics и проектируется в `jobs.md`/crawler design.

Operator может в будущем включить более строгую policy, но Retrieval core не смешивает direct fetch с crawler governance.

---

# 42. Conditional requests/cache

HTTP cache/ETag/If-Modified-Since не входят в обязательный базовый Retrieval contract.

Если Retrieval cache будет добавлен:

- freshness должна быть observable;
- 304 mapping должно сохранять provenance;
- stale cache не выдаётся за fresh retrieval;
- cache policy не должна заставлять LLM управлять HTTP internals через MCP.

---

# 43. Range requests

Range/partial fetch не является базовым public Retrieval parameter.

Он может использоваться специализированной Content/application capability позднее, если это нужно для больших formats.

Нельзя автоматически считать partial bytes полноценным ContentObject исходного ресурса.

---

# 44. Per-host capacity

Infrastructure должна позволять ограничивать concurrency к одному host/domain для:

- stability;
- polite access;
- abuse resistance;
- предотвращения connection storms.

Точные limits configurable.

Batch одного клиента не должен создавать неограниченное количество parallel connections.

---

# 45. DNS caching

DNS cache может использоваться infrastructure, но должен быть совместим с SSRF/rebinding policy.

Нельзя сохранять разрешение hostname дольше, чем допускает security model, если это создаёт stale trust decision.

Точный resolver/cache design является частью SafeHttpFetcher implementation.

---

# 46. Query/privacy logging

URL может содержать sensitive query parameters.

Observability не логирует full URL без redaction policy.

Минимально безопасно логировать:

- normalized host;
- scheme;
- status;
- timing;
- byte count;
- operation/correlation ID;
- redacted URL fingerprint/path при необходимости.

---

# 47. Security tests

Retrieval-specific tests должны покрывать:

- localhost/private IPv4;
- private/special IPv6;
- IPv4-mapped IPv6;
- public hostname → private address;
- redirect public→private;
- redirect loops;
- credentials in URL;
- malformed/ambiguous URLs;
- DNS rebinding-safe connect contract;
- certificate failure;
- compressed/decompressed size limits;
- slow/timeout response;
- oversized Content-Length и streaming overrun;
- cancellation during stream;
- cross-item batch isolation.

---

# 48. Integration tests

Нужен controlled test HTTP server, способный воспроизводить:

- redirects;
- arbitrary status;
- chunked streaming;
- slow reads;
- gzip/brotli-like compression profiles, которые поддерживает client;
- incorrect Content-Length;
- misleading Content-Type;
- large response;
- connection reset;
- empty response.

CI не должен зависеть от стабильности случайных публичных сайтов.

---

# 49. Observability

Retrieval telemetry должна включать:

- operation/item count;
- target host в безопасной форме;
- status code class;
- redirect count;
- bytes received;
- duration;
- timeout stage;
- retry count;
- SSRF/policy rejection count;
- response-too-large;
- Content ingestion failure;
- cancellation.

High-cardinality/full URL не используется как metric label.

---

# 50. REST projection expectations

REST позднее может предоставить более богатую Retrieval projection:

- batch URLs;
- safe request profile;
- richer HTTP metadata;
- content handles;
- authorized diagnostics;
- explicit limits только там, где client override разрешён policy.

REST common endpoint не становится unrestricted HTTP proxy.

---

# 51. MCP projection expectations

MCP должен представить Retrieval максимально просто для LLM.

Ожидания:

- один canonical tool для одного/N известных URLs;
- название уровня `web_fetch`/эквивалентное;
- русскоязычный description;
- ясное указание, что это ordinary HTTP retrieval, не Browser;
- отсутствие `web_fetch_many`;
- отсутствие arbitrary headers/cookies/auth;
- structured Content references/results;
- Browser hint только из trusted application observations, а не hidden fallback.

Точная MCP schema проектируется позже.

---

# 52. Acceptance criteria Retrieval subsystem

Retrieval считается реализованным, если:

1. Один URL и N URLs используют одну batch-first operation.
2. Canonical method — read-only GET.
3. Ordinary Retrieval stateless относительно cookies/browser session.
4. Arbitrary Authorization/Cookie headers отсутствуют в common contract.
5. Каждый URL проходит SSRF validation до connect и после каждого redirect.
6. Network-level egress используется как defense in depth в production design.
7. Response body читается bounded streaming способом.
8. Hard size/decompression limits не приводят к silent truncation.
9. TLS verify нельзя отключить caller-ом common API.
10. Per-item failures не уничтожают siblings batch.
11. Raw body передаётся в Content boundary и может получить ContentObject handle.
12. Declared Content-Type не подменяет Content Inspection.
13. Retrieval не запускает Browser/Native Parsing/L2 автоматически.
14. HTTP 4xx/5xx metadata/body не теряются, но корректно отражаются non-success semantics.
15. Client disconnect/deadline корректно отменяет bounded request-bound work.
16. Public results не содержат local paths/raw sensitive headers.
17. Controlled integration server покрывает redirect/stream/timeout/size failure matrix.

---

# 53. Open questions

До implementation Retrieval необходимо закрыть:

1. Конкретный SafeHttpFetcher/DNS pinning design поверх HTTPX.
2. Exact network egress enforcement для Docker/production deployment.
3. Список supported HTTP content encodings и decompression implementation.
4. Точная HTTP status → OperationOutcome/Error mapping.
5. Всегда ли успешный body создаёт durable/transient ContentObject или допускается inline ephemeral representation для очень малых payloads.
6. Нужна ли explicit safe `request_profile` capability уже в первой версии.
7. Нужен ли `Accept-Language` application field или достаточно future transport/profile option.
8. Нужен ли Retrieval cache/conditional requests в раннем roadmap.
9. Нужен ли отдельный network worker/runtime для особо больших downloads или streaming ContentStore достаточно.
10. Точные batch/byte/per-host limits.

Эти вопросы уточняют implementation и не меняют базовую ответственность Retrieval.
