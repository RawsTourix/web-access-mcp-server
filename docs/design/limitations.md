# Designed limitations

## Статус документа

Канонический список **осознанных границ первой stable линии Web Access**, которые не являются дефектами сами по себе.

Release notes конкретной версии могут добавлять implementation-specific limitations, но не должны скрывать эти архитектурные границы.

---

# 1. External web is not controlled

Web Access не гарантирует:

- доступность внешнего сайта/provider;
- фиксированную latency;
- неизменность страницы между запросами;
- отсутствие anti-bot/geo/auth restrictions;
- корректность search engine snippets;
- истинность найденного контента.

Сервис гарантирует собственный bounded/structured execution и provenance, а не качество всего Internet.

---

# 2. No hidden reasoning/orchestration

Service не пытается самостоятельно решить semantic research strategy.

Не является багом:

```text
пустой static HTML
→ не открыл Browser автоматически

мало search results
→ не переключил provider автоматически

скан PDF
→ не запустил OCR автоматически
```

Для таких случаев предусмотрены diagnostics/hints и explicit next capability choice caller-а.

---

# 3. L2 document/media processing outside Web Access

Первая stable line не включает встроенный:

- OCR;
- VLM/image understanding;
- advanced layout AI;
- LibreOffice conversion/rendering;
- speech transcription;
- video semantic understanding;
- diagram understanding.

Web Access предоставляет raw ContentObject + L0/L1 capabilities и может интегрироваться с отдельным future processing service.

---

# 4. Registered native formats only

L1 Native Parsing поддерживает только форматы, зарегистрированные и протестированные текущей software revision.

Необязательно поддерживаются все существующие:

```text
legacy DOC/XLS/PPT
DJVU
XPS
EPS/WMF/EMF
arbitrary proprietary containers
```

Unsupported format должен завершаться честным diagnostic/result, а не случайным fallback.

---

# 5. Macros/formulas/code are not executed

Office/document parsers не выполняют:

- VBA/macros;
- embedded scripts;
- spreadsheet formulas как вычислительный движок;
- external linked document resources;
- arbitrary code.

Formula text/cached value может быть прочитан, если формат/library безопасно его предоставляет.

---

# 6. BrowserSession is ephemeral

Baseline BrowserSession:

- non-persistent;
- имеет TTL/max lifetime;
- не переживает owning session subprocess/Browser Worker loss;
- не мигрирует между workers;
- не восстанавливается автоматически из PostgreSQL after crash.

Потерянная live session становится `lost`.

Durable browser profiles требуют отдельной security/product capability.

---

# 7. No persistent login credential vault

Web Access не хранит пользовательские сайты passwords/cookies как reusable profile baseline.

Agent может взаимодействовать с login form в explicit BrowserSession, но long-term credential/profile management не входит v1 core.

---

# 8. No CAPTCHA/stealth guarantee

Service не обещает:

- CAPTCHA solving/bypass;
- stealth fingerprint evasion;
- anti-bot circumvention;
- proxy rotation;
- guaranteed access to sites blocking automation.

Browser uses normal controlled Chromium/Playwright semantics under security policies.

---

# 9. Browser network features intentionally constrained

Public-only egress security может ограничивать sites/features, зависящие от unrestricted:

- direct UDP/QUIC;
- WebRTC peer-to-peer paths;
- private-network devices;
- local services.

Security boundary имеет приоритет над полной совместимостью со всеми web applications.

---

# 10. No arbitrary Browser code in ordinary MCP/REST facade

Normal client не получает generic:

- `eval` JavaScript;
- Playwright code execution;
- CSS/XPath arbitrary locator command;
- browser launch flags/proxy credentials.

Новые advanced capabilities требуют отдельного design/security boundary.

---

# 11. Exact element refs are short-lived

`element_ref` привязан к snapshot/page generation и может стать stale после DOM replacement/navigation.

Это нормальная safety property.

Caller должен получить новый snapshot, а service не fuzzy-retargets похожий элемент.

---

# 12. Unknown side-effect outcome is possible

Distributed Browser action может закончиться состоянием:

```text
unknown
```

если после потенциального side effect невозможно доказать outcome.

Service не обещает exactly-once external website side effects и не маскирует ambiguity blind retry.

---

# 13. Jobs are at-least-once delivery, fenced execution

Queue wake-up может доставляться повторно.

Correctness обеспечивается DB claim/Attempt fencing/JobItem checkpoints, а не exactly-once broker magic.

Некоторые safe upstream retrieval retries могут наблюдать более новую версию внешнего ресурса.

---

# 14. Only typed durable workloads are public

v1 core Jobs не является generic workflow/task execution engine.

Initial public durable jobs:

- retrieval batch;
- content native parse batch.

No arbitrary Python/function/command payload.

---

# 15. Crawl is not implicit

Site crawling/frontier traversal не моделируется как recursive `web_fetch` loop baseline.

Crawl требует отдельного design (robots/frontier/dedup/scope/politeness/result graph) до появления как public capability.

---

# 16. Redis state is intentionally ephemeral

Redis restart/loss может сбросить:

- caches;
- ephemeral rate/concurrency state;
- worker route registry;
- queue wake-ups.

Durable correctness восстанавливается из PostgreSQL/ContentStore/reconcilers.

Это design choice, не data-loss bug.

---

# 17. Storage dedup does not merge ownership

Физический content-addressed blob может переиспользоваться, но logical ContentObjects/owners остаются отдельными.

Нельзя использовать dedup как способ узнать, есть ли такой content у другого principal.

Logical storage quota также считается per owner, а не только physical unique bytes.

---

# 18. No universal performance SLA

Reference capacity/defaults основаны на конкретном test profile/hardware.

External provider/site latency и operator hardware меняются.

Project фиксирует measured capacity evidence и bounded backpressure, но не объявляет одно универсальное число RPS/session count для любого deployment.

---

# 19. Authentication baseline is service-oriented

Initial stable line может использовать configured Bearer service principals через replaceable `AuthProvider`.

Это не полноценный consumer account product.

Future OIDC/user identity интегрируется через existing Principal/Owner model.

---

# 20. Dynamic policy contains no secrets

Runtime policy registry управляет non-secret limits/capabilities/retention/budgets.

DB/API/provider/S3/auth secrets остаются deployment/secret configuration.

Отсутствие secret editing через admin policy API является intentional security boundary.

---

# 21. Admin is REST-only baseline

Operator policy/worker drain/audit/maintenance не выставляются обычному LLM как MCP tools.

Это intentional separation task execution vs service administration.

---

# 22. Known limitation vs defect

Limitation становится defect, если implementation нарушает заявленный contract.

Примеры defect:

- supported PDF text layer не читается из-за parser bug;
- Browser TTL не очищает process;
- stale ElementRef кликает replacement node;
- committed Job теряется;
- private IP проходит egress;
- resource owner bypass.

Примеры designed limitation:

- scan PDF требует внешнего OCR;
- worker crash теряет live BrowserSession;
- CAPTCHA blocked site недоступен;
- unsupported legacy format остаётся raw ContentObject.

---

# 23. Evolution

Любая limitation может стать будущей capability, но сначала определяется:

```text
responsibility boundary
security impact
resource/lifecycle model
application contract
REST/MCP projection
compatibility impact
release gates
```

Нельзя убрать limitation случайным library shortcut без design review.
