# Content subsystem design

## Статус документа

Этот документ является каноническим владельцем **Content ingest, inspection, Native Parsing, representations, parser registry и ContentStore-facing application semantics** Web Access MCP.

Content не является универсальным document/media processing engine.

---

# 1. Purpose

Content отвечает на вопросы:

> Что за содержимое уже получено?

> Какое дешёвое и непосредственно доступное представление можно получить из этого формата?

> Как сохранить raw и derived representations так, чтобы их можно было использовать повторно без нового Retrieval/Browser action?

---

# 2. Responsibilities

Content отвечает за:

- ingest raw bytes/streams из Retrieval, Browser и будущих upload/import capabilities;
- ContentObject creation/finalization;
- L0 Inspection;
- format/media identification;
- Native Parser registry;
- L1 Native Parsing;
- derived ContentObjects;
- provenance graph;
- content metadata;
- read/stream access к ContentObject;
- retention/expiration integration;
- structured warnings/hints;
- parser execution profiles;
- ContentStore abstraction;
- cleanup/reconciliation вместе с persistence foundation;
- observability.

---

# 3. Non-goals

Content не должен автоматически выполнять:

- OCR;
- VLM/image understanding;
- LibreOffice conversion;
- speech-to-text;
- video understanding;
- semantic table reconstruction через ML;
- browser rendering;
- Search;
- HTTP Retrieval;
- произвольный Python/shell execution;
- unsupported-format conversion только ради получения текста.

Эти операции относятся к L2 Advanced Processing или другим explicit capabilities.

---

# 4. L0 / L1 / L2

Canonical classification:

```text
L0 — Inspection
L1 — Native Parsing
L2 — Advanced Processing (за границей Web Access)
```

Web Access реализует L0 и поддерживаемый набор L1.

---

# 5. L0 Inspection

Inspection получает наблюдаемые свойства ContentObject без semantic AI processing.

Предварительно:

```text
ContentInspection
├── size/hash
├── declared media type
├── detected format/media type
├── filename metadata
├── encoding, если определимо
├── container/type properties
├── dimensions/pages/duration, если дешёво и безопасно определимо
├── parser availability
└── diagnostics/warnings
```

L0 не означает «вообще не читать структуру файла». Он означает bounded deterministic inspection без тяжёлого content understanding.

---

# 6. L1 Native Parsing

Native Parsing — прямое детерминированное чтение уже существующей структуры формата.

Примеры:

```text
HTML → текст / Markdown / ссылки / metadata
PDF с text layer → текст
DOCX → paragraphs / tables
XLSX → sheets / cells
PPTX → slide text/structure
ODT/ODS/ODP → native structure
JSON/XML/CSV → structured representation
EPUB/FB2 → chapters / text
SVG → XML/text/metadata
```

Наличие формата в этом списке не означает обязательную поддержку первой версии. Поддержка определяется registry capabilities.

---

# 7. L2 Advanced Processing

Примеры L2:

```text
scanned PDF → OCR
image → OCR/VLM
legacy DOC → LibreOffice conversion
complex layout → document model
MP3 → transcription
video → perception/transcription
```

Если L1 недоступен:

```text
raw ContentObject остаётся доступен
+ Inspection
+ diagnostics
+ optional structured hint
```

Content не запускает L2 автоматически.

---

# 8. Content ingest

Content должен иметь internal/application operation уровня:

```text
ContentApplicationService.ingest(
    ExecutionContext,
    ContentIngestRequest,
) -> OperationResult[ContentIngestResult]
```

Ingest принимает stream/controlled source adapter, а не требует, чтобы весь payload находился в RAM.

---

# 9. Источники ingest

Content ingest должен поддерживать provenance origin как минимум для:

```text
Retrieval HTTP response
Browser download
Browser screenshot/export/rendered HTML
future REST upload/import
future external processor result
```

Content не должен зависеть от конкретного transport, который создал source bytes.

---

# 10. Ingest processing level

Внутренний application request должен позволять явно определить требуемый processing level:

```text
store_only
inspect
native
```

## `store_only`

Сохранить raw ContentObject без parser pipeline, кроме минимальной integrity/security metadata.

## `inspect`

Выполнить L0.

## `native`

Выполнить L0 и, если зарегистрирован подходящий L1 parser и operation укладывается в его execution policy, получить native representation(s).

Это explicit deterministic policy, а не reasoning heuristic.

