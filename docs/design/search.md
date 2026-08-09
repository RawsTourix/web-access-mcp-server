# Search subsystem design

## Статус документа

Этот документ является каноническим владельцем **Search application semantics, provider boundary, normalization, cache/freshness и provider execution policy** Web Access MCP.

Он не определяет окончательный REST endpoint или MCP tool schema. Эти facades проектируются позже поверх описанного здесь backend contract.

---

# 1. Purpose

Search предоставляет программному клиенту поисковую выдачу по одному или нескольким независимым запросам через явный/configured SearchProvider.

Search отвечает на вопрос:

> Какие web resources поисковый backend считает релевантными этому запросу?

Search **не отвечает** на вопрос:

> Что фактически содержится на найденной странице?

Для чтения найденного URL клиент использует Retrieval или Browser отдельным следующим шагом.

---

# 2. Responsibilities

Search отвечает за:

- приём нормализованного search application request;
- batch execution независимых query items;
- выбор явно указанного или configured default provider;
- проверку provider capabilities;
- вызов provider adapter;
- normalization provider response;
- сохранение provider ranking/order;
- provenance;
- cache/freshness semantics;
- provider rate/capacity control;
- billable provider usage accounting там, где это требуется;
- normalized errors/warnings/hints;
- observability.

---

# 3. Non-goals

Search не должен:

- автоматически открывать найденные URL;
- выполнять Retrieval;
- запускать Browser;
- анализировать содержимое страниц;
- оценивать «качество» результата LLM-эвристикой;
- автоматически менять provider из-за малого количества результатов;
- автоматически комбинировать Yandex и SearXNG в один ranked list;
- выполнять research planning;
- пересказывать поисковые результаты;
- считать snippet фактическим содержимым страницы.

---

# 4. Основная application operation

Концептуально:

```text
SearchApplicationService.search(
    ExecutionContext,
    SearchBatchRequest,
) -> OperationResult[SearchBatchResult]
```

Search является request-bound operation по умолчанию.

Большой/длительный research workflow не является частью Search operation и при необходимости проектируется отдельно через Jobs/composed application capability.

---

# 5. Batch-first input

Search принимает непустой список независимых query items.

```text
SearchBatchRequest
└── queries[]
    └── SearchQuery
```

Один запрос передаётся как список из одного элемента.

Не создаётся отдельная application operation `search_many`.

Batch semantics наследуются из `application-contracts.md`:

- input order сохраняется;
- каждый query item имеет собственный outcome/error;
- failure одного query не уничтожает результаты остальных;
- aggregate outcome вычисляется общим алгоритмом;
- internal concurrency ограничивается policy и не является обещанием public contract.

---

# 6. SearchQuery

Концептуальная common application model:

```text
SearchQuery
├── query
├── provider_id | null
├── page
├── limit
├── language | null
├── region | null
├── safe_search | null
└── time_range | null
```

Точная Python/Pydantic representation проектируется при implementation, но semantics полей фиксируется этим документом.

---

# 7. `query`

`query` — текст поискового запроса, передаваемый SearchProvider.

Search core:

- проверяет, что query непустой после базовой normalization;
- применяет configurable generic size/control-character limits;
- не пытается семантически переписывать запрос;
- не добавляет скрытые keywords/operators;
- не интерпретирует provider-specific search syntax.

Provider может иметь дополнительные ограничения на длину/синтаксис. Они валидируются adapter/capability layer и возвращаются как repairable provider validation error.

---

# 8. Provider selection

`provider_id = null` означает:

```text
использовать configured default provider
```

Это **не означает `auto`**.

Нет скрытого алгоритма:

```text
default provider дал мало результатов
→ попробовать другой provider
```

Если default provider недоступен, query завершается соответствующим failure/rejection согласно error model.

Клиент может выполнить новую Search operation с другим `provider_id`.

---

# 9. SearchProviderRegistry

Application layer должен иметь registry доступных Search Providers.

Концептуально provider descriptor содержит:

```text
provider_id
human-readable name
provider kind
configured/enabled state
billable flag
capabilities
configuration revision
```

