# v0.5 — Implementation sequence

## Назначение

Обязательный порядок реализации Native Content Expansion и S3 ContentStore.

Главное правило:

> Сначала расширяются общие Content/package/isolation primitives и их security tests. Форматные adapters добавляются только поверх них. REST/MCP не получают format-specific shortcuts.

---

# Patch C0 — Baseline/fixture foundation

1. Убедиться, что v0.3 Content lifecycle/parser isolation tests зелёные.
2. Зафиксировать actual v0.3 Content REST/MCP schemas.
3. Создать synthetic fixture corpus для package/image/document security cases.
4. Никаких больших copyrighted real documents в repository.
5. Добавить dependency/security scanning для новых parser libraries.

**Gate:** baseline не меняется до добавления новых capabilities.

---

# Patch C1 — ContentFormatRegistry evolution

Расширить descriptor:

```text
format_id
signatures/media types/package markers
parser_id
parser_revision
execution_profile
representations
limits_profile
capabilities
```

Requirements:

- deterministic registration;
- no duplicate/conflicting signature mapping;
- registry revision;
- test listing;
- format extension not authoritative;
- parser IDs internal/provenance only.

Добавить capability tests до concrete formats.

---

# Patch C2 — SafePackageReader

Создать infrastructure primitive для ZIP-based document containers.

Реализовать:

- normalized member names;
- no absolute/parent traversal;
- no `extractall()`;
- entry count limit;
- individual/total uncompressed limits;
- compression ratio guard;
- bounded streaming/member reads;
- special/symlink entry policy;
- no nested archive recursion;
- package manifest helpers без provider-specific domain leak.

Security fixtures:

- traversal;
- duplicate/conflicting names;
- zip bomb;
- huge entry count;
- truncated central directory;
- malformed compression;
- large single member.

**Gate:** package security proven independently of DOCX/EPUB/etc.

---

# Patch C3 — Parser isolation profile hardening

Расширить v0.3 `IsolatedProcessParserExecutor` для package/image/media parsers.

Requirements:

- parser-specific profile descriptor;
- hard input/output/wall limits;
- child environment allowlist;
- no network credentials;
- process terminate/kill/reap;
- versioned JSON result;
- package temp/input cleanup;
- concurrent isolated parser admission limit;
- metrics.

Не вводить reusable worker pool без benchmark. Short-lived process остаётся canonical safe baseline.

---

# Patch C4 — DOCX adapter

Dependency: `python-docx` pinned via lock.

Implement:

- validation as compatible OOXML package;
- paragraphs/headings;
- bounded tables;
- metadata;
- links where safely available;
- headers/footers where deterministic;
- embedded media inventory metadata;
- no external fetch;
- no macro execution.

Run isolated process profile.

Test malformed/large/relationship edge cases.

---

# Patch C5 — XLSX adapter

Dependency: `openpyxl` pinned.

Use read-only/memory-conscious path.

Implement:

- sheets;
- bounded row/cell iteration;
- formula text;
- cached value metadata where available;
- merged/basic worksheet metadata;
- workbook metadata.

Do not calculate formulas.

Tests:

- huge row/column dimensions;
- sparse workbook;
- formulas;
- external links;
- malformed workbook;
- emitted-cell/row limits;
- timeout/kill.

---

# Patch C6 — PPTX adapter

Dependency: `python-pptx` pinned.

Implement:

- slide order;
- text-bearing shapes;
- tables;
- links;
- notes where supported/reliable;
- image/media inventory;
- bounded shape count/output.

No chart/diagram visual reasoning.

Malformed package tests.

---

# Patch C7 — ODF package adapters

Implement common ODF package helper over SafePackageReader + hardened XML.

Then adapters:

```text
ODT
ODS
ODP
```

Special focus:

- repeated ODS rows/cells must not expand unbounded;
- styles are read only when required for semantic structure;
- no embedded script execution;
- no external resources.

No LibreOffice dependency.

---

# Patch C8 — EPUB adapter

Implement:

```text
mimetype/container validation
→ container.xml
→ package document
→ manifest
→ spine
→ bounded ordered XHTML chapters
```

Reuse hardened HTML/XML content extraction where appropriate.

No scripts/external fetch.

Test malformed spine/manifest, traversal package paths and huge chapter sets.

---

# Patch C9 — FB2 and SVG

Use hardened XML path.

FB2:

- metadata;
- sections/headings/paragraphs;
- notes/links;
- bounded embedded-image metadata.

SVG:

- title/desc/text;
- links;
- dimensions/viewBox;
- bounded semantic structure.

No visual interpretation.

---

# Patch C10 — Bitmap image inspection

Dependency: Pillow pinned.

Run isolated.

Implement only L0:

- format;
- dimensions;
- frame/animation count;
- mode;
- orientation;
- bounded EXIF/basic metadata.

Keep decompression-bomb safeguards.