---

# 11. Retrieval default integration

Для обычного agent-facing чтения URL ожидаемый composed backend flow:

```text
Retrieval
→ Content ingest(processing_level=native)
→ raw ContentRef
+ Inspection
+ native representations, если доступны
```

Это не означает, что Retrieval сам содержит parser logic.

Content subsystem выполняет processing по явному policy.

REST позднее может предоставить более низкоуровневый control над processing level.

MCP сможет выбрать удобный default `native`, чтобы LLM не делала лишний tool call для каждого HTML.

---

# 12. No automatic L2 escalation

Если `processing_level=native`, допустимы только L0/L1 operations.

Например:

```text
PDF parser обнаружил отсутствие text layer
→ native parse result сообщает text unavailable
→ raw PDF сохраняется
→ hint advanced_processing_may_be_required
```

Нельзя внутри того же operation скрыто вызвать OCR.

---

# 13. ContentObject model

Используется модель из `resource-model.md`:

- один ContentObject = одно конкретное immutable payload representation;
- derived representation создаёт новый ContentObject;
- provenance связывает derived object с source object;
- ownership/lifecycle не смешиваются с physical deduplication.

---

# 14. Raw ContentObject

Ingest сначала создаёт raw representation, максимально близкое к полученному source bytes.

Raw object нужен для:

- повторного parsing;
- debugging;
- нового parser revision;
- передачи внешнему L2 processor;
- download пользователю;
- provenance.

Raw payload не изменяется после publication.

---

# 15. Derived representation

Native parser создаёт один или несколько derived ContentObjects.

Примеры:

```text
HTML raw
├── main Markdown
├── plain text
└── structured metadata JSON

PDF raw
└── native text
```

Не каждый parser обязан создавать все representations.

---

# 16. Representation types

На design-уровне нужны стабильные semantic categories, а не filenames.

Предварительные kinds:

```text
raw
text
markdown
structured
image
binary
rendered_html
```

Точный enum расширяется `content.md` implementation schema и не должен путаться с MIME type.

---

# 17. Media type и representation kind различаются

Например:

```text
representation_kind = text
media_type = text/plain
```

или:

```text
representation_kind = structured
media_type = application/json
```

Raw DOCX:

```text
representation_kind = raw
media_type = application/vnd.openxmlformats-officedocument.wordprocessingml.document
```

---

# 18. Format identification

Format определяется не только extension.

Signals:

```text
source filename/suffix
HTTP declared Content-Type
magic/signature
container structure
parser-safe inspection
```

Canonical `detected_format` должен происходить из Content Inspection.

---

# 19. ContentFormatRegistry

Content subsystem должен иметь registry известных format descriptors.

Descriptor концептуально содержит:

```text
format_id
known media types/extensions/signatures
inspector capability
native parser capability | null
execution profile
supported output representations
parser revision
```

Полный список форматов не является hardcoded architecture contract.

---

# 20. NativeParser port

Application Content объявляет parser port.

Концептуально:

```text
NativeParser
├── parser_id
├── revision
├── supported formats
├── execution profile
└── parse(context, source ContentRef)
```

Concrete parser libraries находятся в infrastructure.

---

# 21. Parser selection

Parser выбирается детерминированно по `detected_format` и registry configuration.

Нельзя использовать случайный chain:

```text
попробовать parser A
если output «плохой» → parser B
если мало текста → OCR
```

Fallback между L1 parsers допустим только если он явно сконфигурирован как deterministic compatibility chain с понятной причиной failure, а не quality heuristic.

---

# 22. Parser availability

Inspection должна позволять сообщить:

```text
native_parser = available
native_parser = unavailable
native_parser = disabled
native_parser = requires_isolated_execution
```

Точный enum определяется implementation.

Client не должен гадать по file extension.

---

# 23. Parser execution profiles

Из-за обработки недоверенных файлов L1 parsers различаются по execution risk.

Предварительные profiles:

```text
inline_bounded
isolated_process
job_required
unsupported
```

### `inline_bounded`

Parser достаточно лёгкий и безопасный при заданных limits для request-bound process.

### `isolated_process`

Parser остаётся L1, но запускается вне Control Plane process из-за crash/resource/native-library risk.

### `job_required`

Parsing остаётся L1 по смыслу, но requested object выходит за synchronous execution contract или операция по design должна выполняться durable.

### `unsupported`

