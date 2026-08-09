# AGENTS.md — правила работы с Web Access MCP

## Назначение

Этот файл задаёт обязательные правила для Codex/ChatGPT/другого coding agent при изменении проекта.

Проект спроектирован как production-oriented Web Access service. Coding agent должен **реализовывать уже принятую архитектуру и target version**, а не заменять её MVP/shortcut по собственному усмотрению.

---

# 1. Перед любой production-работой

1. Проверить фактический git HEAD/status/diff.
2. Прочитать [`README.md`](README.md).
3. Прочитать [`design/current.md`](design/current.md).
4. Определить target version и exact patch/step.
5. Прочитать:
   - `design/principles.md`;
   - `design/dependency-rules.md`;
   - relevant component/cross-cutting design;
   - relevant accepted ADR;
   - relevant `design/contracts/*`, если меняется public facade/DTO;
   - target version README;
   - target implementation sequence/release checklist;
   - `design/testing.md`;
   - applicable `design/release-gates.md`.
6. Проверить prerequisites предыдущей версии/шага.

Не начинать patch только по краткому task prompt без восстановления repository design context.

---

# 2. Канонический владелец темы

Не дублировать и не переопределять canonical contracts локально.

Примеры:

```text
application result/retry/batch semantics
→ design/application-contracts.md

resource ownership/lifecycle
→ design/resource-model.md

MCP semantic catalog
→ design/mcp.md + ADR-0022

exact MCP fields/defaults/bounds/result shapes
→ design/contracts/mcp-tools.md

REST semantic facade
→ design/rest-api.md

exact REST /api/v1 contract
→ design/contracts/rest-api-v1.md

common public DTO/error/resource shapes
→ design/contracts/common-models.md

Browser semantics
→ design/browser.md + Browser ADR

Jobs lifecycle
→ design/jobs.md + Jobs ADR

Content L0/L1 boundary
→ design/content.md

External compatibility
→ design/compatibility.md
```

Если implementation обнаружил реальную невозможность/конфликт, сначала оформить design/ADR change и dependent contract update; затем менять код.

---

# 3. Иерархия при конфликте

Использовать:

```text
accepted latest ADR + canonical Design semantics
→ exact public contract spec
→ target version README
→ target implementation sequence
→ concept docs
```

Exact contract spec фиксирует transport shape, но не может самовольно отменить security/lifecycle invariant Design/ADR.

Superseded ADR не реализуется как альтернативный вариант.

---

# 4. Version boundaries

Не переходить к следующей версии без отдельной задачи и acceptance prerequisites.

Design readiness `v0.8` не означает, что можно реализовывать v0.8 до фактически accepted v0.1–v0.7.

Version `implementation-sequence.md` задаёт обязательный порядок патчей. Не начинать с REST/MCP facade, если sequence сначала требует domain/persistence/runtime foundation.

Не добавлять следующую roadmap capability «заодно».

---

# 5. Запрещённые архитектурные shortcuts

Без explicit accepted design change нельзя:

- помещать business logic в FastAPI/FastMCP handlers;
- запускать Playwright прямо в Control Plane request handler;
- хранить authoritative Browser/Job/resource state только в RAM/Redis;
- заменять outbox/claim/fencing прямым `DB commit → Redis enqueue`;
- доверять client `user_id` как identity;
- ослаблять SSRF/browser egress/parser isolation;
- автоматически запускать Browser/OCR/LibreOffice/provider fallback;
- добавлять generic raw HTTP/Playwright/shell/Python public tools;
- создавать `*_many` alias вместо batch-first schema;
- добавлять MCP tool на каждый parser/file format;
- объединять direct operation и durable Job creation в один MCP tool;
- объединять read-only и mutating intents ради уменьшения числа tools;
- менять public contract потому, что internal library API удобнее;
- использовать CSS/XPath как core MCP targeting вместо ElementRef;
- давать Browser child DB/Redis/ContentStore/provider credentials;
- отключать failing race/security/fault test и считать задачу завершённой.

---

# 6. Backend-first

Правильное направление:

```text
transport
→ application
→ domain/ports
← infrastructure implementations
```

REST и MCP вызывают общий application layer.

MCP не вызывает собственный REST, REST не вызывает собственный MCP в baseline composition.

Provider/library types не выходят наружу без явного mapping.

---

# 7. Exact public contracts

Перед facade/schema implementation читать [`design/contracts/README.md`](design/contracts/README.md).

Target specs:

```text
common public models
→ design/contracts/common-models.md

MCP
→ design/contracts/mcp-tools.md

REST
→ design/contracts/rest-api-v1.md
```

