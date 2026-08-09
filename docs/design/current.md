# Текущее состояние design-проектирования Web Access MCP

## Назначение

Этот документ является кратким навигационным статусом проекта. Он не переопределяет канонические contracts; его задача — показать, что уже спроектировано, что ещё не реализовано и какой следующий шаг допустим.

---

# 1. Общий статус

**Архитектурный design первой stable line v1.0 спроектирован. Production-код сервиса ещё не реализован.**

Выполнены:

```text
Concept
→ architecture foundation
→ component design
→ runtime/infrastructure design
→ REST/MCP facade design
→ ADR decisions
→ exact public contracts
→ version roadmap v0.1..v1.0
→ implementation sequences
→ testing/release/operational gates
```

Следующий канонический этап после финального consistency-аудита документации:

```text
реализация v0.1 Service Foundation
```

Нельзя начинать v0.2+ до отдельной задачи и acceptance предыдущей версии.

---

# 2. Concept layer

Зафиксирован:

- `../project-concept.md`;
- `../architecture-concept.md`.

Главные границы:

- backend-first;
- единый application backend для REST/MCP;
- Search / Retrieval / Content / Browser / Jobs;
- L0 Inspection / L1 Native Parsing;
- L2 Advanced Processing вне Web Access;
- structured hints без hidden orchestration;
- REST — rich programmatic facade;
- MCP — compact LLM-facing facade.

---

# 3. Архитектурный foundation

Канонические документы:

- `principles.md`;
- `glossary.md`;
- `dependency-rules.md`;
- `system-context.md`;
- `runtime-topology.md`;
- `application-contracts.md`;
- `resource-model.md`;
- `persistence.md`;
- `security.md`.

Зафиксированы:

- direction of dependencies / ports-adapters;
- common `OperationResult`/error/warning/hint/batch semantics;
- `unknown outcome` и retry classes;
- opaque resources/ownership;
- immutable Content representations + provenance;
- PostgreSQL/Redis/ContentStore responsibilities;
- transactional outbox/reconciliation;
- SSRF/egress/parser/browser/resource security boundaries.

---

# 4. Component design

Зафиксированы:

- `search.md`;
- `retrieval.md`;
- `content.md`;
- `browser.md`;
- `jobs.md`;
- `observability.md`;
- `policy-and-operations.md`;
- `operational-readiness.md`;
- `limitations.md`.

Крупных component-level архитектурных blockers для текущего roadmap не осталось.

---

# 5. Runtime topology

Основные runtime classes:

```text
Control Plane
Job Worker
Browser Worker supervisor
BrowserSession subprocess
```

Внешние dependencies/services:

```text
PostgreSQL
Redis
ContentStore
SearXNG
optional Yandex Search
Browser Egress Gateway
```

BrowserSession:

```text
1 logical BrowserSession
→ 1 session subprocess
→ 1 Playwright runtime
→ 1 dedicated Chromium
→ N bounded Pages
```

MCP connection lifetime не владеет BrowserSession/Job/Content lifecycle.

---

# 6. Accepted ADR

Реестр: `decisions/README.md`.

Особенно важные chains:

```text
Browser:
ADR-0001, ADR-0009..0014

Content:
ADR-0007, ADR-0008, ADR-0015, ADR-0016

Jobs:
ADR-0017, ADR-0018

Policy/usage:
ADR-0019, ADR-0020

External contract/freeze:
ADR-0021, ADR-0022
```

При конфликте старого exploratory текста с accepted ADR приоритет имеет canonical Design + latest non-superseded ADR.

---

# 7. Public facades

Канонические semantic docs:

- `rest-api.md`;
- `mcp.md`;
- `compatibility.md`;
- `agent-integration.md`.

Exact transport-facing specs:

- `contracts/common-models.md`;
- `contracts/mcp-tools.md`;
- `contracts/rest-api-v1.md`.

MCP core freeze candidate содержит 27 tools и не включает raw Playwright/HTTP/L2/generic task primitives.

REST `/api/v1` является более богатым typed facade и включает protected operator/admin surface.

Generated FastMCP/OpenAPI fixtures появляются и freeze-ятся в v0.8 после фактической реализации.

---

# 8. Version design

Roadmap: `roadmap.md`.

Текущие design statuses:

```text
v0.1 Service Foundation                       ready for implementation
v0.2 Search Runtime                           ready for implementation
v0.3 Retrieval & Content Core                 ready for implementation
v0.4 Managed Browser Runtime                  ready for implementation
v0.5 Native Content Expansion                 ready for implementation
v0.6 Durable Jobs Runtime                     ready for implementation
v0.7 Distributed Operations & Policy          ready for implementation
v0.8 REST/MCP & Agent Integration Stabilization ready for implementation
v0.9 Production Hardening                     ready for implementation
v1.0 Stable Web Access                        release contract defined
```

`ready for implementation` означает готовность design конкретной версии, **не разрешение перепрыгивать предыдущие milestones**.

---

# 9. Тестирование и release evidence

Канонические документы:

- `testing.md`;
- `release-gates.md`;
- `deployment.md`;
- `operational-readiness.md`.

Roadmap требует не только unit/integration, но также contract, race, fault, restart/recovery, security, soak/leak, load/backpressure, migration/restore и rolling-upgrade evidence в соответствующих версиях.

---

# 10. Что намеренно не входит в v1.0 line

См. `limitations.md`.

В частности baseline не обещает:

- L2 OCR/VLM/LibreOffice/transcription;
- CAPTCHA bypass/stealth;
- arbitrary JS/code execution;
- raw HTTP proxy;
- generic arbitrary Job runner;
- persistent browser profiles;
- live BrowserSession migration между workers;
- automatic Search→Retrieval→Browser orchestration.

Это designed boundaries, а не defects.

---

# 11. Следующий шаг

После последнего документационного consistency check можно формировать подробный coding prompt для **только v0.1 Service Foundation** на основе:

```text
docs/AGENTS.md
→ docs/design/current.md
→ foundation design/ADR
→ docs/design/versions/v0.1/README.md
→ docs/design/versions/v0.1/implementation-sequence.md
→ testing/release gates
```

Реализация должна идти version-by-version с factual acceptance evidence перед переходом дальше.
