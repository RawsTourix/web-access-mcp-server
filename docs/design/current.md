# Текущее состояние design-проектирования Web Access MCP

## Назначение

Этот документ является кратким навигационным статусом design-проектирования.

Он не заменяет канонические design-файлы и не переопределяет их contracts. Его задача — показать:

- что уже спроектировано;
- что проектируется сейчас;
- какие решения намеренно остаются открытыми;
- какой следующий документ следует разрабатывать.

---

## 1. Concept layer

Статус: **зафиксирован**.

Документы:

- `../project-concept.md`;
- `../architecture-concept.md`.

Зафиксированы:

- backend-first подход;
- единый application backend для REST и MCP;
- основные ответственности Search / Retrieval / Content / Browser / Jobs;
- L0 Inspection / L1 Native Parsing / L2 Advanced Processing;
- отказ от standalone Extraction bounded context;
- отдельный Browser Worker runtime;
- PostgreSQL / Redis / ContentStore как разные infrastructure роли;
- MCP как agent-facing facade;
- REST как богатый программный facade;
- structured hints без скрытой orchestration.

---

## 2. Documentation governance

Статус: **зафиксирован**.

Документы:

- `README.md`;
- `documentation-plan.md`.

Определены:

- уровни Concept / Design / ADR / Versions;
- правило одного канонического владельца темы;
- порядок проектирования;
- стандарт структуры component design;
- требования к документации, пригодной для Codex/ChatGPT implementation.

---

## 3. Архитектурный фундамент

Статус: **зафиксирован**.

Документы:

- `principles.md`;
- `glossary.md`;
- `dependency-rules.md`;
- `system-context.md`;
- `runtime-topology.md`;
- `application-contracts.md`;
- `resource-model.md`;
- `persistence.md`;
- `security.md`.

### Основные принятые решения

Зафиксированы:

- направление зависимостей и ports/adapters;
- единый application protocol;
- `OperationId`, outcomes, warnings, hints, batch/partial-success semantics;
- `unknown outcome` и retry classes;
- opaque Resource handles и ownership;
- immutable ContentObject payload + provenance graph;
- BrowserSession и Job как отдельные resources;
- PostgreSQL как durable structured source of truth;
- Redis как cache/queue/coordination infrastructure;
- ContentStore как storage крупных payloads;
- Transactional Outbox как target consistency model для durable Job publication;
- обязательный reconciliation для cross-system crash windows;
- server-side cleanup/retention;
- security foundation для SSRF, Content, Browser и resource isolation.

---

## 4. Runtime topology

Зафиксированы три основных runtime classes:

```text
Control Plane
Job Worker
Browser Worker
```

Browser Worker владеет live Playwright state.

Control Plane должен масштабироваться горизонтально и не хранить authoritative live browser objects.

Request-bound и durable execution разделены.

---

## 5. Закрытые ранее открытые решения

### Durable Job publication

Принято target-направление:

```text
PostgreSQL Job state
+
Transactional Outbox
→ at-least-once publish в Redis/arq
→ idempotent Job claim
```

Простой незащищённый dual write `DB commit → redis.enqueue` не является целевым production contract.

---

## 6. Намеренно открытые сквозные решения

Пока не зафиксированы:

1. Control Plane ↔ Browser Worker transport.
2. Browser Worker registry/heartbeat/lease/fencing mechanism.
3. Точная DB access policy Browser Worker.
4. Production ContentStore backend.
5. Exact capability-aware readiness schema.
6. Browser session placement algorithm.
7. Нужен ли отдельный isolated executor/runtime для части L1 Native Parsers.
8. Точная Principal/Owner authentication model.

Эти вопросы должны закрываться соответствующими component design/ADR, а не случайным implementation choice.

---

# 7. Текущий следующий этап

Общий foundation завершён.

Начинается подробное проектирование предметных подсистем в порядке:

```text
Search
→ Retrieval
→ Content
→ Browser
→ Jobs
```

Текущий приоритет:

```text
search.md
```

---

## 8. Что должен закрыть `search.md`

Необходимо определить:

- Search responsibilities/non-goals;
- application inputs/results;
- batch semantics поверх общего contract;
- `SearchProvider` port;
- provider registry/selection;
- SearXNG adapter;
- Yandex Search adapter;
- normalization/provenance;
- pagination/limits;
- language/region/time/category semantics;
- cache/freshness;
- provider rate limits/quotas/cost accounting;
- provider availability/degraded behavior;
- error mapping;
- structured hints без reasoning fallback;
- security/privacy;
- observability;
- acceptance criteria.

Search не должен читать найденные страницы и не должен автоматически менять provider из-за оценки «качества» выдачи.

---

## 9. Последующий порядок

После `search.md`:

1. `retrieval.md`;
2. `content.md`;
3. `browser.md`;
4. `jobs.md`;
5. `observability.md`;
6. `rest-api.md`;
7. `mcp.md`;
8. `deployment.md`;
9. `testing.md`;
10. `release-gates.md`;
11. `roadmap.md`;
12. `versions/`.

Порядок может уточняться только если новый dependency analysis показывает реальную необходимость.