Rules:

- unknown public input fields rejected;
- required/default/min/max/enums/list bounds machine-readable;
- discriminated unions отражаются actual JSON Schema;
- runtime validation не заменяется schema-only validation;
- `null`, omitted и default имеют разные описанные semantics;
- private DB/Redis/provider/worker/Playwright fields не попадают public DTO;
- public contract divergence требует explicit docs/ADR update, не молчаливого «implementation detail».

---

# 8. MCP правила

- agent-facing descriptions/fields — на русском;
- каждый public/nested field имеет description;
- exact catalog/fields брать из `design/mcp.md` + `design/contracts/mcp-tools.md`;
- один tool имеет один stable execution/lifecycle class;
- batch only for independent items or one semantic compound action;
- large result → ContentRef/cursor;
- auth secrets не входят arguments;
- unknown mutating outcome нельзя превращать в blind retry;
- no raw selectors, JavaScript, local paths, provider internals;
- FastMCP annotations должны совпадать с exact contract.

Actual FastMCP schema tests обязательны.

---

# 9. REST правила

REST — rich typed facade, но не infrastructure console.

- exact baseline: `design/contracts/rest-api-v1.md`;
- reuse application logic;
- validate auth/owner/scopes;
- use common result/error contracts;
- no raw SQL/Redis/Playwright/provider leakage;
- binary Content — streaming endpoint, не base64 JSON;
- only explicitly designed `Idempotency-Key` semantics;
- mutating Browser endpoint не становится безопасным blind retry из-за HTTP method/header;
- admin surface protected/admin-scoped;
- generated OpenAPI contract-test-ится.

---

# 10. Security

Web input считается недоверенным.

Нельзя ослаблять без explicit review:

- URL/DNS/redirect/TLS validation;
- public-only browser egress;
- Browser session subprocess boundary;
- parser process isolation;
- package/decompression/input/output limits;
- owner/resource authorization;
- secret redaction;
- path/temp safety;
- quotas/backpressure;
- internal service authentication.

Если library требует disabling sandbox/security ради работы, это blocker/design issue, а не повод молча выключить protection.

---

# 11. Persistence / consistency

PostgreSQL — authoritative durable structured state.

Redis — cache/coordination/flow limiting/queue wake-up/short-lived route cache, но не единственный source of truth для durable resource.

ContentStore — large immutable payload storage.

Repositories не hidden-commit.

Crash windows должны иметь explicit state/reconciler/fault test.

Content/Jobs/Browser lifecycle transitions используют state/revision/CAS/fencing согласно design.

---

# 12. Browser-specific rules

Canonical process model:

```text
Browser Worker supervisor
→ one BrowserSession subprocess per logical session
→ Playwright
→ dedicated Chromium
```

Do not implement old direct Browser Worker ownership variant from superseded portion of ADR-0012.

Browser actions:

- serialize per session;
- use action IDs/ledger/status recovery internally;
- ElementRef exact/stale validation;
- no heuristic retargeting;
- response loss after possible side effect may produce `unknown`;
- downloads/screenshots/rendered content become ContentObjects before operation is considered durably handed off where required.

---

# 13. Tests

Не ограничиваться happy path.

Для изменённой capability проверить applicable:

```text
unit
schema/contract
integration
migration
race/concurrency
fault injection
restart/recovery
security
browser lifecycle
soak/leak
load/backpressure
actual REST/OpenAPI
actual FastMCP schemas
e2e
```

Flaky failure — defect до объяснения причины. Один green rerun не является доказательством исправления.

---

# 14. Documentation with code changes

Если код реализует accepted version:

- обновлять `design/current.md` только после factual verification;
- version status менять только по реальному evidence;
- public contract divergence сначала согласовать и отразить в Design/ADR/contracts;
- generated runtime contract fixtures в v0.8+ обновлять только через reviewed compatible change;
- не переписывать архитектуру silently в code comments.

---

# 15. External references

Reference repositories:

```text
RawsTourix/kudago-nominatim-mcp-server
RawsTourix/internet-search-bot
```

Их можно использовать как проверенные implementation patterns/contracts, но Web Access остаётся самостоятельным сервисом и не импортирует их runtime код как hidden dependency без отдельного design.

---

# 16. Completion report

Coding agent final report должен указать:

- target version/patch step;
- changed files;
- migrations/config/dependencies;
- tests и exact results;
- race/security/fault/load evidence where applicable;
- unresolved defects/limitations;
- changed ли public REST/MCP contract;
- какой следующий шаг разрешён implementation sequence.

Не писать «всё готово», если applicable release gate не проверен.