L1 parser отсутствует.

---

# 24. Process isolation не превращает L1 в L2

PDF parser в отдельном sandbox/process всё ещё является Native Parsing, если он просто читает text layer.

Classification L0/L1/L2 определяется смыслом обработки, а не process topology.

---

# 25. Automatic promotion в Job запрещён по умолчанию

Если request-bound L1 operation не допускается policy/size/profile:

```text
operation rejected/failed с code processing_requires_job
+ hint related_capability = jobs/content processing
```

Сервис не должен тихо создать durable Job вместо request-bound operation, если client не запросил это явно.

---

# 26. Не хардкодить heuristic size decisions в business logic

Limits задаются typed/configured execution policy.

Нельзя разбрасывать по parsers условия:

```python
if size > 5_000_000:
    ...
```

без единого policy owner.

Parser descriptor/execution policy должен централизованно определять hard limits/profile.

---

# 27. HTML Native Parsing

HTML L1 должен предоставлять два разных класса данных:

## Main-content representation

- основной текст;
- Markdown/структурированный текст;
- headings, если это часть canonical representation.

## Structural metadata

- title;
- canonical URL metadata;
- meta description;
- language metadata;
- links;
- JSON-LD;
- selected OpenGraph metadata;
- другие детерминированно извлекаемые элементы.

Main-content extraction и structural parser могут использовать разные libraries за единым Content contract.

---

# 28. HTML parser implementation direction

Текущие кандидаты:

- Trafilatura для main-content extraction;
- `lxml` или `selectolax`/другой HTML parser для structural extraction.

Конкретный structural parser требует отдельного технического выбора/benchmark, но application output не должен зависеть от его private node API.

---

# 29. HTML без статического текста

Пример:

```html
<div id="root"></div>
<script src="app.js"></script>
```

Native Parsing возвращает фактический результат:

```text
text representation отсутствует/пусто
structural metadata доступна частично
raw HTML доступен
```

Если parser может объективно определить сильный structural signal вроде отсутствия non-whitespace body text при наличии script-driven shell, application может добавить:

```text
browser_may_be_required
```

Hint не запускает Browser.

---

# 30. HTML hints не основываются на произвольном quality score

Не следует вводить общий hidden threshold:

```text
text_chars < 500 → browser
```

Если используются эвристические diagnostics, они должны:

- быть отдельными наблюдаемыми полями;
- иметь централизованную/configurable policy;
- не инициировать operation;
- не выдавать heuristic confidence как факт.

Предпочтение отдаётся сильным structural signals.

---

# 31. PDF Native Parsing

PDF L1 получает доступный native text layer и bounded document metadata.

Если text layer существует:

```text
raw PDF
→ page/native text representation
```

Не требуется различать PDF/A, PDF/X, PDF/E и другие профили как отдельные application capabilities, если один native parser способен безопасно прочитать нужную структуру.

Format/profile metadata может сохраняться Inspection.

---

# 32. Scanned/image-only PDF

Если PDF содержит страницы, но native parser не получает text layer:

```text
raw PDF остаётся available
native text = unavailable
```

Допустимые diagnostics/hints:

```text
native_text_unavailable
advanced_processing_may_be_required
```

Недопустимо автоматически запускать OCR.

---

# 33. Garbled native text

Content не должен пытаться LLM-эвристикой решить, что текст «дракозябра».

Если parser сообщает объективную decode/parser проблему, это diagnostic/warning/error.

Если parser успешно вернул текст, Web Access не запускает другой processor только из-за субъективной оценки качества.

Клиент/агент может принять дальнейшее решение.

---

# 34. Bitmap images

Для JPEG/PNG/WebP/TIFF и других bitmap formats L0 может возвращать:

- dimensions;
- media format;
- animation/frame count, если применимо и безопасно;
- orientation;
- безопасную metadata.

Семантический текст/описание изображения не является L1.

OCR/VLM относятся к L2.

---

# 35. SVG

SVG является структурированным XML-based format.

L1 может извлекать:

- textual nodes;
- title/description;
- links;
- dimensions/viewBox;
- XML structure metadata.

Понимание смысла сложной vector diagram через vision/semantic reasoning не является L1.

---

# 36. OOXML/ODF

Современные structured office/container formats могут поддерживаться L1 через прямое чтение их document structure.

Примеры:

