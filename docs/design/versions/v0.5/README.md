# v0.5 — Native Content Expansion

## Статус

`ready for implementation`

Версия расширяет L0/L1 Content capabilities поверх v0.3 Content Core, не меняя границу ответственности Web Access и не добавляя L2 processing.

---

# 1. Цель

После v0.5 Web Access должен уметь **напрямую, детерминированно и bounded** читать существенно больше распространённых document/container formats, если содержимое доступно без OCR/rendering/conversion.

Главный инвариант:

```text
получить/прочитать напрямую можем
→ L0/L1 Web Access

для понимания требуется OCR / office rendering / conversion / VLM / transcription
→ raw ContentObject + diagnostics/hint
→ внешний специализированный capability
```

Версия также добавляет shared S3-compatible ContentStore для multi-replica production deployment.

---

# 2. Prerequisites

Обязательны:

- v0.1 Foundation;
- v0.3 Retrieval & Content Core;
- `../../content.md`;
- `../../resource-model.md`;
- `../../persistence.md`;
- `../../security.md`;
- `../../observability.md`;
- `../../deployment.md`;
- `../../testing.md`;
- `../../release-gates.md`;
- ADR-0007 Content staging/finalization;
- ADR-0008 initial parser/isolation stack;
- ADR-0015 v0.5 native format expansion;
- ADR-0016 S3-compatible ContentStore.

---

# 3. Explicit non-goals

v0.5 не реализует:

- OCR;
- image captioning/VLM;
- document-layout ML;
- LibreOffice conversion/rendering;
- legacy Office conversion (`DOC`, `XLS`, `PPT`) любой ценой;
- macro execution;
- spreadsheet formula evaluation;
- transcription;
- video understanding;
- generic FFmpeg media pipeline;
- universal archive extraction;
- recursive nested archive processing;
- arbitrary user-selected parser package;
- отдельный MCP tool на каждый format;
- automatic L2 invocation.

---

# 4. Capability families

## 4.1 OOXML

Direct L1:

```text
DOCX
XLSX
PPTX
```

Adapters:

- DOCX → `python-docx`;
- XLSX → `openpyxl` read-only path;
- PPTX → `python-pptx`.

Макросы/embedded executable content не выполняются.

## 4.2 OpenDocument

Direct bounded package/XML reader:

```text
ODT
ODS
ODP
```

Без LibreOffice.

## 4.3 E-books/XML documents

```text
EPUB
FB2
```

EPUB читается как package + manifest/spine + XHTML/XML.

FB2 — hardened XML.

## 4.4 SVG

L1 textual/structural representation:

- title/description;
- text nodes;
- links;
- dimensions/viewBox;
- bounded metadata/structure.

No visual interpretation of vector paths.

## 4.5 Bitmap images

L0 inspection:

```text
JPEG/PNG/GIF/WebP/TIFF
```

Metadata only:

- dimensions;
- format;
- animation/frame count;
- mode;
- orientation;
- bounded EXIF/basic metadata.

No OCR/vision.

## 4.6 Audio metadata

Optional enabled capability through Mutagen-compatible direct metadata inspector:

- duration;
- bitrate;
- sample rate/channels where available;
- tags;
- normalized container/codec information.

No transcription/semantic analysis.

---

# 5. Capability registry, а не extension switch

`ContentFormatRegistry` является source of truth.

Descriptor conceptually:

```text
format_id
signatures / media types / package markers
parser_id
parser_revision
execution_profile
supported representations
limits_profile
capabilities
```

File extension — только hint.

Parser выбирается не цепочкой:

```python
try_docx()
except:
    try_pdf()
except:
    ...
```

а через identification + exact registered capability.

---

# 6. SafePackageReader

v0.5 вводит reusable bounded reader для ZIP-based document packages.

Используется как infrastructure primitive для:

- OOXML;
- ODF;
- EPUB.

Он не является generic public archive extraction API.

Requirements:

- entry count bound;
- compressed/uncompressed byte bounds;
- per-entry bound;
- compression-ratio guard;
- path normalization;
- reject absolute/parent traversal;
- no `extractall()`;
- no recursive nested archive extraction;
- no executable member launch;
- bounded XML member parsing;
- cleanup/temp safety.

---

# 7. Initial package safety profile

Initial operational defaults:

```text
max package raw bytes              = 64 MiB
max entries                        = 10,000
max single uncompressed entry      = 64 MiB
max total uncompressed package     = 256 MiB
max compression ratio per entry    = 100x
max package parser wall time       = 30 s
max derived text/structured output = 16 MiB per representation
```

Hard server ceilings:

```text
raw package bytes              <= 256 MiB
entries                        <= 50,000
total uncompressed package     <= 1 GiB
single entry                   <= 256 MiB
compression ratio              <= 200x
isolated parser wall time      <= 120 s
single derived representation  <= 64 MiB
```

Operator defaults могут быть строже, но расширение hard ceilings требует отдельного review/version change.

Limits применяются **до/во время** expansion, а не после materialization всего package.

---

# 8. Isolation policy

## Inline bounded

Только простые XML/text-like readers, где resource amplification доказуемо ограничена:

- FB2;
- SVG;
- небольшие metadata operations.

## Isolated process

Baseline для:

- PDF (унаследовано v0.3);
- DOCX;
- XLSX;
- PPTX;
- ODT/ODS/ODP;
- EPUB;
- bitmap image metadata;
- audio metadata.

`IsolatedProcessParserExecutor` остаётся общей abstraction v0.3.

---

# 9. Parser subprocess hardening

Для v0.5 child:

- spawn/fresh process;
- no DB/Redis/Search/Auth/S3 credentials;
- only bounded private materialized input;
- no shell;
- no network required by parser baseline;
- JSON/versioned result protocol, no pickle;
- wall timeout → terminate → kill;
- output limit;
- POSIX resource limits where reliable;
- temp cleanup/reaper;
- stderr diagnostics separated from data protocol.

При необходимости package parser subprocess может использовать `SafePackageReader` внутри child.

---

# 10. DOCX semantics

Canonical direct representation содержит bounded:

```text
document metadata
paragraphs/headings
list-like structure where available
tables
links
headers/footers where deterministic
embedded media inventory metadata
```

Embedded images не распознаются.

Visual layout не гарантируется.

---

# 11. XLSX semantics

Workbook читается в memory-conscious/read-only режиме.

Representation:

```text
workbook metadata
sheets[]
rows/cells bounded
stored formulas
cached values where available
merged-cell/basic sheet metadata
```

Web Access не пересчитывает formulas.

Если cached formula value существует, она возвращается как наблюдаемый stored value с warning/hint о возможной устарелости.

External workbook links не открываются.

Initial defaults:

```text
max sheets = 256
max emitted cells = 1,000,000
max emitted rows across workbook = 250,000
```

Hard ceilings configurable lower/upper within server policy; output-byte limits всё равно authoritative.

---

# 12. PPTX semantics

Representation:

```text
slide order
text-bearing shapes
tables
links
notes where deterministic/available
image/media inventory metadata
basic shape identity/type metadata where useful
```

No visual interpretation of diagrams/charts/images.

No animation execution.

---

# 13. ODF semantics

ODT/ODS/ODP читаются напрямую из known package members.

No general-purpose file extraction.

### ODT

- text/headings;
- lists/sections;
- tables;
- metadata;
- links.

### ODS

- sheets;
- rows/cells;
- stored formula/value metadata;
- repeated cells/rows expanded only under hard limits.

### ODP

- page/slide order;
- text elements;
- tables/basic document metadata.

No rendering.

---

# 14. EPUB semantics

Flow:

```text
validate package
→ locate package document
→ manifest
→ spine order
→ bounded XHTML chapter parsing
→ metadata/navigation structure
```

Scripts are not executed.

Remote resources are not fetched.

Chapter HTML passes through existing hardened HTML/content logic where compatible.

---

# 15. Image inspection limits

Initial defaults:

```text
max raw image bytes = 64 MiB
max pixel count     = 100 megapixels
max frames          = 1,000
metadata output     = bounded by normal representation limit
```

Library decompression-bomb protections remain enabled.

If an image exceeds profile:

```text
raw ContentObject remains available
→ inspection/native metadata may be rejected/partial
→ no hidden resize/OCR
```

---

# 16. Audio metadata limits

Audio inspector does not decode whole media stream for semantic analysis.

Initial raw input follows Content parser bounds.

Metadata/tag values are bounded by:

- max tag count;
- max value bytes/chars;
- max embedded artwork metadata/payload inspection without automatically materializing giant artwork.

Embedded artwork bytes are not automatically parsed/OCR'd.

---

# 17. Macro/active content

No parser executes:

- VBA;
- embedded scripts;
- OLE objects;
- external links;
- formulas;
- document actions.

Where detectable, inspection records:

```text
active_content_present = true
```

или более specific bounded warning.

---

# 18. Result/representation model

New parsers reuse existing immutable Content representation graph.

Derived ContentObject records:

```text
source_content_id
representation kind/schema revision
parser_id
parser_revision
parameters/profile revision
created_at
warnings/diagnostics provenance
```

Library class names are not public schema dependencies.

---

# 19. `content_parse` semantics

Existing generic backend/MCP operation remains canonical.

It does **not** become:

```text
parse_docx
parse_xlsx
parse_epub
...
```