Health/readiness является runtime state и не обязано быть частью immutable descriptor.

Registry не раскрывает credentials.

---

# 10. SearchProvider port

Search application объявляет port примерно следующей семантики:

```text
SearchProvider
├── provider_id
├── capabilities()
└── search(context, provider_request)
```

Concrete adapters:

```text
SearXNGProvider
YandexSearchProvider
future providers
```

Application/Search service не импортирует concrete provider implementation.

---

# 11. Provider capabilities

Не все search backends поддерживают одинаковые options.

Provider descriptor должен позволять определить support как минимум для:

- `web` search kind;
- pagination;
- language;
- region;
- safe search;
- time range;
- provider-specific result limits;
- billable usage metadata.

Если клиент указал option, который provider не поддерживает, он **не игнорируется молча**.

Query item завершается `rejected` с repairable `unsupported_option`/provider validation error.

---

# 12. Search kinds

Первый обязательный Search kind:

```text
web
```

Image/video/news search не следует искусственно впихивать в один result schema только потому, что отдельные providers это умеют.

Если такие capabilities добавляются позднее, необходимо решить:

- новый Search kind с typed result union;
- отдельная application operation;
- другой стабильный contract.

До отдельного design generic web Search не обещает image/video result semantics.

---

# 13. `page`

Application `page` является **1-based logical page number**.

```text
page = 1
```

означает первую страницу результатов независимо от provider-specific numbering.

Adapter выполняет mapping.

Это устраняет протекание различий вроде:

```text
SearXNG pageno = 1-based
Yandex provider page field может иметь другую нумерацию/protocol semantics
```

Public Search contract остаётся единым.

---

# 14. `limit`

`limit` означает:

> максимальное количество нормализованных result items, которое Web Access должен вернуть для данного query item в рамках requested page.

`limit` не обязан совпадать с provider-specific page-size parameter.

Adapter может запросить provider-supported размер и затем вернуть не более application limit.

Provider-specific maximum не должен молча повышать requested limit.

Generic max limit является configurable server policy и будет зафиксирован version/deployment config, а не случайным числом в design.

---

# 15. `language`

`language` является provider-agnostic language preference/search option.

Application representation должна использовать стабильную языковую semantics, предпочтительно нормализованный language tag/code.

Adapter:

- маппит common language в provider protocol;
- отклоняет явно неподдерживаемое значение;
- не подменяет язык другим без отражения в result metadata.

Точный accepted language format (`BCP 47`/ограниченный набор) фиксируется implementation schema после проверки обоих основных providers.

---

# 16. `region`

Region является optional application search preference.

Provider capabilities могут:

- поддерживать region;
- не поддерживать region;
- поддерживать только ограниченный region registry.

Web Access не должен создавать огромную скрытую geocoding/region inference систему внутри Search только для маппинга provider region identifiers.

Первая реализация должна использовать детерминированный explicit region representation и provider mapping только там, где он однозначно поддерживается.

Точная common `SearchRegion` model остаётся design detail до реализации Yandex adapter и не должна протекать provider-specific `lr` integer напрямую в MCP common schema.

---

# 17. `safe_search`

Common semantics:

```text
off
moderate
strict
```

или эквивалентный typed enum.

Adapter маппит его в provider-specific filter.

Если provider не поддерживает конкретный уровень, option отклоняется или маппится только если semantics доказуемо эквивалентна.

Нельзя тихо отключать requested strict filtering.

---

# 18. `time_range`

Common базовые значения могут включать:

```text
day
month
year
```

поскольку они поддерживаются SearXNG для engines с соответствующей capability.

Provider-specific поддержка проверяется capabilities.

Если Yandex/другой provider имеет только sorting by time, но не эквивалентный filter, нельзя притворяться, что это та же `time_range` semantics.

---

# 19. Provider-specific advanced options

Общий Search contract не должен превращаться в объединение всех upstream parameters.

Если позднее REST действительно потребуется provider-specific advanced control, он должен проектироваться отдельно через typed extension/provider-specific projection.