```text
DOCX → paragraphs/tables
XLSX → sheets/cells
PPTX → slides/text
ODT/ODS/ODP → document/sheets/slides structure
```

Использование LibreOffice для преобразования format не является Native Parsing и не должно скрыто включаться как fallback.

---

# 37. Legacy binary Office formats

DOC/XLS/PPT и другие legacy binary formats поддерживаются L1 только если выбран надёжный прямой parser, соответствующий security/execution policy.

Если такого parser нет:

```text
unsupported native format
→ raw ContentObject
→ optional advanced_processing hint
```

Не следует добавлять LibreOffice только ради того, чтобы поставить галочку «поддерживается всё».

---

# 38. JSON

JSON L1:

- bounded parse;
- валидная structured representation;
- сохранение исходного raw content;
- encoding/parse errors нормализуются.

Большой JSON должен учитывать parser memory limits.

JSON parsing не предполагает semantic schema inference без отдельного contract.

---

# 39. XML

XML L1 использует hardened parser:

- external entities disabled;
- network resolution disabled;
- DTD/entity expansion policy безопасна;
- depth/size limits.

Result может предоставлять structured/text representation согласно format-specific parser.

---

# 40. CSV / tabular text

L1 может возвращать tabular structured representation, но должен иметь limits на:

- rows;
- columns;
- cell size;
- total bytes.

Delimiter/encoding detection не должна превращаться в неограниченный brute-force heuristic process.

---

# 41. EPUB / FB2

Structured ebook formats являются подходящими кандидатами L1:

- metadata;
- table of contents;
- chapters;
- text.

Embedded images остаются отдельными content parts/metadata по design parser.

---

# 42. Audio/video

L0 может поддерживать техническую metadata, если для этого выбран bounded безопасный inspector:

- duration;
- codec;
- dimensions;
- stream metadata.

Speech recognition, subtitles generation и semantic understanding относятся к L2, если они не представлены в файле как уже доступная native track/metadata.

---

# 43. Archive formats

Generic archive extraction не является обязательной user-facing Content capability.

Archives используются внутренне только там, где формат сам является стандартизованным container (OOXML/EPUB/ODF и т.п.) или если позднее спроектирована отдельная archive capability.

Bounded/path-safe extraction rules обязательны.

---

# 44. Nested content

Некоторые formats содержат embedded resources.

Parser может возвращать manifest/relationships, но не обязан автоматически превращать каждый embedded object в отдельный durable ContentObject.

Политика materialization embedded content определяется format-specific design, чтобы не создавать тысячи objects неожиданно.

---

# 45. Structured representation

Для complex formats полезна structured JSON-like representation, но она должна иметь typed/versioned schema.

Нельзя возвращать произвольный parser-native object dump.

Например XLSX structured representation может иметь application-defined workbook/sheet/cell schema, а не serialized `openpyxl` objects.

---

# 46. Representation schema version

Derived structured representation должна иметь schema/revision metadata, чтобы изменение parser output не ломало cached/persisted objects незаметно.

Cache/provenance учитывает parser/representation revision.

---

# 47. Parser revision

Изменение parser logic/version может привести к другому derived result.

Поэтому provenance должна позволять узнать parser revision.

Повторный parse новым parser revision создаёт новый derived ContentObject, а не переписывает старый payload.

---

# 48. Duplicate derived processing

Если тот же source ContentObject уже имеет подходящее derived representation с тем же parser/representation revision и processing parameters, Content может переиспользовать его как cache/dedup optimization.

Это deterministic reuse, а не reasoning heuristic.

Reuse должен учитывать ownership/access policy.

---

# 49. Content read

ContentApplicationService должен предоставлять stable read capability для существующего ContentObject.

Различаются:

- metadata read;
- bounded bytes/text read;
- streaming/download path через REST;
- representation discovery.

Точный REST/MCP projection проектируется позже.

---

# 50. Large text access

Большой extracted text/Markdown не должен безусловно вставляться целиком в MCP result.

Application должна позволять:

- inline preview;
- total size/length metadata;
- ContentRef;
- bounded range/chunk read.

Точная chunk semantics определяется MCP/REST design с учётом Unicode/text boundaries.

---

# 51. Binary access

REST сможет стримить/download binary ContentObject после ownership/policy validation.

MCP не должен передавать большие binary payload как base64 без необходимости.

Для agent workflow предпочтителен Content handle + metadata, а изображения могут использовать поддерживаемый artifact/content integration позднее.