Client normally supplies:

```text
content_id
optional desired representation/profile where public contract supports it
```

Server chooses the registered direct native parser deterministically from identified format/capability.

LLM не выбирает `python-docx`/`openpyxl`/parser ID.

---

# 20. `web_fetch` relationship

`web_fetch` сохраняет fixed lazy pipeline:

```text
safe retrieval
→ raw ContentObject
→ L0 identification/inspection
→ registered default L1 Native Parsing if directly applicable and within request-bound policy
```

Это не quality heuristic.

Если direct parser отсутствует/неподходящ по safety/time profile:

- raw resource сохраняется;
- result сообщает capability/diagnostics;
- no Browser/L2 fallback.

Heavy L1 parse, который не помещается в request-bound profile, может позднее потребовать durable Job v0.6.

---

# 21. Structured hints

Examples:

```text
native_format_unsupported
advanced_processing_may_be_required
visual_content_not_interpreted
active_content_not_executed
cached_formula_value_may_be_stale
native_parse_requires_durable_job   (после v0.6, если применимо)
```

Hints не запускают external processing.

---

# 22. S3-compatible ContentStore

v0.5 реализует ADR-0016.

`ContentStore` backend profiles:

```text
filesystem
s3
```

Application Content lifecycle одинаков.

S3 adapter:

- boto3/botocore;
- dedicated bounded I/O executor;
- multipart staging where needed;
- content-addressed final keys;
- SHA-256 authoritative, not ETag;
- idempotent finalize/reuse;
- range streaming reads;
- owner auth at application layer;
- no public bucket/object URL baseline.

---

# 23. S3 local/integration profile

Default developer profile остаётся filesystem.

Дополнительный Compose/test profile поднимает reference S3-compatible object storage и прогоняет общий `ContentStore` contract suite.

Production vendor не является application contract.

---

# 24. REST projection

REST Content API расширяется через existing generic resources/operations.

Допустимы:

- format/capability inspection;
- native parse existing ContentObject;
- list available derived representations;
- authorized parser/capability diagnostics endpoint для programmatic/admin clients.

Не создаются format-specific endpoints без отдельной реальной причины.

---

# 25. MCP projection

MCP catalog **не расширяется пропорционально числу форматов**.

Основные existing tools остаются:

```text
web_fetch
content_get
content_parse
```

Descriptions/structured result объясняют detected format, available direct representation и limitations.

MCP schema не содержит library/parser implementation enums.

---

# 26. Observability

Новые dimensions/metrics bounded:

- parser_id/revision (bounded registry cardinality);
- format family;
- execution profile;
- parse success/failure/timeout/limit;
- input/output bytes;
- package expansion bytes/entries;
- isolated child duration/kill;
- S3 transfer/finalize/retry;
- representation reuse/cache-like hit;
- active-content warning counts.

No document text/tag values in metric labels.

---

# 27. Security tests

Обязательны:

- ZIP traversal;
- huge entry count;
- compressed bomb;
- repeated ODS rows/cells amplification;
- malformed OOXML/ODF/EPUB;
- XML entity/network attacks;
- macros not executed;
- external relationships not fetched;
- image decompression bomb;
- malformed image/media metadata;
- isolated process timeout/kill;
- child secret/environment audit;
- output limit;
- parser temp cleanup.

---

# 28. ContentStore S3 tests

Общий contract suite +:

- multipart staging;
- same-hash concurrent finalize;
- copy/finalize crash window;
- range read;
- executor saturation;
- credentials/permission error;
- missing/corrupt final object;
- multiple API replicas read same content;
- orphan staging cleanup.

---

# 29. Release gates

Applicable:

- architecture/dependency gates;
- Content lifecycle/storage gates;
- parser security/isolation gates;
- race/fault gates;
- actual REST/MCP schemas;
- observability;
- S3 adapter contract/integration;
- soak for isolated parsing and package corpus.

No v0.5 acceptance based only on happy-path sample documents.

---

# 30. Definition of Done

v0.5 завершена только если:

1. OOXML direct L1 works without Office runtime.
2. ODF direct L1 works without LibreOffice.
3. EPUB/FB2/SVG are parsed with hardened package/XML boundaries.
4. Images are inspection-only, no OCR.
5. Optional audio capability is metadata-only.
6. All complex document packages run isolated baseline.
7. Macro/embedded code is never executed.
8. Formula evaluation absent.
9. Package bombs/path traversal are blocked during expansion.
10. Parser selection is registry-based and deterministic.
11. MCP tool count does not grow per format.
12. S3 ContentStore passes same logical lifecycle contract as filesystem.
13. Multi-replica Content access works with S3 profile.
14. L2 remains out of scope.
15. Applicable release gates are green.
