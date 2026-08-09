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

### `principles.md`

Статус: **зафиксирован**.

Определены сквозные invariants:

- backend-first;
- lazy execution;
- отсутствие hidden reasoning fallback;
- ownership/lifecycle;
- operation identity;
- retry/unknown outcome;
- provenance;
- L0/L1/L2;
- batch-first для независимых операций;
- structured hints;
- scalability;
- MCP/REST роли.

### `glossary.md`

Статус: **зафиксирован**.

Определён общий словарь для последующих design-документов.

### `dependency-rules.md`

Статус: **зафиксирован**.

Определены:

- `domain → application → transport/infrastructure` boundaries;
- ownership ports;
- separation ORM/domain/transport models;
- Control Plane / Job Worker / Browser Worker responsibilities;
- запрет hidden Search→Retrieval→Browser orchestration;
- composition root;
- infrastructure error normalization;
- cross-module dependency rules.

---

## 4. System context

### `system-context.md`

Статус: **зафиксирован**.

Определены:

- внешние actors;
- Web Access system boundary;
- Search/Internet/Advanced L2 boundaries;
- trust boundaries;
- ownership/lifecycle boundaries;
- интеграция с собственным ИИ-агентом и другими clients.

---

## 5. Runtime topology

### `runtime-topology.md`

Статус: **зафиксирован на концептуальном design-уровне**.

Определены три основных runtime classes:

```text
Control Plane
Job Worker
Browser Worker
```

Зафиксированы:

- Browser Worker ownership live Playwright state;
- горизонтальное масштабирование control plane;
- BrowserSession routing requirement;
- request-bound vs durable execution path;
- graceful shutdown direction;
- capability-aware degraded operation;
- separation PostgreSQL / Redis / ContentStore / worker memory.

### Намеренно открытые решения

Пока не зафиксированы:

1. Control Plane ↔ Browser Worker transport.
2. Browser Worker registry/heartbeat mechanism.
3. Необходимость fencing token.
4. Точная DB access policy Browser Worker.
5. Durable Job publication strategy (`reconciliation` / `outbox` / другое).
6. Production ContentStore backend.
7. Exact readiness schema.
8. Browser session placement algorithm.

Эти вопросы должны закрываться соответствующими component design/ADR, а не случайным implementation choice.

---

# 6. Текущий следующий этап

Следующий блок проектирования:

```text
application-contracts.md
        ↓
resource-model.md
        ↓
persistence.md
        ↓
security.md
```

Это последний общий foundation перед подробным проектированием Search / Retrieval / Content / Browser / Jobs.

---

## 7. Приоритет ближайшего документа

### `application-contracts.md`

Нужно определить единый application protocol проекта:

- `OperationId`;
- `ExecutionContext`;
- principal/owner context;
- deadline/cancellation;
- `OperationResult`;
- `OperationOutcome`;
- `OperationError`;
- warnings;
- structured hints;
- provenance references;
- batch semantics;
- partial success;
- retry/idempotency classes;
- unknown outcome;
- operation metadata.

Этот документ должен стать общим основанием для всех последующих application services и обоих transport facades.

---

## 8. После общего foundation

После `application-contracts.md`, `resource-model.md`, `persistence.md`, `security.md` проектирование идёт в порядке:

1. `search.md`;
2. `retrieval.md`;
3. `content.md`;
4. `browser.md`;
5. `jobs.md`;
6. `observability.md`;
7. `rest-api.md`;
8. `mcp.md`;
9. `deployment.md`;
10. `testing.md`;
11. `release-gates.md`;
12. `roadmap.md`;
13. `versions/`.

Порядок может уточняться только если новый dependency analysis показывает реальную необходимость.