---

# 52. Content retention

Content objects имеют configurable retention category.

Возможные policy classes:

```text
transient_fetch
browser_artifact
job_result
explicit_saved
```

Точные сроки не фиксируются design.

Raw/derived objects могут иметь разные retention, но provenance cleanup не должен оставлять dangling relations без defined semantics.

---

# 53. Cleanup graph

Удаление source ContentObject не должно случайно уничтожать derived object, если policy разрешает ему жить самостоятельно и provenance metadata может сохранять tombstone/source reference.

И наоборот, derived objects не должны бесконечно удерживать transient raw payload без explicit retention policy.

Content GC design должен учитывать graph relationships.

---

# 54. ContentStore consistency

Используются persistence invariants из `persistence.md`:

- payload + PostgreSQL metadata не являются одной atomic transaction;
- staged/finalization lifecycle;
- orphan reconciliation;
- hash verification;
- no public local paths.

`available` ContentObject означает, что предусмотренный storage finalize contract выполнен.

---

# 55. Upload/import security

Будущий REST upload/import использует тот же Content ingest pipeline.

Client filename/MIME не считаются trusted.

Upload не создаёт executable file path на host.

Content Inspector определяет фактический format.

---

# 56. Prompt injection separation

Extracted HTML/document text остаётся недоверенным content.

Parser не должен помещать page text в:

- trusted StructuredHint message;
- server error message как instruction;
- MCP tool description.

Result structure разделяет content и trusted diagnostics.

---

# 57. Structured hints Content

Примеры допустимых hints:

```text
browser_may_be_required
advanced_processing_may_be_required
native_processing_unsupported
processing_requires_job
alternative_representation_available
```

Hint формируется из trusted parser/inspection diagnostics.

Он не запускает действие.

---

# 58. Warning vs Hint

Пример Warning:

```text
declared_content_type_mismatch
```

Пример Hint:

```text
browser_may_be_required
```

Warning описывает текущий result.

Hint предлагает возможный следующий шаг.

---

# 59. Parser errors

Native parser failure должен различать как минимум:

- unsupported format;
- malformed content;
- encrypted/password-protected content;
- resource/size limit exceeded;
- parser timeout;
- parser crash/isolation failure;
- no native representation available.

Не все эти состояния являются одинаковым `failed`.

Например absence native text в valid image-only PDF может быть successful inspection + no derived text, а не parser crash.

---

# 60. Password-protected/encrypted documents

Content не должен brute-force password.

Если format encrypted:

```text
Inspection → encrypted=true
Native Parsing → rejected/encrypted_content
```

Future explicit password capability потребует отдельного secret-handling contract.

---

# 61. Security limits per parser

Parser descriptor/execution policy должен иметь limits, применимые к его format:

- input bytes;
- pages;
- XML depth;
- archive expansion;
- cells/rows;
- image pixels;
- parser deadline;
- output bytes.

Limits централизованы configuration/policy, а не разбросаны magic numbers по implementation.

---

# 62. Isolated parser execution

Для riskier L1 parser design должен использовать abstraction уровня:

```text
NativeParserExecutor
```

которая может иметь реализации:

```text
InProcessParserExecutor
IsolatedProcessParserExecutor
future RemoteParserExecutor
```

Application ContentService выбирает executor по parser execution profile, не зная конкретной process topology.

---

# 63. Runtime topology impact

На текущем этапе не фиксируется отдельный постоянный `Content Worker` runtime.

Первая реализация может использовать bounded subprocess/process pool для `isolated_process` parsers.

Если benchmark/security analysis покажет необходимость отдельного scalable Content Worker pool, `runtime-topology.md` обновляется через design/ADR без изменения Content application contract.

---

# 64. Job-required parsing

Если parser operation по policy требует durable Job:

- request-bound Content operation не создаёт Job скрыто;
- возвращается нормализованный result/hint;
- client явно создаёт соответствующую Job capability.

Job design позже определит, как Content processing job ссылается на source ContentObject.

---

# 65. Observability

Content telemetry должна включать:

- ingested bytes;
- detected format;
- parser_id/revision;
- execution profile;
- parse duration;
- output bytes;
- parser failure category;
- ContentStore latency/error;
- orphan/reconciliation events;
- retention cleanup;
- hints/warnings counts;
- cache/reuse derived representation.

Filename/full content не используется как metric label.