Нельзя добавлять в общий SearchQuery бесконтрольный:

```text
provider_options: dict[str, Any]
```

который фактически отменяет abstraction boundary.

---

# 20. SearchQueryResult

Каждый batch item возвращает typed query result.

Концептуально:

```text
SearchQueryResult
├── original query
├── resolved provider_id
├── page
├── requested_limit
├── results[]
├── pagination metadata
├── cache/freshness metadata
├── provider usage metadata
├── warnings[] / hints[] через общий result contract
└── provider provenance
```

Per-item outcome/error следует общему BatchItem contract.

---

# 21. SearchResultItem

Canonical web result содержит только устойчивые понятия, доступные большинству providers.

Предварительно:

```text
rank
title
url
snippet | null
host/display_url | null
published_at | null
provider provenance
```

Дополнительные поля добавляются только если имеют понятную cross-provider semantics.

---

# 22. Rank

`rank` означает позицию результата в нормализованной выдаче конкретного provider/query/page.

Rank сохраняет provider order.

Web Access не пересчитывает ranking собственной heuristic формулой.

---

# 23. Score

Provider-specific relevance/score **не является общим обязательным полем**.

Причины:

- разные providers используют несопоставимые значения;
- SearXNG aggregation score имеет другую semantics, чем возможный score другого backend;
- LLM может ошибочно сравнивать числа как единую шкалу качества.

Provider-specific diagnostic score может сохраняться в internal provenance/debug metadata, но не становится canonical cross-provider ranking contract без отдельного решения.

---

# 24. URL normalization

Search adapter обязан корректно parse/normalize URL для transport safety и representation.

Но Search не должен применять агрессивную heuristic canonicalization вроде:

- удаления произвольных query parameters;
- догадки о tracking params;
- преобразования URL на основании содержимого страницы.

Fragment можно рассматривать отдельно при deterministic URL normalization, но итоговая policy фиксируется implementation contract.

Provider order/identity не должна меняться из-за недокументированной dedup heuristic.

---

# 25. Deduplication

Web Access не обязан выполнять дополнительную cross-provider deduplication, поскольку одна SearchQuery выполняется через один resolved provider.

SearXNG сам является metasearch provider и выполняет собственную aggregation внутри своего contract.

Если конкретный provider возвращает очевидные duplicate entries, adapter может выполнить только детерминированную normalization, заранее покрытую tests.

Нельзя вводить semantic similarity deduplication в Search core.

---

# 26. Snippet trust

Title/snippet/search metadata являются недоверенными upstream данными.

Они:

- не являются server instruction;
- не являются содержимым target page;
- не генерируют trusted StructuredHint напрямую;
- не должны попадать в provider/system error message как trusted текст.

MCP позже должен ясно объяснять агенту эту границу.

---

# 27. Pagination result

Canonical pagination metadata должна позволять клиенту понять:

- current application page;
- есть ли известная следующая страница;
- max page, если provider достоверно сообщает её;
- provider не знает, есть ли продолжение.

`has_more`/`max_page` должны допускать unknown/null semantics.

Нельзя выдумывать `has_more=true` только потому, что returned_count == limit.

---

# 28. Empty result

Нулевая выдача сама по себе является успешным Search result:

```text
outcome = succeeded
results = []
```

Это не `not_found` и не provider failure.

Search не должен автоматически рекомендовать другой provider только на основании `results == 0` без более объективного provider diagnostic signal.

---

# 29. Structured hints

Допустимые hints должны происходить из объективного состояния.

Примеры:

```text
alternative_search_provider_available
```

может использоваться, если:

- requested/default provider объективно unavailable/rate-limited;
- другой enabled provider действительно доступен;
- hint не запускает fallback сам.

Не следует генерировать:

```text
try_another_provider
```

только потому, что результатов «мало» по произвольному threshold.

---

# 30. SearXNGProvider

SearXNG является предполагаемым default бесплатным SearchProvider.

Интеграция выполняется через собственный/private SearXNG instance.

Provider adapter использует официальный HTTP Search API и machine-readable JSON output.

