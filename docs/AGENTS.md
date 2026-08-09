# AGENTS.md — правила работы с Web Access MCP

## Назначение

Этот файл задаёт обязательные правила для Codex/ChatGPT/другого coding agent при изменении проекта.

Проект спроектирован как production-oriented Web Access service. Coding agent должен **реализовывать уже принятую архитектуру**, а не заменять её более простым MVP/shortcut по собственному усмотрению.

---

# 1. Перед любой работой

1. Прочитать [`README.md`](README.md).
2. Прочитать [`design/current.md`](design/current.md).
3. Определить target version/component.
4. Прочитать:
   - `design/principles.md`;
   - `design/dependency-rules.md`;
   - relevant component design;
   - relevant accepted ADR;
   - target version README;
   - target implementation sequence;
   - `design/testing.md`;
   - applicable `design/release-gates.md`.
5. Проверить фактический git HEAD/status/diff перед изменениями.

Не начинать production patch только по краткому пользовательскому prompt без восстановления repository design context.

---

# 2. Канонический владелец темы

Не дублировать и не переопределять canonical contracts локально.

Примеры:

```text
MCP tool catalog
→ design/mcp.md + ADR-0021/ADR-0022

Browser semantics
→ design/browser.md + Browser ADR

Jobs lifecycle
→ design/jobs.md + Jobs ADR

Content L0/L1 boundary
→ design/content.md

External compatibility
→ design/compatibility.md
```

Если implementation обнаружил реальный конфликт/невозможность, сначала оформить/согласовать design change/ADR, затем менять код.

---

# 3. Version boundaries

Не переходить к следующей версии без отдельной задачи/acceptance.

Если target — v0.2, нельзя «заодно» начать Browser/Jobs/v0.3.

Version `implementation-sequence.md` задаёт порядок патчей. Не начинать с REST/MCP facade, если sequence сначала требует domain/persistence/runtime foundation.

---

# 4. Запрещённые архитектурные shortcuts

Без explicit accepted design change нельзя:

- помещать business logic в FastAPI/FastMCP handlers;
- запускать Playwright прямо в Control Plane request handler;
- хранить authoritative Browser/Job/resource state только в RAM/Redis;
- заменять outbox/claim/fencing прямым `DB commit → Redis enqueue`;
- доверять client user ID как identity;
- ослаблять SSRF/browser egress security;
- автоматически запускать Browser/OCR/LibreOffice/provider fallback;
- добавлять generic raw HTTP/Playwright/shell/Python public tools;
- создавать `*_many` alias вместо batch-first schema;
- добавлять MCP tool на каждый parser/file format;
- менять public contract потому, что internal library API удобнее;
- отключать failing race/security test и считать задачу завершённой.

---

# 5. Backend-first

Правильная зависимость:

```text
transport
→ application
→ domain/ports
← infrastructure implementations
```

REST и MCP должны вызывать общий application layer.

Provider/library types не выходят наружу без явного mapping.

---

# 6. MCP правила

- agent-facing descriptions/fields — на русском;
- каждый public/nested field имеет description;
- actual JSON Schema содержит machine-readable bounds/invariants;
- runtime validation обязательна;
- один tool имеет один stable execution/lifecycle class;
- exact tool catalog брать из `design/mcp.md`, не из старого task prompt;
- large result → ContentRef/cursor, не giant inline payload;
- auth secrets не входят tool arguments;
- unknown mutating outcome нельзя превращать в blind retry.

Actual FastMCP schema tests обязательны для contract change.

---

# 7. REST правила

REST — rich typed facade, но не infrastructure console.

- reuse application logic;
- validate auth/owner;
- use common result/error contracts;
- no raw SQL/Redis/Playwright/provider object leakage;
- streaming/binary endpoints bounded;
- OpenAPI actual fixture/gate после v0.8;
- admin surface REST-only and admin-scoped baseline.

---

# 8. Security

Web input считается недоверенным.

Нельзя ослаблять без explicit review:

- URL/DNS/redirect/TLS validation;
- browser public-only egress;
- parser process isolation;
- package/decompression limits;
- owner/resource authorization;
- secret redaction;
- path/temp safety;
- quotas/backpressure.

Если библиотека требует disabling sandbox/security ради работы, это blocker/design issue, а не повод молча выключить protection.

---

# 9. Persistence / consistency

PostgreSQL — authoritative durable structured state.

Redis — cache/coordination/flow limiting/queue wake-up, но не единственный source of truth для durable resource.

Repositories не hidden-commit.

Crash windows должны иметь explicit recovered state/reconciler test.

Content/Jobs/Browser lifecycle transitions используют state/revision/CAS/fencing согласно design.

---

# 10. Tests

Не ограничиваться happy path.

Для изменённой capability проверить applicable:

```text
unit
contract
integration
race/concurrency
fault injection
restart/recovery
security
soak/leak
load/backpressure
actual REST/MCP schemas
```

Flaky failure — defect до объяснения причины. Один green rerun не является доказательством исправления.

---

# 11. Documentation with code changes

Если код реализует/изменяет accepted version:

- update implementation status/evidence in `design/current.md` only after factual verification;
- update docs when actual schema/behavior differs from planned detail;
- do not rewrite architecture silently inside code comments;
- public contract change follows `design/compatibility.md`.

---

# 12. External references

Reference repositories can be used as proven implementation patterns:

```text
RawsTourix/kudago-nominatim-mcp-server
RawsTourix/internet-search-bot
```

Но Web Access remains a separate service and must not import their runtime code as hidden dependency unless a future design explicitly establishes shared package.

---

# 13. Completion report

Coding agent final report should state:

- changed files;
- implemented target patch/version step;
- migrations/config changes;
- tests run and exact result;
- race/security/fault evidence where applicable;
- unresolved limitations/blockers;
- whether public REST/MCP contract changed;
- next implementation step from sequence.

Не писать «всё готово», если applicable release gate не проверен.