---

# 66. REST projection expectations

REST позднее должен предоставлять богатые Content capabilities:

- inspect ContentObject(s);
- discover representations;
- request Native Parsing;
- metadata/provenance;
- bounded text/bytes read;
- stream/download;
- explicit upload/import, если входит roadmap;
- administrative parser capability/status diagnostics.

REST не должен раскрывать internal storage path/parser-native objects.

---

# 67. MCP projection expectations

MCP не должен превращаться в десятки format-specific tools.

Ожидаемая модель:

- Retrieval-facing `web_fetch` сможет вернуть доступное native content автоматически через `processing_level=native` backend flow;
- отдельный generic Content tool понадобится только для повторного чтения/processing уже существующего ContentRef;
- никаких `read_pdf`, `read_docx`, `read_xlsx` tools без отдельной семантической причины;
- schema объясняет, что unsupported native format не запускает OCR/conversion;
- structured hints помогают LLM выбрать Browser/внешний processor/Job.

Точный MCP catalog определяется позже.

---

# 68. Tests — common Content

Обязательные tests:

1. Raw payload immutable после publication.
2. Derived object получает новый content_id.
3. Provenance source relation сохраняется.
4. Format detection не полагается только на extension/MIME.
5. Unsupported Native Parser возвращает raw content + diagnostics.
6. L1 никогда автоматически не вызывает L2.
7. Parser revision входит в reuse/provenance semantics.
8. Cross-owner derived reuse не нарушает isolation.
9. Large result возвращается через ContentRef без unbounded inline payload.
10. ContentStore path не протекает client-у.
11. Staged/orphan payload reconciliation работает.
12. Parser hard limits применяются централизованно.

---

# 69. Format-specific test matrix

Каждый зарегистрированный Native Parser должен иметь fixtures:

- valid minimal file;
- representative normal file;
- malformed/truncated file;
- oversized/limit case;
- spoofed extension/MIME;
- parser-specific dangerous structure;
- empty/native-no-content case;
- deterministic result/schema snapshot.

Не требуется один гигантский fixture suite форматов, которые ещё не зарегистрированы.

---

# 70. Acceptance criteria Content subsystem

Content считается реализованным, если:

1. Raw ContentObject создаётся через streaming ingest без обязательного buffering всего payload.
2. L0 определяет формат через несколько signals.
3. Parser registry является расширяемым и не построен на монолитном extension switch.
4. L1 parsers не выполняют OCR/VLM/LibreOffice fallback.
5. `processing_level=native` детерминированно выполняет только зарегистрированный L1.
6. Unsupported/scan/image-only content остаётся доступен raw.
7. Structured hints не запускают следующий operation.
8. Derived ContentObjects immutable и имеют provenance/parser revision.
9. Risky L1 parser может выполняться isolated без изменения application contract.
10. Request-bound parser не превращается в Job автоматически.
11. HTML empty-JS-shell case может быть диагностирован без hidden Browser fallback.
12. PDF native text и image-only PDF имеют различимую semantics.
13. OOXML/ODF support может добавляться parser adapters без изменения REST/MCP core contract.
14. ContentStore filesystem/S3 adapters взаимозаменяемы.
15. Большой content доступен через handle/read/stream mechanics, а не giant MCP JSON.

---

# 71. Open questions

До implementation Content необходимо закрыть:

1. Точный structural HTML parser (`lxml`, `selectolax`, другой) после benchmark/security review.
2. Точная Trafilatura integration/output contract.
3. Точный PDF native parser и его process isolation profile.
4. Набор Native Parsers первой версии и порядок последующего расширения.
5. Exact `ContentInspection` schema.
6. Exact representation kinds/schema versioning.
7. Text chunk/read semantics для Unicode MCP access.
8. Content retention classes/defaults.
9. Нужно ли создавать отдельный ContentObject для structured metadata или хранить небольшую metadata в PostgreSQL.
10. Embedded resource materialization policy.
11. Exact isolated parser executor implementation.
12. Нужна ли generic Content-processing durable Job уже в раннем roadmap.
13. Exact objective diagnostics, при которых HTML получает `browser_may_be_required` hint.
14. Exact raw-content persistence default для обычного Retrieval: всегда transient ContentObject или допустим small inline optimization без durable resource.

Открытые вопросы не меняют принятые L0/L1/L2 и Content responsibility boundaries.