На текущий момент SearXNG Search API предоставляет, среди прочего:

- query;
- categories;
- language;
- page number;
- time range;
- output format;
- safe search.

Наличие конкретной capability у underlying engines может различаться, поэтому Web Access не должен обещать больше, чем фактически поддерживает configured SearXNG profile.

---

# 31. SearXNG configuration boundary

Выбор конкретных underlying search engines принадлежит SearXNG deployment/configuration, а не обычному SearchQuery Web Access.

Публичный common contract не должен требовать от LLM знания внутреннего списка engines SearXNG.

Если в будущем administrator REST interface должен управлять SearXNG profile, это отдельная operational capability.

---

# 32. SearXNG partial engine failures

SearXNG может получить результаты от части engines при ошибках других.

Если provider response позволяет достоверно определить такую ситуацию:

- SearchQuery может оставаться `succeeded`;
- adapter добавляет warning с безопасной diagnostic metadata;
- returned results сохраняются.

Нельзя превращать частичный upstream engine warning в полный failure, если сам SearXNG успешно сформировал валидную выдачу.

---

# 33. YandexSearchProvider

Yandex Search является дополнительным billable provider.

Adapter должен:

- использовать стабильный поддерживаемый Yandex Search API interface;
- хранить credentials только в configuration/secrets;
- маппить application pagination/language/region/safe-search semantics;
- учитывать provider-specific query/limit constraints;
- нормализовать результаты в общий `SearchResultItem`;
- фиксировать billable usage metadata;
- не раскрывать `folderId`, API key и другие provider internals клиенту.

---

# 34. Yandex region mapping

Yandex поддерживает region preference через собственный region identifier model.

Common Search contract не должен требовать от MCP/общего REST клиента знания raw provider `lr` ID как основного понятия.

Необходимо спроектировать deterministic mapping common `SearchRegion` → Yandex region reference для поддерживаемого набора.

Если region невозможно однозначно сопоставить без отдельного справочника/внешней логики, запрос отклоняется как unsupported region вместо heuristic guessing.

---

# 35. Yandex query constraints

Yandex adapter обязан валидировать provider-specific ограничения до upstream request, когда они известны.

Такие ограничения не должны автоматически становиться global restriction SearXNG/common Search.

Например более строгий max query length Yandex не должен искусственно ограничивать другой provider, если common server policy допускает больше.

---

# 36. Provider protocol revision

Provider adapter должен иметь собственную implementation revision/version awareness.

Изменение Yandex/SearXNG response parser:

- покрывается contract/integration tests;
- не должно незаметно менять common Search schema;
- при несовместимости должно отражаться provider health/readiness.

---

# 37. Cache

Search cache является optional infrastructure optimization.

Cache key должен концептуально учитывать как минимум:

```text
provider_id
provider/config revision
query
page
limit
language
region
safe_search
time_range
search contract/cache schema revision
```

Точный key format не является public contract.

---

# 38. Cache freshness

Cached query result должен содержать/позволять восстановить:

- `cached = true`;
- когда upstream result был фактически получен;
- cache policy/revision настолько, насколько это требуется diagnostics.

Cache не должен выдавать старый result за новый upstream fetch.

TTL configurable per provider/search policy.

---

# 39. Cache и billing

Cache hit не создаёт новый upstream billable call.

Usage/accounting metadata должна отличать:

```text
served_from_cache
```

от

```text
provider_called
```

Это особенно важно для Yandex Search.

---

# 40. Cache bypass/refresh

Не следует добавлять public `no_cache` parameter раньше реальной потребности.

REST design позже решит, нужен ли программному клиенту explicit cache policy control.

MCP facade по умолчанию не должен заставлять LLM управлять infrastructure cache details.

---

# 41. Rate limiting

Search должен иметь два потенциальных уровня rate/capacity control:

- service/principal policy;
- provider-specific policy.

Batch не должен позволять обойти лимит, упаковывая множество query items в один request.

Provider usage считается на уровне фактических query/provider calls.

---

# 42. Provider concurrency