Test extreme dimensions, malformed metadata, animated files and process limits.

---

# Patch C11 — Audio technical metadata profile

Dependency: Mutagen pinned **only if this optional capability is enabled in v0.5 build**.

Implement L0 technical/tag metadata, no audio decode/transcription.

If dependency/format behavior fails security/maintenance review, omit capability from release rather than replacing it with ffmpeg/L2 pipeline silently.

---

# Patch C12 — Parser representation reuse/provenance

Ensure all new adapters produce immutable derived ContentObjects with:

- parser id/revision;
- representation schema revision;
- source content;
- profile/parameters hash;
- warnings/diagnostics.

Existing compatible derived representation may be reused according v0.3 Content rules.

No cross-owner logical Content reuse leak.

---

# Patch C13 — S3 adapter foundation

Add boto3/botocore pinned dependencies.

Implement dedicated bounded S3 I/O executor.

Config:

- endpoint;
- bucket/prefix;
- region;
- credentials/provider chain;
- TLS;
- multipart profile;
- executor capacity.

Do not alter application ContentStore port to expose boto3 types.

---

# Patch C14 — S3 stage/finalize/read/GC

Implement ADR-0016:

- stage stream;
- multipart;
- SHA-256/size;
- hash final key;
- HEAD/reuse;
- copy/multipart copy finalize;
- range read;
- staging delete;
- final delete;
- reconciliation.

Run same ContentStore contract tests for filesystem + S3.

Fault injection at copy/DB windows.

---

# Patch C15 — S3 Compose integration profile

Add optional local/integration profile with reference S3-compatible object storage.

Requirements:

- isolated credentials;
- no public anonymous bucket;
- readiness;
- persistent volume only where profile requires;
- automated adapter contract suite;
- multiple Control Plane replicas can read same ContentObject.

Filesystem remains default simple developer profile.

---

# Patch C16 — Content application/capability API update

Expose deterministic format/capability metadata through existing Content application services.

`content_parse`:

- uses identified format + registry;
- optional stable requested representation only where contract supports it;
- no concrete library selector;
- structured unsupported/limit diagnostics.

`web_fetch` can use default direct L1 pipeline only within request-bound budget.

No automatic durable job before v0.6.

If parse exceeds request-bound profile:

```text
return raw content + diagnostic/hint
```

rather than silently waiting indefinitely.

---

# Patch C17 — REST projection

Extend generic Content API:

- supported capability/status discovery for authorized clients;
- parse existing ContentObject;
- representations/provenance metadata;
- S3-backed data streaming stays transparent.

Do not add `/parse/docx`, `/parse/xlsx`, etc.

Actual OpenAPI snapshot/negative tests required.

---

# Patch C18 — MCP projection

Keep compact tool catalog.

Review actual FastMCP schemas for:

```text
web_fetch
content_get
content_parse
```

Requirements:

- Russian descriptions;
- detected format explained;
- no parser-library enum;
- no format-specific tools;
- structured hints;
- bounded output/ContentRef behavior;
- correct annotations.

---

# Patch C19 — Security/fuzz/fault roast

Run broad corpus:

- package bombs;
- traversal;
- malformed OOXML/ODF/EPUB;
- huge spreadsheet dimensions/repetitions;
- active/macro content;
- XML attacks;
- image bombs;
- metadata bombs;
- isolated parser hangs/crashes;
- temp/reaper faults;
- S3 permission/network failures;
- concurrent finalization/GC.

No parser crash may crash Control Plane.

---

# Patch C20 — Soak/load

Measure:

- isolated parser process churn;
- max concurrent parses;
- package expansion throughput;
- XLSX large bounded iteration;
- S3 executor saturation;
- multipart throughput;
- memory/temp leakage;
- representation storage growth.

Optimization (reusable parser pool, changed limits) only after measurements and without weakening isolation.

---

# Patch C21 — Documentation/acceptance closure

1. registry lists only actually implemented/tested formats;
2. version docs match actual dependencies;
3. actual MCP/OpenAPI schemas reviewed;
4. ContentStore contract passes filesystem + S3;
5. no LibreOffice/OCR/VLM dependency accidentally added;
6. release gate evidence recorded;
7. `current.md` updated.

---

# Forbidden shortcuts

Implementation must not:

- call LibreOffice to make unsupported Office file readable;
- invoke OCR/VLM automatically;
- use ZIP `extractall()` on untrusted package;
- parse arbitrary nested archives recursively;
- run macros/formulas;
- add one MCP tool per file format;
- expose parser package names as required LLM choice;
- run complex package parser in Control Plane process merely for convenience;
- treat S3 ETag as canonical content hash;
- block asyncio loop with boto3 calls;
- grant Browser session subprocess S3 credentials;
- make S3 bucket public for Content delivery.

---

# Final acceptance

v0.5 считается завершённой только после выполнения Definition of Done из README и всех applicable Content/security/storage release gates.
