# v0.3 — Retrieval & Content Core

## Статус

`design in progress`

Версия реализует законченный flow:

```text
известный URL
→ безопасный HTTP(S) Retrieval
→ raw ContentObject
→ L0 Inspection
→ доступный L1 Native Parsing
→ bounded REST/MCP result
```

без Browser и без L2.

---

# 1. Prerequisites

- accepted v0.1;
- accepted/available v0.2 Search для полного agent workflow, хотя Retrieval технически не зависит от Search runtime;
- `../../retrieval.md`;
- `../../content.md`;
- `../../resource-model.md`;
- `../../persistence.md`;
- `../../security.md`;
- `../../rest-api.md`;
- `../../mcp.md`;
- `../../testing.md`;
- ADR-0006 Safe Retrieval transport;
- ADR-0007 Content staging/finalization;
- ADR-0008 initial Native Parser stack.

---

# 2. Scope Retrieval

- aiohttp SafeHttpFetcher;
- validating custom resolver;
- only HTTP/HTTPS GET;
- manual redirects;
- TLS verify;
- no environment proxy;
- streaming limits;
- deadlines/cancellation;
- batch-first URL fetch;
- HTTP response metadata;
- raw Content handoff.

---

# 3. Scope Content

- ContentObject PostgreSQL lifecycle;
- Content relations/provenance;
- ContentStore staging/finalization protocol;
- filesystem ContentStore production-quality local adapter;
- L0 Inspection;
- format registry;
- parser registry;
- L1 parser execution;
- isolated parser subprocess foundation;
- HTML main + structural parsing;
- text/JSON/XML/CSV;
- PDF native text;
- derived representations;
- content read/chunking;
- retention/reconciliation.

---

# 4. Initial format capabilities

Required:

```text
HTML/HTM
plain text
JSON
XML
CSV
PDF native text
```

Также L0 должен корректно распознавать unsupported/binary formats насколько позволяет identification stack, даже если L1 parser отсутствует.

---

# 5. Explicit non-goals

- Browser;
- JavaScript rendering;
- OCR;
- VLM;
- LibreOffice;
- DOCX/XLSX/PPTX/ODF full parsing;
- image understanding;
- audio/video transcription;
- arbitrary file conversion;
- request-bound auto→Job promotion;
- generic upload UI unless implementation-sequence explicitly includes minimal REST import.

---

# 6. MCP tools

v0.3 добавляет:

```text
web_fetch
content_get
content_parse
```

Никаких:

```text
web_read
web_fetch_many
read_pdf
read_docx
```

---

# 7. `web_fetch`

Input baseline:

```text
urls: list[HttpUrl]
```

Один URL — список из одного.

MCP не принимает:

- method;
- arbitrary headers;
- cookies;
- auth;
- browser mode;
- parser ID;
- OCR option.

Backend mapping:

```text
Retrieval GET
→ Content processing_level=native
```

---

# 8. `web_fetch` result

Per URL должен содержать:

- requested/final URL;
- HTTP status/redirect summary;
- detected format;
- raw ContentRef при body;
- available derived ContentRefs;
- preferred bounded native preview, если есть;
- key inspection metadata;
- warnings/hints/error.

Search/retrieval web content остаётся untrusted.

---

# 9. `content_get`

Читает **конкретный ContentObject**.

Input batch items:

```text
content_id
cursor | null
```

ContentObject immutable, поэтому cursor безопасно продолжает bounded read той же representation.

Если ContentObject binary/non-textual:

- metadata возвращается;
- inline text отсутствует;
- available representations/hints подсказывают следующий шаг.

Для выбора Markdown/text representation клиент использует `content_id` соответствующего derived object, а не `representation="markdown"` поверх raw PDF.

---

# 10. `content_parse`

Запускает L1 Native Parsing существующих ContentObjects:

```text
content_ids[]
```

Canonical parser выбирается registry по detected format.

LLM не передаёт parser ID.

Если L1 unavailable:

- raw object остаётся;
- result сообщает diagnostics/hint;
- no OCR/Browser/Job hidden escalation.

---

# 11. Content DB model direction

v0.3 вводит как минимум:

```text
content_objects
content_relations
```

`content_objects` содержит:

- public content_id;
- owner principal;
- lifecycle/revision;
- representation kind;
- media/detected format;
- size/hash;
- internal storage/staging key;
- inspection/metadata JSONB bounded;
- producer/parser/schema revision;
- timestamps/retention.

`content_relations` хранит typed provenance (`derived_from` и future relation types) без giant graph payload.

Exact schema фиксируется implementation-sequence/migration.

---

# 12. Preferred derived representations

Initial canonical behavior:

## HTML

- raw HTML ContentObject;
- derived Markdown ContentObject, если main-content extraction дала содержимое;
- structural inspection/metadata хранится bounded metadata/inspection model, а не обязательно отдельным JSON blob.

## PDF

- raw PDF;
- derived `text/plain` ContentObject, если native text layer доступен.

## Plain text

Raw ContentObject уже является textual representation; лишняя копия не обязательна после decode validation.

## JSON/XML/CSV

Raw сохраняется; Native Parsing возвращает typed inspection/structured summary и создаёт derived ContentObject только если canonical normalized representation действительно отличается/нужна для большого structured output.

Не создавать derived blobs «для симметрии» без практической пользы.

---

# 13. Required hints

Как минимум:

```text
browser_may_be_required
advanced_processing_may_be_required
native_parser_unavailable
processing_requires_job (foundation for future)
alternative_representation_available
```

`browser_may_be_required` допустим только на objective HTML diagnostic вроде «нет статического текста + присутствуют script-driven document signals», а не на произвольный threshold качества.

---

# 14. Required gates

- G0–G6;
- G8 Retrieval;
- G9 Content;
- G12–G15;
- G17 race/fault;
- G20 own-agent integration;
- G21 docs consistency.

Parser/security/fault tests обязательны до acceptance.

---

# 15. Acceptance criteria

1. `web_fetch` безопасно получает 1..N URLs без Browser.
2. DNS/connect rebinding protection подтверждён tests.
3. Redirect private target blocked.
4. Body streaming bounded, no silent truncation.
5. Raw ContentObject проходит ADR-0007 lifecycle.
6. Crash windows Content reconciled.
7. L0 format identification не доверяет extension/MIME единолично.
8. HTML returns native Markdown where directly available.
9. Empty JS shell returns raw/metadata + Browser hint, no Browser call.
10. PDF native text returns derived text.
11. Image-only PDF returns raw + no-native-text/L2 hint, no OCR.
12. PDF parser isolated process and hard timeout kills child.
13. XML entity/security fixtures blocked.
14. Large text uses ContentRef/cursor.
15. `content_get` reads immutable representation without re-fetch.
16. `content_parse` does L1 only.
17. MCP has no format-specific parser tools.
18. REST exposes rich Content metadata/data/native processing.
19. Cross-owner Content access denied.
20. Required gates green, 0 flaky failures.

---

# 16. Remaining blockers

До `ready for implementation` требуется `implementation-sequence.md`, который фиксирует:

- exact Retrieval limits/timeouts;
- exact aiohttp SafeResolver implementation shape;
- exact Content SQL schema/indexes;
- exact content read cursor;
- exact identification library/magic strategy;
- exact parser limits;
- exact isolated subprocess protocol;
- exact MCP schemas/hard bounds;
- exact retention/reconciler defaults.