Batch queries могут выполняться параллельно, но concurrency bounded.

Необходимы:

- global/service capacity;
- per-provider limit;
- deadline awareness;
- cancellation.

Точные числа configuration-specific.

---

# 43. Provider timeout

Provider call timeout не должен превышать оставшийся application deadline.

Provider-specific connect/read timeout profile может быть короче общего deadline.

Timeout одного query item не отменяет автоматически independent siblings batch.

---

# 44. Retry

Search является кандидатом на `safe_retry`, поскольку не должен создавать внешний side effect кроме billable/read request к provider.

Но retry должен учитывать:

- error stage;
- provider rate limits;
- billable duplication;
- remaining deadline;
- configured retry policy.

Для billable provider повторный запрос может стоить денег, поэтому infrastructure retry count должен быть ограничен и observable.

---

# 45. Provider usage accounting

Для billable provider необходимо фиксировать usage настолько, чтобы можно было понимать фактические затраты и quotas.

Предварительно:

```text
provider_id
operation_id/query item reference
upstream call attempted
upstream call confirmed/completed
cache hit/miss
usage units/request count
provider response status
```

Денежная цена не должна хардкодиться в adapter, если pricing может меняться.

Pricing policy/config может позднее вычислять estimate отдельно.

---

# 46. PostgreSQL dependency

Free/request-bound Search не обязан становиться недоступным только потому, что PostgreSQL не используется для хранения search results.

Но если deployment policy требует durable billable accounting для Yandex, Yandex query может требовать доступной persistence capability.

Degraded behavior должен различать providers/capabilities.

---

# 47. Redis dependency

Redis может использоваться для:

- cache;
- rate limiting;
- provider capacity counters.

Если Redis недоступен:

- cache может деградировать в miss/direct provider call, если security/rate policy допускает;
- нельзя обходить обязательный provider rate limit, если Redis является единственным enforcement mechanism.

Exact degraded policy фиксируется implementation/deployment design.

---

# 48. Search results не создают ContentObject автоматически

SearchResult является небольшим structured application result.

Web Access не должен автоматически сохранять каждый result/snippet в ContentStore.

ContentObject появляется, когда фактическое содержимое URL получено Retrieval/Browser или другой explicit operation создаёт content artifact.

---

# 49. Security

Search query/result считаются недоверенными данными.

Требования:

- credentials provider не логируются/не возвращаются;
- query logging проходит privacy/redaction policy;
- provider response parsing bounded;
- HTML/XML/JSON provider response не исполняется как active content;
- search result URL не считается автоматически безопасным для Retrieval;
- последующий Retrieval заново применяет SSRF policy.

SearchProvider доверен как configured integration, но его data не становится trusted instruction.

---

# 50. Observability

Search должен создавать telemetry как минимум для:

- operation/query item count;
- provider_id;
- cache hit/miss;
- upstream latency;
- timeout/error category;
- result count;
- retry count;
- rate-limit events;
- billable usage;
- provider partial warnings;
- deadline cancellation.

Raw query text не должен быть обязательным metric label/log field.

---

# 51. Provider health/readiness

Provider health должен оцениваться отдельно по provider_id.

Состояния могут различать:

```text
configured
enabled
ready
degraded
unavailable
```

Точная readiness model принадлежит observability/deployment design.

Search service в целом может быть degraded, если один дополнительный provider недоступен, но default/free provider работает.

---

# 52. REST projection expectations

Поздний `rest-api.md` должен предоставить Search как богатую application projection, потенциально включая:

- batch query items с индивидуальными options;
- explicit provider selection;
- pagination;
- common filters;
- cache/freshness metadata;
- provider usage metadata;
- diagnostics для authorized clients;
- provider status/admin surface отдельно от обычного Search endpoint.

REST не должен требовать provider-specific raw protocol fields в common endpoint.

---

# 53. MCP projection expectations

Поздний `mcp.md` должен сделать Search проще application/REST model.

Ожидания:

- один canonical web-search tool;
- batch-first input;
- русскоязычный description;
- ясное объяснение, что snippets не являются прочитанными страницами;
- минимум инфраструктурных параметров;
- optional explicit provider только если это действительно полезно агенту;
- structured results/errors/hints;
- отсутствие отдельного `search_many` tool.

Точная MCP schema этим документом не фиксируется.

---

# 54. Tests — provider-independent

Unit/contract tests Search application должны работать через fake providers и проверять:

1. default provider resolution;
2. explicit provider selection;
3. отсутствие hidden fallback;
4. unsupported option rejection;
5. batch ordering;
6. partial success;
7. empty result = succeeded;
8. deterministic pagination mapping contract;
9. cache hit metadata;
10. provider timeout isolation между batch items;
11. warning/hint semantics;
12. billable accounting hook;
13. no ContentObject creation from plain search result.

---

# 55. Tests — SearXNG adapter

Integration/contract tests с контролируемым SearXNG должны проверять:

- JSON format;
- query mapping;
- language;
- 1-based application page mapping;
- safe search;
- time range;
- empty result;
- malformed/partial response;
- underlying engine warning mapping;
- timeout/retry;
- provider result order/provenance.

Не следует строить CI, требующий стабильной реальной выдачи публичного поисковика по конкретному запросу.

---

# 56. Tests — Yandex adapter

Provider tests должны проверять:

- authentication config отсутствует/некорректна;
- page mapping;
- common safe-search mapping;
- region mapping;
- language/localization mapping;
- provider query constraints;
- provider rate/HTTP errors;
- response normalization;
- credentials redaction;
- billable usage recording;
- response protocol revision compatibility.

Network billing tests не должны выполняться в обычном unit test suite без explicit integration profile.

---

# 57. Acceptance criteria Search subsystem

Search design считается реализованным, если:

1. Существует application-level batch Search operation.
2. Один query и N queries используют один contract.
3. Provider выбирается explicit/default, без hidden fallback.
4. SearXNG реализован за `SearchProvider` port.
5. Yandex реализован отдельным adapter без протекания credentials/provider protocol.
6. Unsupported common option не игнорируется молча.
7. Application page всегда 1-based.
8. Provider ranking сохраняется без собственного heuristic reranking.
9. Empty result является successful empty list.
10. Search snippets явно считаются недоверенной поисковой metadata.
11. Search не запускает Retrieval/Browser.
12. Cache сообщает freshness/cache status.
13. Billable upstream calls можно учитывать отдельно от cache hits.
14. Batch partial failures сохраняют sibling results.
15. Provider error/retry/deadline semantics соответствуют общему application contract.
16. REST/MCP смогут использовать тот же SearchApplicationService без дублирования Search logic.

---

# 58. Open questions

Перед implementation Search необходимо закрыть:

1. Точный `SearchRegion` common representation и Yandex mapping strategy.
2. Точный accepted language tag format.
3. Default common `safe_search` policy, если клиент не передал значение.
4. Нужен ли `time_range` в первой реализации Yandex adapter или только SearXNG capability.
5. Точный SearXNG configured category для canonical `web` search.
6. Какую стабильную версию/interface Yandex Search использовать в adapter, учитывая существующий рабочий код и актуальный API.
7. Точная Redis rate-limit algorithm/configuration.
8. Нужен ли durable usage accounting для всех providers или только billable.
9. Нужен ли authorized REST provider-status endpoint уже в первых версиях.
10. Нужен ли MCP explicit provider parameter по умолчанию или provider selection оставить преимущественно REST/config capability.

Эти вопросы не меняют уже зафиксированные Search responsibilities и provider abstraction.

---

# 59. Актуальные provider capabilities как внешний ориентир

На момент проектирования официальный SearXNG Search API поддерживает HTTP search parameters для query, categories, language, page, time range, output format и safe search; JSON должен быть разрешён configuration конкретного instance.

Yandex Search API предоставляет собственную модель web search, region/filter/pagination semantics и является отдельным provider с собственными constraints и billing.

Эти upstream contracts могут развиваться, поэтому provider adapters обязаны изолировать изменения внешних API от общего Search application contract.
